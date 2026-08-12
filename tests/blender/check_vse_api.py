"""Validate the exact Blender 5 VSE call used by the add-on."""

from pathlib import Path
import sys

import bpy


arguments = sys.argv[sys.argv.index("--") + 1 :]
video = Path(arguments[0]).resolve()
repo = Path(arguments[1]).resolve()
sys.path.insert(0, str(repo / "blender_addon"))
bpy.ops.preferences.addon_enable(module="flynotes_ai")

from flynotes_ai.compat import ensure_sequence_collection, sequence_collection

scene = bpy.context.scene
strips = ensure_sequence_collection(scene)
print("FLYNOTES_VSE_COLLECTION", type(strips), len(strips), bool(strips), flush=True)
created = strips.new_movie(video.name, str(video), channel=1, frame_start=1)
collection = sequence_collection(scene.sequence_editor)
print(
    "FLYNOTES_VSE_CREATED",
    created.name,
    created.type,
    created.filepath,
    len(collection),
    bool(collection),
    flush=True,
)
assert len(collection) == 1
bpy.ops.preferences.addon_disable(module="flynotes_ai")
