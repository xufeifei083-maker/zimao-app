from __future__ import annotations

from pathlib import Path

import pytest

from flynotes_agent.config import AgentConfig


@pytest.fixture
def config(tmp_path: Path) -> AgentConfig:
    comfy_root = tmp_path / "comfy"
    (comfy_root / "walkingwithai").mkdir(parents=True)
    (comfy_root / "walkingwithai" / "python.exe").write_bytes(b"")
    (comfy_root / "main.py").write_text("# test", encoding="utf-8")
    return AgentConfig(
        comfy_root=comfy_root,
        data_root=tmp_path / "data",
        comfy_start_timeout_seconds=0.1,
    )

