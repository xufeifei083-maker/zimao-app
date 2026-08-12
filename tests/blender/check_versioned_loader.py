"""Load, unregister and reload a packaged version through the stable loader."""

from __future__ import annotations

from pathlib import Path
import sys

import bpy


root = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
sys.path.insert(0, str(root))
bpy.ops.preferences.addon_enable(module="flynotes_ai")
import flynotes_ai

assert flynotes_ai._active_version == "1.4.0"
assert flynotes_ai._active_module.bl_info["version"] == (1, 4, 0)
bpy.ops.preferences.addon_disable(module="flynotes_ai")
bpy.ops.preferences.addon_enable(module="flynotes_ai")
assert flynotes_ai._active_version == "1.4.0"
print("FLYNOTES_VERSIONED_LOADER_PASS", flynotes_ai._active_version, flush=True)
bpy.ops.preferences.addon_disable(module="flynotes_ai")
