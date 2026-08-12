from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from .assets import AssetStore
from .comfy import ComfyClient
from .config import AgentConfig
from .h3_compiler import H3Inputs, H3WorkflowCompiler, H3WorkflowError
from .repository import JobRepository
from .runtime import ComfyRuntimeError, ComfyRuntimeManager
from .schemas import JobResponse, JobStatus, RuntimeState
from .uploads import UploadNotFound, UploadStore


class JobWorker:
    PROCESSABLE = {
        JobStatus.CREATED,
        JobStatus.VALIDATING,
        JobStatus.WAITING_RUNTIME,
        JobStatus.STAGING_INPUTS,
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.RECOVERING,
    }

    def __init__(
        self,
        config: AgentConfig,
        repository: JobRepository,
        runtime: ComfyRuntimeManager,
        upload_store: UploadStore,
        *,
        comfy: ComfyClient | None = None,
        compiler: H3WorkflowCompiler | None = None,
        asset_store: AssetStore | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.runtime = runtime
        self.upload_store = upload_store
        self.comfy = comfy or ComfyClient(config.comfy_base_url)
        self.compiler = compiler or H3WorkflowCompiler()
        self.asset_store = asset_store
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    async def run(self) -> None:
        while not self._stop.is_set():
            job = await asyncio.to_thread(
                self.repository.next_with_statuses, self.PROCESSABLE
            )
            if job is None:
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=2)
                except TimeoutError:
                    pass
                continue
            try:
                if job.promptId:
                    await self._monitor(job)
                else:
                    await self._submit(job)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # the worker must survive an individual job
                await self._fail(job.id, "WORKER_ERROR", str(error))

    async def _submit(self, job: JobResponse) -> None:
        await self._update(job.id, status=JobStatus.VALIDATING, progress=0)
        runtime_status = await self.runtime.status()
        if runtime_status.state not in {RuntimeState.READY, RuntimeState.WARNING}:
            if (
                runtime_status.state == RuntimeState.STOPPED
                and self.config.auto_start_comfy_on_job
            ):
                await self._update(job.id, status=JobStatus.WAITING_RUNTIME)
                try:
                    runtime_status = await self.runtime.start()
                except ComfyRuntimeError as error:
                    await self._fail(job.id, error.code, str(error))
                    return
            if runtime_status.state not in {RuntimeState.READY, RuntimeState.WARNING}:
                await self._fail(
                    job.id,
                    "COMFYUI_UNAVAILABLE",
                    runtime_status.message or "ComfyUI 未就绪",
                )
                return

        await self._update(job.id, status=JobStatus.STAGING_INPUTS, progress=0)
        try:
            material = await asyncio.to_thread(self._stage_inputs, job)
            compiled = self.compiler.compile(
                mode=job.mode,
                prompt=job.prompt,
                parameters=job.parameters,
                inputs=material,
                filename_prefix=f"video/Flynotes/{job.id}",
            )
        except (UploadNotFound, H3WorkflowError, ValueError) as error:
            await self._fail(job.id, "INVALID_INPUT", str(error))
            return

        await asyncio.to_thread(
            self._save_compiled_workflow,
            job.id,
            compiled.workflow,
        )
        try:
            prompt_id = await self.comfy.submit_prompt(
                compiled.workflow, client_id=f"flynotes-agent:{job.id}"
            )
        except (httpx.HTTPError, ValueError) as error:
            await self._fail(job.id, "COMFYUI_SUBMIT_FAILED", self._error_text(error))
            return

        queued = await self._update(
            job.id,
            status=JobStatus.QUEUED,
            prompt_id=prompt_id,
            actual_seed=compiled.actual_seed,
            progress=0,
        )
        if queued:
            await self._monitor(queued)

    def _stage_inputs(self, job: JobResponse) -> H3Inputs:
        staged: defaultdict[str, list[str]] = defaultdict(list)
        allowed = {
            "first_frame",
            "last_frame",
            "reference_image",
            "reference_video",
            "reference_audio",
        }
        for item in job.inputs:
            if item.role not in allowed:
                raise H3WorkflowError(f"不支持的素材角色：{item.role}")
            index = len(staged[item.role])
            name = self.upload_store.stage_for_comfy(
                upload_id=item.uploadId,
                comfy_input_root=self.config.comfy_root / "input",
                job_id=job.id,
                role=item.role,
                index=index,
            )
            staged[item.role].append(name)
        if len(staged["first_frame"]) > 1 or len(staged["last_frame"]) > 1:
            raise H3WorkflowError("首帧和尾帧各最多一个")
        return H3Inputs(
            first_frame=staged["first_frame"][0] if staged["first_frame"] else None,
            last_frame=staged["last_frame"][0] if staged["last_frame"] else None,
            reference_images=staged["reference_image"],
            reference_videos=staged["reference_video"],
            reference_audios=staged["reference_audio"],
        )

    def _save_compiled_workflow(
        self, job_id: str, workflow: dict[str, Any]
    ) -> None:
        directory = self.config.staging_path / "jobs" / job_id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "compiled-workflow.json").write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def _monitor(self, job: JobResponse) -> None:
        assert job.promptId
        missing_count = 0
        while not self._stop.is_set():
            current = await asyncio.to_thread(self.repository.get, job.id)
            if current is None:
                return
            if current.status == JobStatus.CANCELLED:
                try:
                    await self.comfy.cancel(job.promptId, interrupt=True)
                except httpx.HTTPError:
                    pass
                return
            try:
                history = await self.comfy.history(job.promptId)
                if history:
                    error_message = self._history_error(history)
                    if error_message:
                        await self._fail(job.id, "COMFYUI_EXECUTION_ERROR", error_message)
                        return
                    if self._history_completed(history):
                        result_path = self._find_result_path(history)
                        if result_path is None:
                            await self._fail(
                                job.id,
                                "OUTPUT_NOT_FOUND",
                                "ComfyUI 已完成，但未找到输出视频",
                            )
                        else:
                            finished = await self._update(
                                job.id,
                                status=JobStatus.SUCCEEDED,
                                progress=100,
                                result_path=str(result_path),
                            )
                            if finished and self.asset_store:
                                try:
                                    await asyncio.to_thread(
                                        self.asset_store.register, finished, result_path
                                    )
                                except Exception as error:
                                    await self._fail(
                                        job.id,
                                        "ASSET_REGISTER_FAILED",
                                        f"视频已生成，但素材登记失败：{error}",
                                    )
                        return

                queue = await self.comfy.queue()
                serialized = json.dumps(queue, ensure_ascii=False)
                if job.promptId in serialized:
                    missing_count = 0
                    running = job.promptId in json.dumps(
                        queue.get("queue_running", []), ensure_ascii=False
                    )
                    await self._update(
                        job.id,
                        status=JobStatus.RUNNING if running else JobStatus.QUEUED,
                        progress=1 if running else 0,
                    )
                else:
                    missing_count += 1
                    if missing_count >= 10:
                        await self._fail(
                            job.id,
                            "COMFYUI_JOB_LOST",
                            "ComfyUI 队列和历史记录中均未找到任务",
                        )
                        return
            except (httpx.HTTPError, ValueError) as error:
                await self._update(job.id, status=JobStatus.RECOVERING)
                if missing_count >= 20:
                    await self._fail(job.id, "COMFYUI_DISCONNECTED", self._error_text(error))
                    return
                missing_count += 1
            await asyncio.sleep(1.5)

    @staticmethod
    def _history_completed(history: dict[str, Any]) -> bool:
        status = history.get("status", {})
        if isinstance(status, dict) and status.get("completed") is True:
            return True
        return bool(history.get("outputs"))

    @staticmethod
    def _history_error(history: dict[str, Any]) -> str | None:
        status = history.get("status", {})
        if isinstance(status, dict) and status.get("status_str") in {"error", "failed"}:
            messages = status.get("messages", [])
            return json.dumps(messages, ensure_ascii=False)[-2000:]
        return None

    def _find_result_path(self, history: dict[str, Any]) -> Path | None:
        def candidates(value: Any) -> list[dict[str, Any]]:
            if isinstance(value, dict):
                found = [value] if isinstance(value.get("filename"), str) else []
                for nested in value.values():
                    found.extend(candidates(nested))
                return found
            if isinstance(value, list):
                found: list[dict[str, Any]] = []
                for nested in value:
                    found.extend(candidates(nested))
                return found
            return []

        for item in candidates(history.get("outputs", {})):
            filename = Path(item["filename"]).name
            if not filename.lower().endswith((".mp4", ".webm", ".mov", ".mkv")):
                continue
            kind = item.get("type", "output")
            bases = (
                [self.config.comfy_root / "temp"]
                if kind == "temp"
                else [self.config.generated_path, self.config.comfy_root / "output"]
            )
            for base in bases:
                subfolder = Path(str(item.get("subfolder", "")))
                candidate = (base / subfolder / filename).resolve()
                try:
                    candidate.relative_to(base.resolve())
                except ValueError:
                    continue
                if candidate.is_file():
                    return candidate
        return None

    async def _update(self, job_id: str, **values: Any) -> JobResponse | None:
        return await asyncio.to_thread(self.repository.update, job_id, **values)

    async def _fail(self, job_id: str, code: str, message: str) -> None:
        await self._update(
            job_id,
            status=JobStatus.FAILED,
            error_code=code,
            error_message=message[:2000],
        )

    @staticmethod
    def _error_text(error: Exception) -> str:
        if isinstance(error, httpx.HTTPStatusError):
            return f"{error}：{error.response.text[:1500]}"
        return str(error)[:2000]
