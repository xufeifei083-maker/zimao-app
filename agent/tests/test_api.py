from __future__ import annotations

from fastapi.testclient import TestClient
import httpx

from flynotes_agent.api import create_app
from flynotes_agent.registry import ModelRegistry
from flynotes_agent.repository import JobRepository
from flynotes_agent.schemas import RuntimeState, RuntimeStatusResponse


class FakeRuntime:
    def __init__(self, config) -> None:
        self.config = config
        self.state = RuntimeState.STOPPED

    async def status(self) -> RuntimeStatusResponse:
        return RuntimeStatusResponse(
            state=self.state,
            baseUrl=self.config.comfy_base_url,
            root=str(self.config.comfy_root),
            managed=self.state == RuntimeState.READY,
        )

    async def start(self) -> RuntimeStatusResponse:
        self.state = RuntimeState.READY
        return await self.status()

    async def stop(self) -> RuntimeStatusResponse:
        self.state = RuntimeState.STOPPED
        return await self.status()

    async def restart(self) -> RuntimeStatusResponse:
        self.state = RuntimeState.READY
        return await self.status()


def _client(config) -> TestClient:
    registry = ModelRegistry()
    repository = JobRepository(config.database_path, registry)
    app = create_app(
        config=config,
        runtime=FakeRuntime(config),
        registry=registry,
        repository=repository,
        enable_worker=False,
    )
    return TestClient(app)


def test_health_and_models(config) -> None:
    with _client(config) as client:
        health = client.get("/v1/health")
        models = client.get("/v1/models")

    assert health.status_code == 200
    assert health.json()["comfyui"] == "stopped"
    assert models.status_code == 200
    assert models.json()[0]["displayName"] == "MiniMax H3（本地）"


def test_workflow_catalog_and_install_plan(config) -> None:
    with _client(config) as client:
        workflows = client.get("/v1/workflows")
        plan = client.post("/v1/workflows/minimax-h3/plan")

    assert workflows.status_code == 200
    assert workflows.json()[0]["id"] == "minimax-h3"
    assert workflows.json()[0]["hardware"]["minimumVramGB"] == 8
    assert plan.status_code == 200
    assert plan.json()["workflowId"] == "minimax-h3"


def test_windows_tauri_origin_is_allowed(config) -> None:
    origin = "http://tauri.localhost"
    with _client(config) as client:
        response = client.get("/v1/health", headers={"Origin": origin})
        preflight = client.options(
            "/v1/runtime/comfyui/start",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin


def test_runtime_actions(config) -> None:
    with _client(config) as client:
        started = client.post("/v1/runtime/comfyui/start")
        stopped = client.post("/v1/runtime/comfyui/stop")

    assert started.status_code == 200
    assert started.json()["state"] == "ready"
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "stopped"


def test_plugins_and_logs_contract(config) -> None:
    with _client(config) as client:
        plugins = client.get("/v1/plugins")
        logs = client.get("/v1/logs?source=comfyui&tail=20")

    assert plugins.status_code == 200
    assert plugins.json()[0]["name"] == "Flynotes AI Blender 插件"
    assert logs.status_code == 200
    assert logs.json()["source"] == "comfyui"


def test_create_and_list_job(config) -> None:
    payload = {
        "clientRequestId": "api-request-1",
        "client": {
            "type": "blender",
            "version": "1.4.0",
            "instanceId": "blender-1",
        },
        "modelId": "minimax-h3-local",
        "mode": "text",
        "prompt": "测试提示词",
        "parameters": {"width": 480, "height": 832},
        "inputs": [],
    }
    with _client(config) as client:
        created = client.post("/v1/jobs", json=payload)
        jobs = client.get("/v1/jobs")

    assert created.status_code == 201
    assert created.json()["status"] == "created"
    assert jobs.status_code == 200
    assert [job["id"] for job in jobs.json()] == [created.json()["id"]]


def test_rejects_unavailable_cloud_model(config) -> None:
    payload = {
        "clientRequestId": "cloud-request-1",
        "client": {"type": "desktop"},
        "modelId": "seedance-2",
        "mode": "text",
        "prompt": "测试提示词",
    }
    with _client(config) as client:
        response = client.post("/v1/jobs", json=payload)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "MODEL_UNAVAILABLE"


def test_upload_endpoint_stores_file(config) -> None:
    with _client(config) as client:
        response = client.post(
            "/v1/uploads",
            files={"file": ("frame.png", b"png-data", "image/png")},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("upload_")
    assert body["originalName"] == "frame.png"
    assert body["size"] == 8


def test_blender_compatibility_upload_and_job_contract(config) -> None:
    with _client(config) as client:
        uploaded = client.post(
            "/api/v1/blender/uploads",
            files={"file": ("frame.png", b"png-data", "image/png")},
        )
        created = client.post(
            "/api/v1/blender/jobs",
            json={
                "clientRequestId": "blender-compat-1",
                "installationId": "blender-installation",
                "pluginVersion": "1.4.0",
                "mediaType": "video",
                "modelId": "minimax-h3-local",
                "mode": "text",
                "prompt": "cinematic test",
                "parameters": {"width": 480, "height": 832, "seed": 42},
                "inputs": [],
            },
        )
        fetched = client.get(
            f"/api/v1/blender/jobs/{created.json()['jobId']}"
        )

    assert uploaded.status_code == 201
    assert uploaded.json()["uploadId"].startswith("upload_")
    assert created.status_code == 201
    assert created.json()["status"] == "queued"
    assert fetched.status_code == 200
    assert fetched.json()["jobId"] == created.json()["jobId"]


def test_blender_config_and_asset_contract(config) -> None:
    with _client(config) as client:
        manifest = client.get("/api/v1/blender/config/manifest")
        config_response = client.get(
            f"/api/v1/blender/config/{manifest.json()['configVersion']}"
        )
        assets = client.get("/v1/assets")

    assert manifest.status_code == 200
    assert manifest.json()["agentVersion"] == "0.1.0"
    models = config_response.json()["config"]["models"]
    assert models[0]["displayName"] == "MiniMax H3（本地）"
    assert assets.json() == []


def test_blender_cloud_proxy_forwards_to_configured_upstream(config) -> None:
    captured: dict[str, object] = {}

    class JsonStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"proxied":true}'

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(
            method=request.method,
            url=str(request.url),
            authorization=request.headers.get("authorization"),
            body=await request.aread(),
        )
        return httpx.Response(
            201,
            headers={"content-type": "application/json", "x-upstream": "yes"},
            stream=JsonStream(),
        )

    registry = ModelRegistry()
    repository = JobRepository(config.database_path, registry)
    app = create_app(
        config=config,
        runtime=FakeRuntime(config),
        registry=registry,
        repository=repository,
        cloud_transport=httpx.MockTransport(handler),
        enable_worker=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/blender/cloud/blender/jobs?source=addon",
            headers={"Authorization": "Bearer plugin-token"},
            json={"prompt": "test"},
        )

    assert response.status_code == 201
    assert response.json() == {"proxied": True}
    assert response.headers["x-upstream"] == "yes"
    assert captured == {
        "method": "POST",
        "url": "https://flynotes.top/api/v1/blender/jobs?source=addon",
        "authorization": "Bearer plugin-token",
        "body": b'{"prompt":"test"}',
    }
