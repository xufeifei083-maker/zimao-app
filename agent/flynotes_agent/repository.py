from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .registry import ModelRegistry
from .schemas import JobCreateRequest, JobResponse, JobStatus


class DuplicateClientRequest(ValueError):
    pass


class JobRepository:
    def __init__(self, database_path: Path, registry: ModelRegistry) -> None:
        self.database_path = database_path
        self.registry = registry

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
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    client_request_id TEXT NOT NULL UNIQUE,
                    client_type TEXT NOT NULL,
                    client_instance_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    workflow_id TEXT,
                    workflow_version TEXT,
                    mode TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    inputs_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    prompt_id TEXT,
                    remote_job_id TEXT,
                    actual_seed INTEGER,
                    error_code TEXT,
                    error_message TEXT,
                    result_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "inputs_json" not in columns:
                connection.execute(
                    "ALTER TABLE jobs ADD COLUMN inputs_json TEXT NOT NULL DEFAULT '[]'"
                )
            if "result_path" not in columns:
                connection.execute("ALTER TABLE jobs ADD COLUMN result_path TEXT")

    @staticmethod
    def _row_to_response(row: sqlite3.Row) -> JobResponse:
        return JobResponse(
            id=row["id"],
            clientRequestId=row["client_request_id"],
            clientType=row["client_type"],
            clientInstanceId=row["client_instance_id"],
            modelId=row["model_id"],
            provider=row["provider"],
            workflowId=row["workflow_id"],
            workflowVersion=row["workflow_version"],
            mode=row["mode"],
            prompt=row["prompt"],
            parameters=json.loads(row["parameters_json"]),
            inputs=json.loads(row["inputs_json"]),
            status=JobStatus(row["status"]),
            progress=row["progress"],
            promptId=row["prompt_id"],
            remoteJobId=row["remote_job_id"],
            actualSeed=row["actual_seed"],
            errorCode=row["error_code"],
            errorMessage=row["error_message"],
            resultPath=row["result_path"],
            createdAt=datetime.fromisoformat(row["created_at"]),
            updatedAt=datetime.fromisoformat(row["updated_at"]),
        )

    def create(self, request: JobCreateRequest) -> JobResponse:
        model = self.registry.get(request.modelId)
        if model is None:
            raise KeyError(request.modelId)
        now = datetime.now(UTC).isoformat()
        job_id = f"job_{uuid.uuid4().hex}"
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO jobs (
                        id, client_request_id, client_type, client_instance_id,
                        model_id, provider, workflow_id, workflow_version,
                        mode, prompt, parameters_json, inputs_json, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        request.clientRequestId,
                        request.client.type,
                        request.client.instanceId,
                        model.id,
                        model.provider,
                        model.workflowId,
                        model.workflowVersion,
                        request.mode,
                        request.prompt,
                        json.dumps(request.parameters, ensure_ascii=False),
                        json.dumps(
                            [item.model_dump() for item in request.inputs],
                            ensure_ascii=False,
                        ),
                        JobStatus.CREATED.value,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise DuplicateClientRequest(request.clientRequestId) from error
        result = self.get(job_id)
        assert result is not None
        return result

    def get(self, job_id: str) -> JobResponse | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return self._row_to_response(row) if row else None

    def list(self, limit: int = 100) -> list[JobResponse]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_response(row) for row in rows]

    def next_with_statuses(self, statuses: set[JobStatus]) -> JobResponse | None:
        if not statuses:
            return None
        values = sorted(status.value for status in statuses)
        placeholders = ",".join("?" for _ in values)
        with self._connection() as connection:
            row = connection.execute(
                f"SELECT * FROM jobs WHERE status IN ({placeholders}) "
                "ORDER BY created_at ASC LIMIT 1",
                values,
            ).fetchone()
        return self._row_to_response(row) if row else None

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: float | None = None,
        prompt_id: str | None = None,
        actual_seed: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        result_path: str | None = None,
    ) -> JobResponse | None:
        values: dict[str, Any] = {"updated_at": datetime.now(UTC).isoformat()}
        if status is not None:
            values["status"] = status.value
        if progress is not None:
            values["progress"] = min(max(progress, 0), 100)
        if prompt_id is not None:
            values["prompt_id"] = prompt_id
        if actual_seed is not None:
            values["actual_seed"] = actual_seed
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
        if result_path is not None:
            values["result_path"] = result_path
        assignments = ", ".join(f"{column} = ?" for column in values)
        with self._connection() as connection:
            cursor = connection.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",
                [*values.values(), job_id],
            )
            if cursor.rowcount == 0:
                return None
        return self.get(job_id)

    def cancel(self, job_id: str) -> JobResponse | None:
        terminal = {
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return None
            if row["status"] not in terminal:
                connection.execute(
                    "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                    (JobStatus.CANCELLED.value, datetime.now(UTC).isoformat(), job_id),
                )
        return self.get(job_id)
