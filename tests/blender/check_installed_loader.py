"""Verify Blender loads the deployed add-on through its stable loader."""

from __future__ import annotations

from pathlib import Path

import bpy


bpy.ops.preferences.addon_enable(module="flynotes_ai")
import flynotes_ai
from flynotes_ai import operators

assert flynotes_ai._active_version == "1.4.0"
assert flynotes_ai._active_module.bl_info["version"] == (1, 4, 0)
assert Path(flynotes_ai.__file__).name == "__init__.py"
preference = bpy.context.preferences.addons["flynotes_ai"].preferences
expected_cloud_route = (
    f"{operators.local_agent_base(preference)}/blender/cloud"
)
actual_cloud_route = operators.api_base(preference)
print(
    "FLYNOTES_CLOUD_PROXY_ROUTE",
    preference.local_agent_api,
    actual_cloud_route,
    flush=True,
)
assert actual_cloud_route == expected_cloud_route
assert actual_cloud_route.endswith("/api/v1/blender/cloud")
print(
    "FLYNOTES_INSTALLED_LOADER_PASS",
    flynotes_ai._active_version,
    Path(flynotes_ai.__file__).resolve(),
    flush=True,
)
bpy.ops.preferences.addon_disable(module="flynotes_ai")
