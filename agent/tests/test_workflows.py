from __future__ import annotations

import json
from pathlib import Path

import pytest

from flynotes_agent.schemas import WorkflowState
from flynotes_agent.workflows import WorkflowManager, WorkflowManifest


class FakeComfyClient:
    def __init__(self, node_names: list[str]) -> None:
        self.node_names = node_names

    async def object_info(self):
        return {name: {} for name in self.node_names}


def _package(root: Path, manifest: dict) -> Path:
    package = root / manifest["id"] / manifest["version"]
    package.mkdir(parents=True)
    (package / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    for filename in manifest["modes"].values():
        (package / filename).write_text("{}", encoding="utf-8")
    return package


def test_manifest_rejects_unsafe_workflow_path() -> None:
    with pytest.raises(ValueError):
        WorkflowManifest.model_validate(
            {
                "id": "unsafe",
                "version": "1",
                "modes": {"text": "../workflow.json"},
            }
        )


def test_manifest_rejects_unsafe_id() -> None:
    with pytest.raises(ValueError):
        WorkflowManifest.model_validate(
            {
                "id": "../unsafe",
                "version": "1",
                "modes": {"text": "workflow.json"},
            }
        )


@pytest.mark.asyncio
async def test_manager_reports_ready_when_resources_and_nodes_exist(
    config, tmp_path: Path, monkeypatch
) -> None:
    builtin = tmp_path / "packages"
    _package(
        builtin,
        {
            "id": "test-workflow",
            "version": "1.0.0",
            "displayName": "测试工作流",
            "modes": {"text": "text.json"},
            "requiredModels": ["tiny.safetensors"],
            "requiredNodes": ["TestNode"],
            "hardware": {
                "minimumVramGB": 8,
                "minimumRamGB": 16,
                "minimumDriver": "580.00",
            },
        },
    )
    (config.comfy_root / "models").mkdir()
    (config.comfy_root / "models" / "tiny.safetensors").write_bytes(b"model")
    monkeypatch.setattr(
        "flynotes_agent.workflows.WorkflowManager._hardware_check",
        staticmethod(lambda _requirements: (True, [], [])),
    )
    manager = WorkflowManager(
        config,
        builtin_root=builtin,
        comfy_client=FakeComfyClient(["TestNode"]),
    )

    result = await manager.inspect()

    assert len(result) == 1
    assert result[0].state == WorkflowState.READY
    assert result[0].missingModels == []
    assert result[0].missingNodes == []


@pytest.mark.asyncio
async def test_manager_reports_missing_resources(config, tmp_path: Path, monkeypatch) -> None:
    builtin = tmp_path / "packages"
    _package(
        builtin,
        {
            "id": "test-workflow",
            "version": "1.0.0",
            "modes": {"text": "text.json"},
            "requiredModels": ["missing.safetensors"],
            "requiredNodes": ["MissingNode"],
        },
    )
    monkeypatch.setattr(
        "flynotes_agent.workflows.WorkflowManager._hardware_check",
        staticmethod(lambda _requirements: (True, [], [])),
    )
    manager = WorkflowManager(
        config,
        builtin_root=builtin,
        comfy_client=FakeComfyClient([]),
    )

    result = await manager.inspect()
    plan = await manager.plan("test-workflow")

    assert result[0].state == WorkflowState.NEEDS_REPAIR
    assert result[0].missingModels == ["missing.safetensors"]
    assert result[0].missingNodes == ["MissingNode"]
    assert plan is not None
    assert plan.canInstall is False
    assert plan.errors == ["当前工作流资源尚未配置固定下载来源"]
