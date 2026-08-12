from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from flynotes_agent.downloads import ResumableDownloader
from flynotes_agent.installer import WorkflowInstaller
from flynotes_agent.schemas import WorkflowInstallState
from flynotes_agent.workflows import WorkflowManager


class FakeComfyClient:
    async def object_info(self):
        return {"TestNode": {}}


class FakeRuntime:
    def __init__(self) -> None:
        self.started = False

    async def start(self):
        self.started = True


def _write_package(root: Path, payload: bytes) -> None:
    package = root / "tiny" / "1.0.0"
    package.mkdir(parents=True)
    manifest = {
        "id": "tiny",
        "version": "1.0.0",
        "displayName": "Tiny test workflow",
        "modes": {"text": "text.json"},
        "models": [
            {
                "id": "tiny-model",
                "source": "huggingface",
                "repo": "Zimao/tiny",
                "revision": "a" * 40,
                "file": "models/tiny.bin",
                "installTo": "checkpoints/tiny.bin",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
        "requiredNodes": ["TestNode"],
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (package / "text.json").write_text("{}", encoding="utf-8")


@pytest.mark.asyncio
async def test_installer_downloads_verifies_and_persists(config, tmp_path: Path, monkeypatch) -> None:
    payload = b"verified model payload"
    packages = tmp_path / "packages"
    _write_package(packages, payload)
    config.ensure_directories()
    monkeypatch.setattr(
        "flynotes_agent.workflows.WorkflowManager._hardware_check",
        staticmethod(lambda _requirements: (True, [], [])),
    )

    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=payload))
    manager = WorkflowManager(config, builtin_root=packages, comfy_client=FakeComfyClient())
    runtime = FakeRuntime()
    installer = WorkflowInstaller(
        manager,
        runtime,  # type: ignore[arg-type]
        downloader=ResumableDownloader(transport=transport, chunk_size=4),
    )

    operation = await installer.start("tiny")
    for _ in range(100):
        await asyncio.sleep(0.01)
        operation = installer.get(operation.id)
        if operation and operation.state in {
            WorkflowInstallState.SUCCEEDED,
            WorkflowInstallState.FAILED,
        }:
            break

    assert operation is not None
    assert operation.state == WorkflowInstallState.SUCCEEDED
    assert operation.progressPercent == 100
    assert runtime.started is True
    assert (config.models_path / "checkpoints" / "tiny.bin").read_bytes() == payload
    assert config.workflow_install_state_path.is_file()


def test_initialize_turns_interrupted_operation_into_paused(config) -> None:
    config.ensure_directories()
    now = datetime.now(UTC).isoformat()
    config.workflow_install_state_path.write_text(
        json.dumps(
            [
                {
                    "id": "install_interrupted",
                    "workflowId": "tiny",
                    "workflowVersion": "1.0.0",
                    "state": "downloading",
                    "createdAt": now,
                    "updatedAt": now,
                }
            ]
        ),
        encoding="utf-8",
    )
    manager = WorkflowManager(config, comfy_client=FakeComfyClient())
    installer = WorkflowInstaller(manager, FakeRuntime())  # type: ignore[arg-type]

    installer.initialize()

    operation = installer.get("install_interrupted")
    assert operation is not None
    assert operation.state == WorkflowInstallState.PAUSED
    assert operation.errorCode == "AGENT_RESTARTED"
