import os

import bpy

from .compat import ensure_sequence_collection, set_image_media_type


SCENE_PREFIX = "Flynotes VSE Encode Temp"


def sequence_collection(scene):
    return ensure_sequence_collection(scene)


def output_candidates(output_path):
    folder = os.path.dirname(output_path)
    if not os.path.isdir(folder):
        return []
    stem = os.path.splitext(os.path.basename(output_path))[0]
    return [
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if name.startswith(stem)
        and name.lower().endswith(".mp4")
        and os.path.isfile(os.path.join(folder, name))
    ]


def delete_outputs(output_path):
    for path in output_candidates(output_path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def create_encode_scene(session):
    if not bpy.app.build_options.codec_ffmpeg:
        raise RuntimeError("当前 Blender 标准版没有可用的视频编码能力")
    if not session.has_complete_frames:
        raise RuntimeError("视图模式图片序列不完整，不能合成 MP4")
    delete_outputs(session.output_path)
    scene = bpy.data.scenes.new(f"{SCENE_PREFIX} {session.session_id[:8]}")
    try:
        scene.frame_start = 1
        scene.frame_end = session.frame_count
        scene.frame_set(1)
        scene.render.fps = session.fps
        scene.render.fps_base = session.fps_base
        scene.render.resolution_x = session.width
        scene.render.resolution_y = session.height
        scene.render.resolution_percentage = 100
        scene.render.filepath = session.output_path
        scene.render.use_file_extension = True
        set_image_media_type(scene.render.image_settings, "VIDEO")
        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.image_settings.color_mode = "RGB"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
        strips = sequence_collection(scene)
        strip = strips.new_image("Flynotes Workbench Frames", session.frame_paths[0], 1, 1)
        for path in session.frame_paths[1:]:
            strip.elements.append(os.path.basename(path))
        strip.frame_final_duration = session.frame_count
        return scene
    except Exception:
        bpy.data.scenes.remove(scene, do_unlink=True)
        raise


def remove_encode_scene(scene):
    if scene and scene.name in bpy.data.scenes:
        bpy.data.scenes.remove(scene, do_unlink=True)


def remove_orphan_scenes():
    for scene in tuple(bpy.data.scenes):
        if scene.name.startswith(SCENE_PREFIX):
            bpy.data.scenes.remove(scene, do_unlink=True)


def validate_output(session):
    candidates = output_candidates(session.output_path)
    if len(candidates) != 1 or os.path.getsize(candidates[0]) <= 0:
        raise RuntimeError("Blender 没有生成有效的 MP4")
    path = candidates[0]
    if os.path.abspath(path) != os.path.abspath(session.output_path):
        os.replace(path, session.output_path)
        path = session.output_path
    clip = bpy.data.movieclips.load(path, check_existing=False)
    try:
        width, height = int(clip.size[0]), int(clip.size[1])
        frames = int(clip.frame_duration)
        if width != session.width or height != session.height or frames < session.frame_count:
            raise RuntimeError(f"MP4 校验失败：{width}x{height}，{frames} 帧")
    finally:
        bpy.data.movieclips.remove(clip)
    return path
