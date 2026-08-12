"""Stable Flynotes AI loader with idle hot-reload and automatic rollback."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import threading
import urllib.request
import uuid

import bpy


bl_info = {
    "name": "Flynotes AI",
    "author": "Flynotes",
    "version": (1, 4, 0),
    "blender": (4, 0, 0),
    "location": "3D 视图 > 侧边栏 > Flynotes AI",
    "description": "Flynotes AI 稳定版本加载器",
    "category": "3D View",
}

_ROOT = Path(__file__).resolve().parent
_POINTER = _ROOT / "current.json"
_INSTANCE_ID = str(uuid.uuid4())
_active_module = None
_active_version = ""
_registered = False
_PUBLIC_SUBMODULES = (
    "api",
    "background",
    "builtin_config",
    "compat",
    "local_video_session",
    "operators",
    "panels",
    "runtime",
    "storage",
    "vse_encoder",
    "workbench_frames",
)


def _read_version() -> str:
    value = json.loads(_POINTER.read_text(encoding="utf-8"))["version"]
    if not isinstance(value, str) or not value:
        raise RuntimeError("Flynotes AI current.json 缺少有效版本")
    return value


def _module_name(version: str) -> str:
    return f"{__package__}.versions.v{version.replace('.', '_')}"


def _load(version: str):
    module_name = _module_name(version)
    importlib.invalidate_caches()
    module = importlib.import_module(module_name)
    for name in sorted(
        (name for name in sys.modules if name.startswith(module_name + ".")),
        key=lambda value: value.count("."),
        reverse=True,
    ):
        importlib.reload(sys.modules[name])
    return importlib.reload(module)


def _expose(module) -> None:
    """Expose active version modules through the stable add-on package.

    Blender integrations and release tests historically import
    ``flynotes_ai.operators`` directly. Without these aliases Python can load
    stale pre-loader files left in an existing installation after an update.
    """
    globals()["bl_info"] = module.bl_info
    for name in _PUBLIC_SUBMODULES:
        active_name = f"{module.__name__}.{name}"
        submodule = sys.modules.get(active_name)
        if submodule is not None:
            globals()[name] = submodule
            sys.modules[f"{__package__}.{name}"] = submodule


def _busy() -> tuple[bool, str]:
    if _active_module:
        runtime = getattr(_active_module, "runtime", None)
        if runtime:
            active = [job for job in runtime.session_jobs if job.get("status") in {"queued", "running"}]
            if active:
                return True, active[0].get("jobId", "")
            session = runtime.local_video_session
            if session and session.is_active:
                return True, "workbench"
    for name in ("RENDER", "COMPOSITE", "OBJECT_BAKE"):
        try:
            if bpy.app.is_job_running(name):
                return True, name.lower()
        except (TypeError, ValueError):
            continue
    return False, ""


def _heartbeat(state: str, active_job_id: str) -> None:
    payload = json.dumps(
        {
            "instanceId": _INSTANCE_ID,
            "blenderVersion": bpy.app.version_string,
            "pluginVersion": _active_version,
            "state": state,
            "activeJobId": active_job_id,
        }
    ).encode("utf-8")

    def send():
        request = urllib.request.Request(
            "http://127.0.0.1:17980/api/v1/blender/plugins/heartbeat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(request, timeout=2).close()
        except Exception:
            pass

    threading.Thread(target=send, name="Flynotes-Heartbeat", daemon=True).start()


def _write_pointer(version: str) -> None:
    temporary = _POINTER.with_suffix(".tmp")
    temporary.write_text(json.dumps({"version": version}, indent=2), encoding="utf-8")
    os.replace(temporary, _POINTER)


def _watch_updates():
    global _active_module, _active_version
    busy, active_job = _busy()
    _heartbeat("busy" if busy else "idle", active_job)
    try:
        requested = _read_version()
    except Exception as error:
        print(f"Flynotes loader: {error}")
        return 2.0
    if requested == _active_version or busy:
        return 2.0
    previous_version, previous_module = _active_version, _active_module
    try:
        if previous_module:
            previous_module.unregister()
        candidate = _load(requested)
        candidate.register()
        _expose(candidate)
        _active_module, _active_version = candidate, requested
        print(f"Flynotes AI hot updated to {requested}")
    except Exception as error:
        print(f"Flynotes AI update {requested} failed, rolling back: {error}")
        try:
            _write_pointer(previous_version)
            restored = _load(previous_version)
            restored.register()
            _expose(restored)
            _active_module, _active_version = restored, previous_version
        except Exception as rollback_error:
            print(f"Flynotes AI rollback failed: {rollback_error}")
    return 2.0


def register():
    global _active_module, _active_version, _registered
    if _registered:
        return
    version = _read_version()
    module = _load(version)
    module.register()
    _expose(module)
    _active_module, _active_version, _registered = module, version, True
    if not bpy.app.timers.is_registered(_watch_updates):
        bpy.app.timers.register(_watch_updates, first_interval=2.0, persistent=True)


def unregister():
    global _active_module, _registered
    if bpy.app.timers.is_registered(_watch_updates):
        bpy.app.timers.unregister(_watch_updates)
    if _active_module:
        _active_module.unregister()
    _active_module = None
    _registered = False
