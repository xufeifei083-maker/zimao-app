from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask

from . import __version__
from .assets import AssetStore
from .blender_config import CONFIG_VERSION, build_blender_config, config_sha256
from .config import AgentConfig
from .registry import ModelRegistry
from .plugins import PluginManager, PluginUpdateError
from .repository import DuplicateClientRequest, JobRepository
from .runtime import ComfyRuntimeError, ComfyRuntimeManager
from .system_metrics import read_system_metrics
from .schemas import (
    HealthResponse,
    JobCreateRequest,
    JobResponse,
    ModelSpec,
    RuntimeStatusResponse,
    SystemMetricsResponse,
    AssetResponse,
    BlenderHeartbeatRequest,
    PluginStageRequest,
    PluginStatusResponse,
    UploadResponse,
    WorkflowInstallOperationResponse,
    WorkflowInstallPlanResponse,
    WorkflowStatusResponse,
    WorkflowCatalogStatusResponse,
    RuntimePackageStatusResponse,
)
from .uploads import UploadStore
from .worker import JobWorker
from .workflows import WorkflowManager
from .installer import WorkflowInstaller, WorkflowInstallError
from .catalog import CatalogError, WorkflowCatalogManager
from .runtime_package import RuntimePackageManager


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def create_app(
    config: AgentConfig | None = None,
    runtime: ComfyRuntimeManager | None = None,
    registry: ModelRegistry | None = None,
    repository: JobRepository | None = None,
    upload_store: UploadStore | None = None,
    worker: JobWorker | None = None,
    asset_store: AssetStore | None = None,
    plugin_manager: PluginManager | None = None,
    cloud_transport: httpx.AsyncBaseTransport | None = None,
    workflow_manager: WorkflowManager | None = None,
    workflow_installer: WorkflowInstaller | None = None,
    workflow_catalog_manager: WorkflowCatalogManager | None = None,
    runtime_package_manager: RuntimePackageManager | None = None,
    enable_worker: bool = True,
) -> FastAPI:
    resolved_config = config or AgentConfig.from_env()
    resolved_registry = registry or ModelRegistry()
    resolved_runtime = runtime or ComfyRuntimeManager(resolved_config)
    resolved_repository = repository or JobRepository(
        resolved_config.database_path, resolved_registry
    )
    resolved_upload_store = upload_store or UploadStore(resolved_config.staging_path)
    resolved_asset_store = asset_store or AssetStore(resolved_config)
    resolved_plugin_manager = plugin_manager or PluginManager(resolved_config)
    resolved_workflow_manager = workflow_manager or WorkflowManager(resolved_config)
    resolved_runtime_package_manager = runtime_package_manager or RuntimePackageManager(
        resolved_config
    )
    resolved_workflow_installer = workflow_installer or WorkflowInstaller(
        resolved_workflow_manager,
        resolved_runtime,
        runtime_package_manager=resolved_runtime_package_manager,
    )
    resolved_workflow_catalog_manager = workflow_catalog_manager or WorkflowCatalogManager(
        resolved_config
    )
    resolved_worker = worker or JobWorker(
        resolved_config,
        resolved_repository,
        resolved_runtime,
        resolved_upload_store,
        asset_store=resolved_asset_store,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        resolved_config.ensure_directories()
        resolved_repository.initialize()
        resolved_upload_store.initialize()
        resolved_asset_store.initialize()
        resolved_plugin_manager.initialize()
        resolved_workflow_manager.initialize()
        resolved_workflow_installer.initialize()
        worker_task = (
            asyncio.create_task(resolved_worker.run(), name="flynotes-job-worker")
            if enable_worker
            else None
        )
        try:
            yield
        finally:
            await resolved_workflow_installer.shutdown()
            if worker_task:
                resolved_worker.stop()
                worker_task.cancel()
                with suppress(asyncio.CancelledError):
                    await worker_task

    app = FastAPI(
        title="Flynotes Local Agent",
        version=__version__,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:1420",
            "http://127.0.0.1:1420",
            "tauri://localhost",
            # Tauri's custom protocol uses an HTTP origin on Windows/Linux.
            # Without this entry, the native WebView can reach the TCP port
            # but the browser blocks every API response as a CORS violation.
            "http://tauri.localhost",
            "https://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    app.state.config = resolved_config
    app.state.runtime = resolved_runtime
    app.state.registry = resolved_registry
    app.state.repository = resolved_repository
    app.state.upload_store = resolved_upload_store
    app.state.worker = resolved_worker
    app.state.asset_store = resolved_asset_store
    app.state.plugin_manager = resolved_plugin_manager
    app.state.workflow_manager = resolved_workflow_manager
    app.state.workflow_installer = resolved_workflow_installer
    app.state.workflow_catalog_manager = resolved_workflow_catalog_manager
    app.state.runtime_package_manager = resolved_runtime_package_manager

    @app.get("/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        runtime_status = await resolved_runtime.status()
        return HealthResponse(version=__version__, comfyui=runtime_status.state)

    @app.get("/v1/models", response_model=list[ModelSpec])
    async def models() -> list[ModelSpec]:
        return resolved_registry.list()

    @app.get("/v1/runtime/package", response_model=RuntimePackageStatusResponse)
    async def runtime_package() -> RuntimePackageStatusResponse:
        return resolved_runtime_package_manager.status()

    @app.get("/v1/catalog", response_model=WorkflowCatalogStatusResponse)
    async def workflow_catalog() -> WorkflowCatalogStatusResponse:
        return resolved_workflow_catalog_manager.status()

    @app.post("/v1/catalog/refresh", response_model=WorkflowCatalogStatusResponse)
    async def workflow_catalog_refresh() -> WorkflowCatalogStatusResponse:
        try:
            result = await resolved_workflow_catalog_manager.refresh()
            resolved_workflow_manager.invalidate_resource_cache()
            return result
        except CatalogError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": error.code, "message": str(error)},
            ) from error

    @app.get("/v1/workflows", response_model=list[WorkflowStatusResponse])
    async def workflows() -> list[WorkflowStatusResponse]:
        return await resolved_workflow_manager.inspect(verify_nodes=True)

    @app.get(
        "/v1/workflows/{workflow_id}", response_model=WorkflowStatusResponse
    )
    async def workflow(workflow_id: str) -> WorkflowStatusResponse:
        items = await resolved_workflow_manager.inspect(verify_nodes=True)
        result = next((item for item in items if item.id == workflow_id), None)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return result

    @app.post(
        "/v1/workflows/{workflow_id}/plan",
        response_model=WorkflowInstallPlanResponse,
    )
    async def workflow_plan(workflow_id: str) -> WorkflowInstallPlanResponse:
        result = await resolved_workflow_manager.plan(workflow_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return result

    @app.post(
        "/v1/workflows/{workflow_id}/verify",
        response_model=WorkflowStatusResponse,
    )
    async def workflow_verify(workflow_id: str) -> WorkflowStatusResponse:
        items = await resolved_workflow_manager.inspect(verify_nodes=True)
        result = next((item for item in items if item.id == workflow_id), None)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return result

    @app.post(
        "/v1/workflows/{workflow_id}/install",
        response_model=WorkflowInstallOperationResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def workflow_install(workflow_id: str) -> WorkflowInstallOperationResponse:
        try:
            return await resolved_workflow_installer.start(workflow_id)
        except WorkflowInstallError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": error.code, "message": str(error)},
            ) from error

    @app.get(
        "/v1/downloads", response_model=list[WorkflowInstallOperationResponse]
    )
    async def workflow_downloads() -> list[WorkflowInstallOperationResponse]:
        return resolved_workflow_installer.list()

    @app.get(
        "/v1/downloads/{operation_id}",
        response_model=WorkflowInstallOperationResponse,
    )
    async def workflow_download(operation_id: str) -> WorkflowInstallOperationResponse:
        result = resolved_workflow_installer.get(operation_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return result

    def _download_action(
        operation_id: str, action: str
    ) -> WorkflowInstallOperationResponse:
        method = getattr(resolved_workflow_installer, action)
        result = method(operation_id)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return result

    @app.post(
        "/v1/downloads/{operation_id}/pause",
        response_model=WorkflowInstallOperationResponse,
    )
    async def workflow_download_pause(
        operation_id: str,
    ) -> WorkflowInstallOperationResponse:
        return _download_action(operation_id, "pause")

    @app.post(
        "/v1/downloads/{operation_id}/resume",
        response_model=WorkflowInstallOperationResponse,
    )
    async def workflow_download_resume(
        operation_id: str,
    ) -> WorkflowInstallOperationResponse:
        return _download_action(operation_id, "resume")

    @app.post(
        "/v1/downloads/{operation_id}/retry",
        response_model=WorkflowInstallOperationResponse,
    )
    async def workflow_download_retry(
        operation_id: str,
    ) -> WorkflowInstallOperationResponse:
        return _download_action(operation_id, "resume")

    @app.delete(
        "/v1/downloads/{operation_id}",
        response_model=WorkflowInstallOperationResponse,
    )
    async def workflow_download_cancel(
        operation_id: str,
    ) -> WorkflowInstallOperationResponse:
        return _download_action(operation_id, "cancel")

    @app.get("/v1/runtime/comfyui", response_model=RuntimeStatusResponse)
    async def comfy_status() -> RuntimeStatusResponse:
        return await resolved_runtime.status()

    @app.get("/v1/system/metrics", response_model=SystemMetricsResponse)
    async def system_metrics() -> SystemMetricsResponse:
        return await asyncio.to_thread(read_system_metrics)

    async def _runtime_action(action: str) -> RuntimeStatusResponse:
        try:
            method = getattr(resolved_runtime, action)
            return await method()
        except ComfyRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": error.code, "message": str(error)},
            ) from error

    @app.post("/v1/runtime/comfyui/start", response_model=RuntimeStatusResponse)
    async def comfy_start() -> RuntimeStatusResponse:
        return await _runtime_action("start")

    @app.post("/v1/runtime/comfyui/stop", response_model=RuntimeStatusResponse)
    async def comfy_stop() -> RuntimeStatusResponse:
        return await _runtime_action("stop")

    @app.post("/v1/runtime/comfyui/restart", response_model=RuntimeStatusResponse)
    async def comfy_restart() -> RuntimeStatusResponse:
        return await _runtime_action("restart")

    @app.get("/v1/jobs", response_model=list[JobResponse])
    async def list_jobs(limit: int = 100) -> list[JobResponse]:
        return await asyncio.to_thread(resolved_repository.list, min(max(limit, 1), 500))

    @app.get("/v1/assets", response_model=list[AssetResponse])
    async def list_assets(limit: int = 200) -> list[AssetResponse]:
        return await asyncio.to_thread(
            resolved_asset_store.list, min(max(limit, 1), 500)
        )

    @app.get("/v1/assets/{asset_id}", response_model=AssetResponse)
    async def get_asset(asset_id: str) -> AssetResponse:
        asset = await asyncio.to_thread(resolved_asset_store.get, asset_id)
        if not asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return asset

    @app.get("/v1/assets/{asset_id}/content")
    async def get_asset_content(asset_id: str) -> FileResponse:
        asset = await asyncio.to_thread(resolved_asset_store.get, asset_id)
        if not asset:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        path = Path(asset.path).resolve()
        if not path.is_file() or not _is_within(path, resolved_config.generated_path.resolve()):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(path, media_type="video/mp4", filename=path.name)

    @app.get("/v1/assets/{asset_id}/thumbnail")
    async def get_asset_thumbnail(asset_id: str) -> FileResponse:
        asset = await asyncio.to_thread(resolved_asset_store.get, asset_id)
        if not asset or not asset.thumbnailPath:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        path = Path(asset.thumbnailPath).resolve()
        if not path.is_file() or not _is_within(path, resolved_config.data_root.resolve()):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/v1/logs")
    async def logs(source: str = "comfyui", tail: int = 200) -> dict[str, Any]:
        paths = {
            "comfyui": resolved_config.comfy_log_path,
            "agent": resolved_config.agent_log_path,
            "agent-stdout": resolved_config.agent_log_path.parent / "agent-stdout.log",
            "agent-stderr": resolved_config.agent_log_path.parent / "agent-stderr.log",
        }
        path = paths.get(source)
        if path is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if not path.is_file():
            return {"source": source, "path": str(path), "lines": []}
        lines = await asyncio.to_thread(
            lambda: path.read_text(encoding="utf-8", errors="replace").splitlines()[-min(max(tail, 1), 2000) :]
        )
        return {"source": source, "path": str(path), "lines": lines}

    @app.get("/v1/plugins", response_model=list[PluginStatusResponse])
    async def plugins() -> list[PluginStatusResponse]:
        return await asyncio.to_thread(resolved_plugin_manager.statuses)

    def _plugin_error(error: PluginUpdateError) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "message": str(error)},
        )

    @app.post("/v1/plugins/check-updates", response_model=list[PluginStatusResponse])
    async def plugin_check_updates() -> list[PluginStatusResponse]:
        try:
            return await resolved_plugin_manager.check_updates()
        except (PluginUpdateError, httpx.HTTPError) as error:
            if isinstance(error, PluginUpdateError):
                raise _plugin_error(error) from error
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "GITHUB_REQUEST_FAILED", "message": str(error)},
            ) from error

    @app.post("/v1/plugins/stage-update", response_model=list[PluginStatusResponse])
    async def plugin_stage_update(request: PluginStageRequest) -> list[PluginStatusResponse]:
        try:
            return await resolved_plugin_manager.stage(request.manifest)
        except (PluginUpdateError, httpx.HTTPError) as error:
            if isinstance(error, PluginUpdateError):
                raise _plugin_error(error) from error
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "PLUGIN_DOWNLOAD_FAILED", "message": str(error)},
            ) from error

    @app.post("/v1/plugins/{plugin_id}/apply-update", response_model=list[PluginStatusResponse])
    async def plugin_apply_update(plugin_id: str) -> list[PluginStatusResponse]:
        try:
            return await asyncio.to_thread(resolved_plugin_manager.apply, plugin_id)
        except PluginUpdateError as error:
            raise _plugin_error(error) from error

    @app.post("/v1/plugins/{plugin_id}/rollback", response_model=list[PluginStatusResponse])
    async def plugin_rollback(plugin_id: str) -> list[PluginStatusResponse]:
        try:
            return await asyncio.to_thread(resolved_plugin_manager.rollback, plugin_id)
        except PluginUpdateError as error:
            raise _plugin_error(error) from error

    @app.post("/api/v1/blender/plugins/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
    async def blender_plugin_heartbeat(request: BlenderHeartbeatRequest) -> None:
        resolved_plugin_manager.heartbeat(request)

    @app.api_route(
        "/api/v1/blender/cloud/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
    )
    async def blender_cloud_proxy(path: str, request: Request) -> StreamingResponse:
        """Forward Blender cloud traffic to the configuration-owned upstream."""
        upstream_url = f"{resolved_config.flynotes_base_url}/{path.lstrip('/')}"
        hop_by_hop = {
            "host", "content-length", "connection", "keep-alive",
            "proxy-authenticate", "proxy-authorization", "te", "trailer",
            "transfer-encoding", "upgrade",
        }
        forwarded_headers = {
            key: value for key, value in request.headers.items()
            if key.lower() not in hop_by_hop
        }
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(600.0, connect=30.0),
            transport=cloud_transport,
        )
        upstream_request = client.build_request(
            request.method,
            upstream_url,
            params=request.query_params,
            headers=forwarded_headers,
            content=await request.body(),
        )
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as error:
            await client.aclose()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "FLYNOTES_CLOUD_UNREACHABLE", "message": str(error)},
            ) from error

        response_headers = {
            key: value for key, value in upstream.headers.items()
            if key.lower() not in hop_by_hop
        }

        async def close_upstream() -> None:
            await upstream.aclose()
            await client.aclose()

        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers=response_headers,
            background=BackgroundTask(close_upstream),
        )

    @app.post(
        "/v1/uploads",
        response_model=UploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_upload(file: UploadFile = File(...)) -> UploadResponse:
        try:
            return await asyncio.to_thread(
                resolved_upload_store.save,
                file.file,
                original_name=file.filename or "upload.bin",
                content_type=file.content_type or "application/octet-stream",
            )
        finally:
            await file.close()

    async def _create_job(request: JobCreateRequest) -> JobResponse:
        model = resolved_registry.get(request.modelId)
        if model is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "MODEL_NOT_FOUND", "message": request.modelId},
            )
        if not model.available:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "MODEL_UNAVAILABLE", "message": model.statusMessage},
            )
        if request.mode not in model.modes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "INVALID_PARAMETER", "message": "不支持的生成模式"},
            )
        try:
            created = await asyncio.to_thread(resolved_repository.create, request)
            if enable_worker:
                resolved_worker.wake()
            return created
        except DuplicateClientRequest as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "DUPLICATE_REQUEST", "message": str(error)},
            ) from error

    @app.post(
        "/v1/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_job(request: JobCreateRequest) -> JobResponse:
        return await _create_job(request)

    @app.get("/v1/jobs/{job_id}", response_model=JobResponse)
    async def get_job(job_id: str) -> JobResponse:
        job = await asyncio.to_thread(resolved_repository.get, job_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return job

    @app.post("/v1/jobs/{job_id}/cancel", response_model=JobResponse)
    async def cancel_job(job_id: str) -> JobResponse:
        job = await asyncio.to_thread(resolved_repository.cancel, job_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return job

    def _blender_job(job: JobResponse) -> dict[str, Any]:
        status_map = {
            "created": "queued",
            "validating": "queued",
            "waiting_runtime": "queued",
            "staging_inputs": "queued",
            "queued": "queued",
            "running": "running",
            "recovering": "running",
            "downloading": "running",
            "succeeded": "done",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        return {
            "jobId": job.id,
            "clientRequestId": job.clientRequestId,
            "modelId": job.modelId,
            "mode": job.mode,
            "prompt": job.prompt,
            "status": status_map[job.status.value],
            "metadata": {
                "progressPercent": job.progress,
                "actualSeed": job.actualSeed,
                "workflowVersion": job.workflowVersion,
            },
            "result": {
                "outputCount": 1 if job.resultPath else 0,
                "localPath": job.resultPath,
            },
            "error": (
                {"code": job.errorCode, "message": job.errorMessage}
                if job.errorCode or job.errorMessage
                else None
            ),
            "createdAt": job.createdAt.isoformat(),
            "queuedAt": job.createdAt.isoformat(),
            "updatedAt": job.updatedAt.isoformat(),
        }

    @app.get("/api/v1/blender/config/manifest")
    async def blender_config_manifest() -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "configVersion": CONFIG_VERSION,
            "agentVersion": __version__,
            "notes": "MiniMax H3 本地工作流由 Local Agent 执行",
        }

    @app.get("/api/v1/blender/config/{version}")
    async def blender_config(version: str) -> dict[str, Any]:
        if version != CONFIG_VERSION:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        config = build_blender_config(resolved_registry)
        return {"config": config, "sha256": config_sha256(config)}

    @app.post("/api/v1/blender/uploads", status_code=status.HTTP_201_CREATED)
    async def blender_upload(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            saved = await asyncio.to_thread(
                resolved_upload_store.save,
                file.file,
                original_name=file.filename or "upload.bin",
                content_type=file.content_type or "application/octet-stream",
            )
        finally:
            await file.close()
        return {
            "uploadId": saved.id,
            "originalName": saved.originalName,
            "size": saved.size,
            "sha256": saved.sha256,
        }

    @app.post(
        "/api/v1/blender/jobs",
        status_code=status.HTTP_201_CREATED,
    )
    async def blender_create_job(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            request = JobCreateRequest.model_validate(
                {
                    "clientRequestId": payload.get("clientRequestId"),
                    "client": {
                        "type": "blender",
                        "version": payload.get("pluginVersion", "unknown"),
                        "instanceId": payload.get("installationId", ""),
                    },
                    "modelId": payload.get("modelId"),
                    "mode": payload.get("mode"),
                    "prompt": payload.get("prompt"),
                    "parameters": payload.get("parameters") or {},
                    "inputs": payload.get("inputs") or [],
                }
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "INVALID_REQUEST", "message": str(error)},
            ) from error
        return _blender_job(await _create_job(request))

    @app.get("/api/v1/blender/jobs")
    async def blender_list_jobs(limit: int = 100) -> list[dict[str, Any]]:
        jobs = await asyncio.to_thread(
            resolved_repository.list, min(max(limit, 1), 500)
        )
        return [_blender_job(job) for job in jobs if job.clientType == "blender"]

    @app.get("/api/v1/blender/jobs/{job_id}")
    async def blender_get_job(job_id: str) -> dict[str, Any]:
        job = await asyncio.to_thread(resolved_repository.get, job_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return _blender_job(job)

    @app.get("/api/v1/blender/jobs/{job_id}/outputs/{index}")
    async def blender_job_output(job_id: str, index: int) -> FileResponse:
        job = await asyncio.to_thread(resolved_repository.get, job_id)
        if not job or index != 0 or not job.resultPath:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        result_path = Path(job.resultPath).resolve()
        roots = [
            resolved_config.generated_path.resolve(),
            (resolved_config.comfy_root / "output").resolve(),
        ]
        if not any(
            _is_within(result_path, root)
            for root in roots
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
        if not result_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return FileResponse(result_path, filename=result_path.name)

    @app.websocket("/v1/events")
    async def events(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            while True:
                runtime_status = await resolved_runtime.status()
                await websocket.send_json(
                    {"type": "runtime.status", "data": runtime_status.model_dump()}
                )
                await asyncio.sleep(2)
        except WebSocketDisconnect:
            return

    return app


app = create_app()
