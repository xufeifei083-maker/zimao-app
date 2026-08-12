import os

import bpy

from .compat import set_image_media_type


SCENE_PREFIX = "Flynotes Workbench Temp"

VIEW_SHADING_PROPERTIES = (
    "type", "light", "color_type", "single_color",
    "show_shadows", "show_cavity", "show_specular_highlight",
    "background_type", "background_color", "background_alpha",
    "use_scene_world", "use_scene_lights", "render_pass",
)


def create_workbench_scene(source_scene, camera=None):
    scene = source_scene.copy()
    scene.name = f"{SCENE_PREFIX} {source_scene.name}"
    if camera:
        scene.camera = camera
    return scene


def remove_workbench_scene(scene):
    if scene and scene.name in bpy.data.scenes:
        bpy.data.scenes.remove(scene, do_unlink=True)


def remove_orphan_scenes():
    for scene in tuple(bpy.data.scenes):
        if scene.name.startswith(SCENE_PREFIX):
            bpy.data.scenes.remove(scene, do_unlink=True)


def frame_path(session, index):
    return os.path.join(session.frame_dir, f"frame_{index + 1:06d}.png")


def _snapshot_view(space):
    shading = space.shading
    values = {}
    for name in VIEW_SHADING_PROPERTIES:
        if hasattr(shading, name):
            values[name] = getattr(shading, name)
    return values, space.overlay.show_overlays


def snapshot_view(space):
    """Capture the active 3D view shading so one task can use one stable mode."""
    return _snapshot_view(space)


def _apply_view_settings(space, view_state):
    shading = space.shading
    shading_values, _overlays = view_state
    for name, value in shading_values.items():
        if hasattr(shading, name):
            try:
                setattr(shading, name, value)
            except Exception:
                pass
    space.overlay.show_overlays = False


def _restore_view(space, shading_values, overlays):
    for name, value in shading_values.items():
        try:
            setattr(space.shading, name, value)
        except Exception:
            pass
    space.overlay.show_overlays = overlays


def render_frame(context, workbench_scene, source_frame, target_path, camera=None, view_state=None):
    if context.area.type != "VIEW_3D" or context.region.type != "WINDOW":
        raise RuntimeError("请在 3D 视图中生成视图模式素材")
    space = context.space_data
    original_view_state = _snapshot_view(space)
    render_view_state = view_state or original_view_state
    shading_values, overlays = original_view_state
    region_3d = space.region_3d
    previous_perspective = region_3d.view_perspective
    previous_camera = getattr(space, "camera", None)
    render = workbench_scene.render
    render.filepath = target_path
    render.use_file_extension = True
    set_image_media_type(render.image_settings, "IMAGE")
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGB"
    workbench_scene.frame_set(source_frame)
    try:
        _apply_view_settings(space, render_view_state)
        if camera:
            workbench_scene.camera = camera
            if hasattr(space, "camera"):
                space.camera = camera
            region_3d.view_perspective = 'CAMERA'
        with context.temp_override(scene=workbench_scene):
            result = bpy.ops.render.opengl(write_still=True, view_context=True)
        if result != {"FINISHED"} or not os.path.isfile(target_path):
            raise RuntimeError(f"视图模式帧没有生成：{os.path.basename(target_path)}")
    finally:
        region_3d.view_perspective = previous_perspective
        if hasattr(space, "camera"):
            space.camera = previous_camera
        _restore_view(space, shading_values, overlays)


def read_frame_size(path):
    baseline = set(bpy.data.images)
    image = bpy.data.images.load(path, check_existing=False)
    try:
        return int(image.size[0]), int(image.size[1])
    finally:
        if image not in baseline:
            bpy.data.images.remove(image)
