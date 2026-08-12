from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .downloads import DownloadError, DownloadPaused, ResumableDownloader, huggingface_file_url
from .runtime import ComfyRuntimeManager
from .schemas import (
    WorkflowInstallOperationResponse,
    WorkflowInstallState,
    WorkflowState,
)
from .workflows import WorkflowManager, WorkflowModelResource


class WorkflowInstallError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WorkflowInstaller:
    def __init__(
        self,
        manager: WorkflowManager,
        runtime: ComfyRuntimeManager,
        *,
        downloader: ResumableDownloader | None = None,
    ) -> None:
        self.manager = manager
        self.config = manager.config
        self.runtime = runtime
        self.downloader = downloader or ResumableDownloader(timeout=120)
        self._operations: dict[str, WorkflowInstallOperationResponse] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._desired_state: dict[str, WorkflowInstallState] = {}
        self._last_save = 0.0

    def initialize(self) -> None:
        self.config.workflow_install_state_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config.workflow_install_state_path.is_file():
            return
        try:
            rows = json.loads(
                self.config.workflow_install_state_path.read_text(encoding="utf-8")
            )
            for row in rows:
                operation = WorkflowInstallOperationResponse.model_validate(row)
                if operation.state in {
                    WorkflowInstallState.QUEUED,
                    WorkflowInstallState.DOWNLOADING,
                    WorkflowInstallState.VERIFYING,
                }:
                    operation.state = WorkflowInstallState.PAUSED
                    operation.errorCode = "AGENT_RESTARTED"
                    operation.errorMessage = "Local Agent 已重启，请继续下载"
                self._operations[operation.id] = operation
        except (OSError, json.JSONDecodeError, ValueError):
            self._operations = {}
        self._save(force=True)

    async def shutdown(self) -> None:
        for operation_id, task in list(self._tasks.items()):
            if not task.done():
                self._desired_state[operation_id] = WorkflowInstallState.PAUSED
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._save(force=True)

    def _save(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_save < 0.5:
            return
        self._last_save = now
        temporary = self.config.workflow_install_state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                [
                    operation.model_dump(mode="json")
                    for operation in sorted(
                        self._operations.values(), key=lambda item: item.createdAt
                    )
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.config.workflow_install_state_path)

    def list(self) -> list[WorkflowInstallOperationResponse]:
        return sorted(
            self._operations.values(), key=lambda item: item.createdAt, reverse=True
        )

    def get(self, operation_id: str) -> WorkflowInstallOperationResponse | None:
        return self._operations.get(operation_id)

    async def start(self, workflow_id: str) -> WorkflowInstallOperationResponse:
        active = next(
            (
                operation
                for operation in self._operations.values()
                if operation.workflowId == workflow_id
                and operation.state
                in {
                    WorkflowInstallState.QUEUED,
                    WorkflowInstallState.DOWNLOADING,
                    WorkflowInstallState.VERIFYING,
                    WorkflowInstallState.PAUSED,
                }
            ),
            None,
        )
        if active:
            return active
        plan = await self.manager.plan(workflow_id)
        if plan is None:
            raise WorkflowInstallError("WORKFLOW_NOT_FOUND", workflow_id)
        if plan.state == WorkflowState.READY:
            raise WorkflowInstallError("WORKFLOW_ALREADY_READY", "工作流已经可以使用")
        if not plan.canInstall:
            raise WorkflowInstallError(
                "WORKFLOW_NOT_INSTALLABLE", "；".join(plan.errors) or "当前工作流无法安装"
            )
        free = shutil.disk_usage(self.config.data_root).free
        if free < plan.requiredDiskBytes:
            raise WorkflowInstallError(
                "DISK_SPACE_INSUFFICIENT",
                f"磁盘可用空间不足，需要至少 {plan.requiredDiskBytes} 字节",
            )
        now = datetime.now(UTC)
        operation = WorkflowInstallOperationResponse(
            id=f"install_{uuid.uuid4().hex}",
            workflowId=workflow_id,
            workflowVersion=plan.workflowVersion,
            state=WorkflowInstallState.QUEUED,
            totalBytes=plan.downloadBytes,
            createdAt=now,
            updatedAt=now,
        )
        self._operations[operation.id] = operation
        self._desired_state.pop(operation.id, None)
        self._save(force=True)
        self._spawn(operation.id)
        return operation

    def _spawn(self, operation_id: str) -> None:
        task = self._tasks.get(operation_id)
        if task and not task.done():
            return
        self._tasks[operation_id] = asyncio.create_task(
            self._run(operation_id), name=f"workflow-install:{operation_id}"
        )

    def pause(self, operation_id: str) -> WorkflowInstallOperationResponse | None:
        operation = self.get(operation_id)
        if not operation:
            return None
        if operation.state in {
            WorkflowInstallState.QUEUED,
            WorkflowInstallState.DOWNLOADING,
        }:
            self._desired_state[operation_id] = WorkflowInstallState.PAUSED
        return operation

    def cancel(self, operation_id: str) -> WorkflowInstallOperationResponse | None:
        operation = self.get(operation_id)
        if not operation:
            return None
        if operation.state not in {
            WorkflowInstallState.SUCCEEDED,
            WorkflowInstallState.FAILED,
            WorkflowInstallState.CANCELLED,
        }:
            self._desired_state[operation_id] = WorkflowInstallState.CANCELLED
        return operation

    def resume(self, operation_id: str) -> WorkflowInstallOperationResponse | None:
        operation = self.get(operation_id)
        if not operation:
            return None
        if operation.state not in {
            WorkflowInstallState.PAUSED,
            WorkflowInstallState.FAILED,
        }:
            return operation
        operation.state = WorkflowInstallState.QUEUED
        operation.errorCode = ""
        operation.errorMessage = ""
        operation.updatedAt = datetime.now(UTC)
        self._desired_state.pop(operation_id, None)
        self._save(force=True)
        self._spawn(operation_id)
        return operation

    @staticmethod
    def _safe_model_target(root: Path, install_to: str) -> Path:
        target = (root / install_to).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError as error:
            raise WorkflowInstallError("UNSAFE_INSTALL_PATH", install_to) from error
        return target

    def _resource_progress(
        self,
        operation: WorkflowInstallOperationResponse,
        completed: int,
        current: int,
    ) -> None:
        operation.downloadedBytes = min(completed + current, operation.totalBytes)
        operation.progressPercent = (
            operation.downloadedBytes / operation.totalBytes * 100
            if operation.totalBytes
            else 0
        )
        operation.updatedAt = datetime.now(UTC)
        self._save()

    async def _missing_models(self, operation: WorkflowInstallOperationResponse) -> list[WorkflowModelResource]:
        package = self.manager.get(operation.workflowId)
        if package is None:
            raise WorkflowInstallError("WORKFLOW_NOT_FOUND", operation.workflowId)
        statuses = await self.manager.inspect(verify_nodes=False)
        status = next(item for item in statuses if item.id == operation.workflowId)
        missing = set(status.missingModels)
        return [
            model
            for model in package.manifest.model_resources
            if model.expected_filename in missing
        ]

    async def _run(self, operation_id: str) -> None:
        operation = self._operations[operation_id]
        try:
            models = await self._missing_models(operation)
            completed = max(
                operation.totalBytes - sum(model.size or 0 for model in models), 0
            )
            operation.state = WorkflowInstallState.DOWNLOADING
            operation.updatedAt = datetime.now(UTC)
            self._save(force=True)
            for model in models:
                desired = self._desired_state.get(operation_id)
                if desired:
                    raise DownloadPaused()
                operation.currentResourceId = model.id
                operation.currentFilename = model.expected_filename
                target = self._safe_model_target(
                    self.config.models_path, model.installTo
                )
                url = huggingface_file_url(model.repo, model.revision, model.file)
                await self.downloader.download(
                    url,
                    target,
                    expected_size=model.size,
                    expected_sha256=model.sha256,
                    progress=lambda current, _total, done=completed: self._resource_progress(
                        operation, done, current
                    ),
                    should_pause=lambda: operation_id in self._desired_state,
                )
                completed += model.size or target.stat().st_size
                self._resource_progress(operation, completed, 0)
            operation.state = WorkflowInstallState.VERIFYING
            operation.currentResourceId = ""
            operation.currentFilename = ""
            operation.updatedAt = datetime.now(UTC)
            self._save(force=True)
            self.manager.invalidate_resource_cache()
            await self.runtime.start()
            rows = await self.manager.inspect(verify_nodes=True)
            status = next(item for item in rows if item.id == operation.workflowId)
            if status.state != WorkflowState.READY:
                raise WorkflowInstallError(
                    "WORKFLOW_VERIFICATION_FAILED", status.statusMessage
                )
            operation.state = WorkflowInstallState.SUCCEEDED
            operation.downloadedBytes = operation.totalBytes
            operation.progressPercent = 100
            operation.errorCode = ""
            operation.errorMessage = ""
        except DownloadPaused:
            desired = self._desired_state.pop(operation_id, WorkflowInstallState.PAUSED)
            operation.state = desired
            operation.errorCode = ""
            operation.errorMessage = ""
        except (DownloadError, WorkflowInstallError) as error:
            operation.state = WorkflowInstallState.FAILED
            operation.errorCode = error.code
            operation.errorMessage = str(error)
        except Exception as error:
            operation.state = WorkflowInstallState.FAILED
            operation.errorCode = "WORKFLOW_INSTALL_FAILED"
            operation.errorMessage = str(error)
        finally:
            operation.updatedAt = datetime.now(UTC)
            self._save(force=True)
