from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from .schemas import UploadResponse


class UploadNotFound(FileNotFoundError):
    pass


class UploadStore:
    CHUNK_SIZE = 1024 * 1024
    SAFE_SUFFIX = re.compile(r"^\.[A-Za-z0-9]{1,10}$")

    def __init__(self, staging_root: Path) -> None:
        self.root = staging_root / "uploads"

    def initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _metadata_path(directory: Path) -> Path:
        return directory / "metadata.json"

    def save(
        self,
        stream: BinaryIO,
        *,
        original_name: str,
        content_type: str = "application/octet-stream",
    ) -> UploadResponse:
        self.initialize()
        upload_id = f"upload_{uuid.uuid4().hex}"
        directory = self.root / upload_id
        directory.mkdir(parents=False, exist_ok=False)
        suffix = Path(original_name).suffix.lower()
        if not self.SAFE_SUFFIX.fullmatch(suffix):
            suffix = ".bin"
        payload_path = directory / f"payload{suffix}"
        digest = hashlib.sha256()
        size = 0
        try:
            with payload_path.open("wb") as target:
                while chunk := stream.read(self.CHUNK_SIZE):
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            created_at = datetime.now(UTC)
            response = UploadResponse(
                id=upload_id,
                originalName=Path(original_name).name or f"file{suffix}",
                size=size,
                sha256=digest.hexdigest(),
                contentType=content_type or "application/octet-stream",
                createdAt=created_at,
            )
            self._metadata_path(directory).write_text(
                response.model_dump_json(indent=2), encoding="utf-8"
            )
            return response
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise

    def get(self, upload_id: str) -> tuple[UploadResponse, Path]:
        if not re.fullmatch(r"upload_[a-f0-9]{32}", upload_id):
            raise UploadNotFound(upload_id)
        directory = self.root / upload_id
        metadata_path = self._metadata_path(directory)
        try:
            response = UploadResponse.model_validate_json(
                metadata_path.read_text(encoding="utf-8")
            )
            payloads = [path for path in directory.glob("payload.*") if path.is_file()]
        except (OSError, ValueError) as error:
            raise UploadNotFound(upload_id) from error
        if len(payloads) != 1:
            raise UploadNotFound(upload_id)
        return response, payloads[0]

    def stage_for_comfy(
        self,
        *,
        upload_id: str,
        comfy_input_root: Path,
        job_id: str,
        role: str,
        index: int,
    ) -> str:
        _metadata, source = self.get(upload_id)
        safe_role = re.sub(r"[^a-z0-9_]+", "_", role.lower()).strip("_") or "input"
        relative_dir = Path("flynotes") / job_id
        target_dir = comfy_input_root / relative_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{safe_role}_{index}{source.suffix}"
        shutil.copy2(source, target)
        return (relative_dir / target.name).as_posix()
