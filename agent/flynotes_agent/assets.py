from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .config import AgentConfig
from .schemas import AssetResponse, JobResponse


class AssetStore:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.database_path = config.database_path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS assets (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    thumbnail_path TEXT,
                    media_type TEXT NOT NULL,
                    width INTEGER,
                    height INTEGER,
                    duration REAL,
                    fps REAL,
                    has_audio INTEGER NOT NULL DEFAULT 0,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    workflow_version TEXT,
                    mode TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    actual_seed INTEGER,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    @property
    def ffprobe(self) -> Path:
        return self.config.comfy_root / "ffmpeg" / "bin" / "ffprobe.exe"

    @property
    def ffmpeg(self) -> Path:
        return self.config.comfy_root / "ffmpeg" / "bin" / "ffmpeg.exe"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def _probe(self, path: Path) -> dict[str, Any]:
        if not self.ffprobe.is_file():
            return {}
        result = subprocess.run(
            [
                str(self.ffprobe),
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        if result.returncode:
            return {"probeError": result.stderr[-2000:]}
        try:
            value = json.loads(result.stdout)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _thumbnail(self, asset_id: str, path: Path) -> Path | None:
        if not self.ffmpeg.is_file():
            return None
        directory = self.config.data_root / "thumbnails"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{asset_id}.jpg"
        result = subprocess.run(
            [
                str(self.ffmpeg),
                "-y",
                "-ss",
                "0",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "scale='min(512,iw)':-2",
                str(target),
            ],
            capture_output=True,
            timeout=120,
            check=False,
        )
        return target if result.returncode == 0 and target.is_file() else None

    @staticmethod
    def _fraction(value: str | None) -> float | None:
        try:
            numerator, denominator = str(value).split("/", 1)
            return float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            return None

    def register(self, job: JobResponse, result_path: Path) -> AssetResponse:
        path = result_path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        existing = self.get_by_path(path)
        if existing:
            return existing
        metadata = self._probe(path)
        streams = metadata.get("streams", []) if isinstance(metadata, dict) else []
        video = next((item for item in streams if item.get("codec_type") == "video"), {})
        has_audio = any(item.get("codec_type") == "audio" for item in streams)
        format_data = metadata.get("format", {}) if isinstance(metadata, dict) else {}
        try:
            duration = float(format_data.get("duration"))
        except (TypeError, ValueError):
            duration = None
        asset_id = f"asset_{uuid.uuid4().hex}"
        thumbnail = self._thumbnail(asset_id, path)
        created_at = datetime.now(UTC).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO assets (
                    id, job_id, path, thumbnail_path, media_type, width, height,
                    duration, fps, has_audio, size_bytes, sha256, model_id,
                    workflow_version, mode, prompt, parameters_json, actual_seed,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    job.id,
                    str(path),
                    str(thumbnail) if thumbnail else None,
                    "video",
                    video.get("width"),
                    video.get("height"),
                    duration,
                    self._fraction(video.get("avg_frame_rate")),
                    int(has_audio),
                    path.stat().st_size,
                    self._sha256(path),
                    job.modelId,
                    job.workflowVersion,
                    job.mode,
                    job.prompt,
                    json.dumps(job.parameters, ensure_ascii=False),
                    job.actualSeed,
                    json.dumps(metadata, ensure_ascii=False),
                    created_at,
                ),
            )
        result = self.get(asset_id)
        assert result is not None
        return result

    @staticmethod
    def _row(row: sqlite3.Row) -> AssetResponse:
        return AssetResponse(
            id=row["id"],
            jobId=row["job_id"],
            path=row["path"],
            thumbnailPath=row["thumbnail_path"],
            mediaType=row["media_type"],
            width=row["width"],
            height=row["height"],
            duration=row["duration"],
            fps=row["fps"],
            hasAudio=bool(row["has_audio"]),
            sizeBytes=row["size_bytes"],
            sha256=row["sha256"],
            modelId=row["model_id"],
            workflowVersion=row["workflow_version"],
            mode=row["mode"],
            prompt=row["prompt"],
            parameters=json.loads(row["parameters_json"]),
            actualSeed=row["actual_seed"],
            createdAt=datetime.fromisoformat(row["created_at"]),
        )

    def get(self, asset_id: str) -> AssetResponse | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)).fetchone()
        return self._row(row) if row else None

    def get_by_path(self, path: Path) -> AssetResponse | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM assets WHERE path = ?", (str(path.resolve()),)).fetchone()
        return self._row(row) if row else None

    def list(self, limit: int = 200) -> list[AssetResponse]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM assets ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row(row) for row in rows]
