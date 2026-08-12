from __future__ import annotations

from flynotes_agent.plugins import PluginManager, PluginUpdateError
from flynotes_agent.schemas import BlenderHeartbeatRequest


def test_plugin_status_is_explicit_when_repository_is_unconfigured(config, monkeypatch) -> None:
    monkeypatch.setattr(PluginManager, "_installations", staticmethod(lambda: []))
    manager = PluginManager(config)
    manager.initialize()

    status = manager.statuses()[0]

    assert status.configured is False
    assert status.state == "not-installed"
    assert status.blenderVersion == "5.0"


def test_busy_blender_blocks_plugin_apply(config, monkeypatch) -> None:
    monkeypatch.setattr(PluginManager, "_installations", staticmethod(lambda: []))
    manager = PluginManager(config)
    manager.initialize()
    manager.heartbeat(
        BlenderHeartbeatRequest(
            instanceId="blender-test",
            blenderVersion="5.0.0",
            pluginVersion="1.4.0",
            state="busy",
            activeJobId="job-test",
        )
    )

    try:
        manager.apply("flynotes-ai-blender:5.0")
    except PluginUpdateError as error:
        assert error.code == "PLUGIN_BUSY"
    else:
        raise AssertionError("busy Blender instance must block a hot update")
