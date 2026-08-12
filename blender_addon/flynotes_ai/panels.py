import datetime
import os
import textwrap

import bpy
import bpy.utils.previews

from . import background, runtime
from .builtin_config import CONFIG
from .operators import (
    AUDIO_EXTENSIONS,
    LOCAL_AGENT_MODEL_ID,
    VIDEO_EXTENSIONS,
    active_config,
    image_models,
    video_models,
    prefs,
    _seconds_left,
    _job_percent,
)


ASSET_PREVIEWS = None
_H3_MODEL = next(model for model in CONFIG["models"] if model.get("modelId") == LOCAL_AGENT_MODEL_ID)
_H3_DEFAULTS = {field["key"]: field.get("default") for field in _H3_MODEL.get("fields", [])}


def register_previews():
    global ASSET_PREVIEWS
    ASSET_PREVIEWS = bpy.utils.previews.new()


def unregister_previews():
    global ASSET_PREVIEWS
    if ASSET_PREVIEWS is not None:
        bpy.utils.previews.remove(ASSET_PREVIEWS)
        ASSET_PREVIEWS = None


def cache_preview(path):
    if ASSET_PREVIEWS is None or not path or not os.path.isfile(path) or path in ASSET_PREVIEWS:
        return
    try:
        ASSET_PREVIEWS.load(path, path, 'IMAGE')
    except Exception:
        pass


def preview_icon(path):
    return ASSET_PREVIEWS[path].icon_id if ASSET_PREVIEWS and path in ASSET_PREVIEWS else 0


RATIO_ITEMS = [(value, value, '') for value in ['1:1', '16:9', '9:16', '4:3', '3:4', '3:2', '2:3', '2:1', '1:2', '21:9', '9:21', '5:4', '4:5', '1:4', '4:1', '1:8', '8:1']]
RESOLUTION_ITEMS = [(value, value, '') for value in ['1K', '2K', '4K', '480P', '720P', '1080P']]
VIDEO_DURATION_ITEMS = [(str(value), f"{value} 秒", '') for value in range(4, 16)]
QUALITY_ITEMS = [('low', '低', ''), ('medium', '中等', ''), ('high', '高', '')]
GENERATION_TAB_ITEMS = [('image', '图片生成', ''), ('video', '视频生成', '')]
IMAGE_MODE_ITEMS = [('text', '文字生图', ''), ('camera', '摄像机视图生图', '')]
VIDEO_MODE_ITEMS = [('text', '文字生成', ''), ('first_frame', '首帧生成', ''), ('first_last', '首尾帧生成', ''), ('reference', '多素材参考', '')]


def _current_model(scene, media_type):
    model_id = scene.flynotes_image_model if media_type == 'image' else scene.flynotes_video_model
    models = [model for model in active_config().get('models', []) if model.get('mediaType') == media_type and model.get('enabled', True)]
    return next((model for model in models if model.get('modelId') == model_id), models[0] if models else {})


def _field_options(model, key, old_key):
    if model.get(old_key):
        return [str(value) for value in model[old_key]]
    field = next((item for item in model.get('fields', []) if item.get('key') == key), {})
    return [str(value) for value in field.get('options', [])]


def _filtered(items, allowed):
    result = [item for item in items if item[0] in allowed]
    return result or items[:1]


def image_modes(scene, _context): return _filtered(IMAGE_MODE_ITEMS, _current_model(scene, 'image').get('modes', []))
def video_modes(scene, _context): return _filtered(VIDEO_MODE_ITEMS, _current_model(scene, 'video').get('modes', []))
def image_ratios(scene, _context): return _filtered(RATIO_ITEMS, _field_options(_current_model(scene, 'image'), 'aspectRatio', 'ratios'))
def video_ratios(scene, _context): return _filtered(RATIO_ITEMS, _field_options(_current_model(scene, 'video'), 'aspectRatio', 'ratios'))
def image_resolutions(scene, _context): return _filtered(RESOLUTION_ITEMS, _field_options(_current_model(scene, 'image'), 'resolution', 'resolutions'))
def video_resolutions(scene, _context): return _filtered(RESOLUTION_ITEMS, _field_options(_current_model(scene, 'video'), 'resolution', 'resolutions'))
def image_qualities(scene, _context):
    allowed = ["low" if str(value).lower() in {"normal", "standard"} else str(value) for value in _field_options(_current_model(scene, 'image'), 'qualityMode', 'qualities')]
    return _filtered(QUALITY_ITEMS, allowed)
def video_durations(scene, _context): return _filtered(VIDEO_DURATION_ITEMS, _field_options(_current_model(scene, 'video'), 'duration', 'durations'))


def _set_first_valid(scene, property_name, values):
    if not values:
        return
    try:
        current = getattr(scene, property_name)
    except Exception:
        current = ""
    if current not in values:
        setattr(scene, property_name, values[0])


def sync_image_model(scene, _context):
    model = _current_model(scene, 'image')
    _set_first_valid(scene, "flynotes_image_mode", model.get('modes', []))
    _set_first_valid(scene, "flynotes_image_ratio", _field_options(model, 'aspectRatio', 'ratios'))
    _set_first_valid(scene, "flynotes_image_resolution", _field_options(model, 'resolution', 'resolutions'))
    quality_options = ["low" if str(value).lower() in {"normal", "standard"} else str(value) for value in _field_options(model, 'qualityMode', 'qualities')]
    _set_first_valid(scene, "flynotes_image_quality", quality_options)


def sync_video_model(scene, _context):
    model = _current_model(scene, 'video')
    _set_first_valid(scene, "flynotes_video_mode", model.get('modes', []))
    _set_first_valid(scene, "flynotes_video_ratio", _field_options(model, 'aspectRatio', 'ratios'))
    _set_first_valid(scene, "flynotes_video_resolution", _field_options(model, 'resolution', 'resolutions'))
    _set_first_valid(scene, "flynotes_video_duration", _field_options(model, 'duration', 'durations'))
    if model.get("modelId") == LOCAL_AGENT_MODEL_ID:
        defaults = {field.get("key"): field.get("default") for field in model.get("fields", [])}
        scene.flynotes_h3_width = int(defaults.get("width", scene.flynotes_h3_width))
        scene.flynotes_h3_height = int(defaults.get("height", scene.flynotes_h3_height))
        scene.flynotes_h3_steps = int(defaults.get("steps", scene.flynotes_h3_steps))
        scene.flynotes_h3_seed = int(defaults.get("seed", scene.flynotes_h3_seed))
        scene.flynotes_h3_ref_image_size = str(defaults.get("refImageSize", scene.flynotes_h3_ref_image_size))


def sync_video_mode(scene, _context):
    if scene.flynotes_video_mode != 'reference':
        scene.flynotes_video_use_workbench = False
        return
    session = runtime.local_video_session
    if session and session.output_path and os.path.isfile(session.output_path):
        scene.flynotes_video_use_workbench = True


class FlynotesInputItem(bpy.types.PropertyGroup):
    path: bpy.props.StringProperty(subtype='FILE_PATH')
    role: bpy.props.StringProperty()
    source: bpy.props.StringProperty()


class FlynotesAssetItem(bpy.types.PropertyGroup):
    path: bpy.props.StringProperty(subtype='FILE_PATH')
    media_type: bpy.props.StringProperty()
    size: bpy.props.IntProperty()
    sha256: bpy.props.StringProperty()
    task_id: bpy.props.StringProperty()
    thumbnail_path: bpy.props.StringProperty(subtype='FILE_PATH')


def _draw_asset_grid(layout, scene):
    grid = layout.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
    for index, item in enumerate(scene.flynotes_assets):
        icon_value = preview_icon(item.thumbnail_path)
        icon = 'IMAGE_DATA' if item.media_type == 'image' else 'SEQUENCE'
        cell = grid.column(align=True)
        if icon_value:
            cell.template_icon(icon_value=icon_value, scale=5.0)
        else:
            placeholder = cell.row(align=True)
            placeholder.scale_y = 4.0
            placeholder.label(text="", icon=icon)
        operator = cell.operator(
            "flynotes.asset_click", text=os.path.basename(item.path),
            icon=icon if not icon_value else 'NONE',
            depress=index == scene.flynotes_asset_index,
        )
        operator.index = index


def _asset_task_id(item):
    value = item.task_id or ""
    if value and len(value) < 36:
        match = next(
            (job.get("jobId", "") for job in runtime.session_jobs if job.get("jobId", "").startswith(value)),
            "",
        )
        if match:
            return match, False
    return value, bool(value and len(value) < 36)


def _status_label(status):
    return {
        "queued": "排队中", "running": "生成中", "done": "已完成",
        "failed": "已失败", "cancelled": "已取消", "canceled": "已取消",
    }.get(status, status or "未知")


def _time_label(value):
    if not value:
        return "刚刚"
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%m-%d %H:%M")
    except ValueError:
        return value[:16]


def _selected_camera(context):
    obj = context.active_object
    return obj if obj and obj.type == 'CAMERA' and obj.select_get() else None


def _draw_inputs(layout, items, media_type):
    if not items:
        layout.label(text="尚未选择素材", icon='INFO')
        return
    box = layout.box()
    for index, item in enumerate(items):
        row = box.row(align=True)
        extension = os.path.splitext(item.path)[1].lower()
        icon = 'SPEAKER' if extension in AUDIO_EXTENSIONS else 'SEQUENCE' if extension in VIDEO_EXTENSIONS else 'OUTLINER_OB_IMAGE'
        row.label(text=os.path.basename(item.path), icon=icon)
        view = row.operator("flynotes.open_input", text="", icon='HIDE_OFF')
        view.media_type, view.index = media_type, index
        save = row.operator("flynotes.save_input", text="", icon='EXPORT')
        save.media_type, save.index = media_type, index
        remove = row.operator("flynotes.remove_input", text="", icon='TRASH')
        remove.media_type, remove.index = media_type, index


def _draw_labeled_property(layout, data, property_name, label):
    row = layout.row(align=True)
    split = row.split(factor=0.22, align=True)
    split.label(text=f"{label}：")
    split.prop(data, property_name, text="")


def _draw_image_parameters(layout, scene):
    card = layout.box()
    grid = card.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
    for property_name, label in (
        ("flynotes_image_ratio", "比例"),
        ("flynotes_image_resolution", "清晰度"),
        ("flynotes_image_quality", "质量"),
        ("flynotes_image_count", "数量"),
    ):
        field = grid.column(align=True)
        field.label(text=label)
        field.prop(scene, property_name, text="")


def _draw_image_sources(layout, context):
    scene = context.scene
    card = layout.box()
    frame = card.column(align=True)
    frame.enabled = scene.flynotes_image_mode == 'camera'
    frame.label(text="渲染帧")
    frame.prop(scene, "flynotes_image_frame", text="")
    source = card.row(align=True)
    choose = source.operator("flynotes.choose_files", text="选择本地素材", icon='FILEBROWSER')
    choose.media_type = 'image'
    camera = _selected_camera(context)
    camera_row = source.row(align=True)
    camera_row.enabled = bool(camera) and scene.flynotes_image_mode == 'camera'
    capture = camera_row.operator(
        "flynotes.camera_input",
        text="渲染并添加当前帧" if camera else "请选中摄像机",
        icon='CAMERA_DATA',
    )
    capture.media_type = 'image'
    _draw_inputs(card, scene.flynotes_image_inputs, 'image')


def _draw_video_parameters(layout, scene):
    card = layout.box()
    if scene.flynotes_video_model == LOCAL_AGENT_MODEL_ID:
        fields = [
            ("flynotes_h3_width", "宽度"),
            ("flynotes_h3_height", "高度"),
            ("flynotes_video_duration", "时长"),
            ("flynotes_h3_steps", "采样步数"),
            ("flynotes_h3_seed", "Seed"),
        ]
        if scene.flynotes_video_mode == 'reference':
            fields.append(("flynotes_h3_ref_image_size", "参考图尺寸"))
    else:
        fields = [
            ("flynotes_video_ratio", "比例"),
            ("flynotes_video_resolution", "清晰度"),
            ("flynotes_video_duration", "时长"),
        ]
    grid = card.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True, align=True)
    for property_name, label in fields:
        field = grid.column(align=True)
        field.label(text=label)
        field.prop(scene, property_name, text="")


def _draw_video_sources(layout, context, session):
    scene = context.scene
    card = layout.box()
    frames = card.grid_flow(row_major=True, columns=3, even_columns=True, even_rows=True, align=True)
    for property_name, label in (
        ("flynotes_video_frame_start", "起始帧"),
        ("flynotes_video_frame_end", "结束帧"),
        ("flynotes_video_fps", "帧率"),
    ):
        field = frames.column(align=True)
        field.label(text=label)
        field.prop(scene, property_name, text="")
    source = card.row(align=True)
    choose = source.operator("flynotes.choose_files", text="选择本地素材", icon='FILEBROWSER')
    choose.media_type = 'video'
    camera = _selected_camera(context)
    camera_row = source.row(align=True)
    camera_row.enabled = bool(camera)
    capture = camera_row.operator(
        "flynotes.camera_input",
        text="渲染当前摄像机画面" if camera else "请选中摄像机",
        icon='CAMERA_DATA',
    )
    capture.media_type = 'video'
    has_workbench = scene.flynotes_video_use_workbench and session
    if has_workbench:
        status = card.box()
        status.label(text=session.phase_label, icon='RENDER_ANIMATION')
        if session.is_active:
            percent = round(session.progress * 100)
            if hasattr(status, "progress"):
                status.progress(factor=session.progress, type='BAR', text=f"{percent}%")
            if session.message:
                status.label(text=session.message)
            if session.phase not in {'encoding', 'cancelling'}:
                status.operator("flynotes.cancel_local_video", text="取消", icon='CANCEL')
            else:
                status.label(text="按 Esc 可安全取消", icon='EVENT_ESC')
        elif session.error:
            status.alert = True
            status.label(text=session.error, icon='ERROR')
            actions = status.row(align=True)
            if session.can_reencode:
                retry = actions.operator("flynotes.workbench_video", text="仅重新合成", icon='FILE_REFRESH')
                retry.reencode_only = True
            actions.operator("flynotes.clear_local_video", text="删除本地视频", icon='TRASH')
        elif session.output_path:
            output = status.row(align=True)
            output.label(text=os.path.basename(session.output_path), icon='FILE_MOVIE')
            output.operator("flynotes.open_local_video", text="", icon='HIDE_OFF')
            output.operator("flynotes.save_local_video", text="", icon='EXPORT')
            output.operator("flynotes.clear_local_video", text="", icon='TRASH')
    if scene.flynotes_video_inputs:
        _draw_inputs(card, scene.flynotes_video_inputs, 'video')
    elif not has_workbench:
        card.label(text="尚未选择素材", icon='INFO')


def _prompt_preview_lines(value, width):
    if not value:
        return ["提示词", "", "", ""]
    lines = []
    for paragraph in value.splitlines() or [value]:
        lines.extend(textwrap.wrap(paragraph, width=width, replace_whitespace=False) or [""])
    return [*lines, *([""] * (4 - len(lines)))]


def _draw_prompt(layout, context, media_type):
    property_name = "flynotes_image_prompt" if media_type == "image" else "flynotes_video_prompt"
    card = layout.box()
    card.prop(context.scene, property_name, text="提示词")
    actions = card.row(align=True)
    clear = actions.operator("flynotes.prompt_clipboard", text="清除", icon='X')
    clear.media_type, clear.action = media_type, 'clear'


class FLYNOTES_PT_task_center(bpy.types.Panel):
    bl_label = "任务中心"
    bl_idname = "FLYNOTES_PT_task_center"
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Flynotes AI'

    def draw(self, context):
        layout = self.layout
        preference = prefs(context)
        remaining = _seconds_left(preference.valid_until)
        account = layout.row(align=True)
        account.label(text=preference.username or "未登录", icon='USER')
        connection = account.row(align=True)
        connection.alignment = 'RIGHT'
        if runtime.connection_status == "connecting":
            connection.label(text="正在连接…", icon='TIME')
        elif not preference.session_id:
            connection.operator("flynotes.login", text="点击连接", icon='UNLINKED')
        elif remaining <= 0:
            connection.operator("flynotes.verify", text="已到期 · 点击验证", icon='ERROR')
        else:
            latency = runtime.connection_latency_ms
            if runtime.connection_status == "error":
                connection_text, connection_icon = "连接失败 · 点击重试", 'ERROR'
            elif runtime.access_token:
                connection_text = f"已连接 · 延时 {latency} ms · 重新连接" if latency is not None else "已连接 · 点击重连"
                connection_icon = 'LINKED'
            else:
                connection_text, connection_icon = "未连接 · 点击连接", 'UNLINKED'
            connection.operator("flynotes.resume", text=connection_text, icon=connection_icon)
        if runtime.network_status:
            layout.label(text=runtime.network_status, icon='NETWORK_DRIVE')
        layout.separator()
        if not runtime.session_jobs:
            layout.label(text="本次打开 Blender 尚无任务", icon='INFO')
        for job in runtime.session_jobs[:6]:
            box = layout.box()
            job_id = job.get('jobId', '')
            id_row = box.row(align=True)
            id_row.label(text=f"编号：{job_id}", icon='IMAGE_DATA' if job.get('_mediaType') == 'image' else 'SEQUENCE')
            copy = id_row.operator("flynotes.job_action", text="复制编号", icon='COPYDOWN')
            copy.job_id, copy.action = job_id, 'copy'
            percent = _job_percent(job)
            status = job.get('status')
            progress_text = " · ".join((
                _time_label(job.get('queuedAt') or job.get('createdAt')),
                _status_label(status),
                f"{percent}%",
            ))
            if hasattr(box, "progress"):
                box.progress(factor=percent / 100, type='BAR', text=progress_text)
            else:
                progress_row = box.row()
                progress_row.alignment = 'CENTER'
                progress_row.label(text=progress_text)
            actions = box.row(align=True)
            if status == 'failed':
                op = actions.operator("flynotes.job_action", text="取消", icon='CANCEL')
                op.job_id, op.action = job_id, 'remove'
            elif status == 'done':
                download = runtime.download_progress.get(job_id, {})
                if download.get("state") in {"sizing", "downloading", "done"}:
                    download_percent = download.get("percent", 0)
                    received_mb = download.get("receivedBytes", 0) / 1024 / 1024
                    total_mb = download.get("totalBytes", 0) / 1024 / 1024
                    if download.get("state") == "sizing":
                        text = "正在读取文件大小…"
                    elif download.get("state") == "done":
                        text = f"下载完成 · 100% · {total_mb:.1f} MB"
                    elif total_mb > 0:
                        text = f"下载中 · {download_percent}% · {received_mb:.1f} / {total_mb:.1f} MB"
                    else:
                        text = f"下载中 · 未知 · {received_mb:.1f} MB"
                    if hasattr(actions, "progress"):
                        actions.progress(factor=download_percent / 100, type='BAR', text=text)
                    else:
                        actions.label(text=text, icon='IMPORT')
                else:
                    text = "重新下载到本地素材" if download.get("state") == "failed" else "下载到本地素材"
                    op = actions.operator("flynotes.job_action", text=text, icon='IMPORT')
                    op.job_id, op.action = job_id, 'download'
        layout.operator("flynotes.open_history", icon='URL')


def _draw_image_generation(layout, context):
    scene = context.scene
    _draw_labeled_property(layout, scene, "flynotes_image_model", "模型")
    _draw_labeled_property(layout, scene, "flynotes_image_mode", "生成方式")
    _draw_prompt(layout, context, 'image')
    _draw_image_sources(layout, context)
    _draw_image_parameters(layout, scene)
    generate = layout.row(align=True)
    generate.scale_y = 2.0
    submitting = runtime.generation_status.get('image') == 'submitting'
    generate.enabled = not submitting
    button = generate.operator("flynotes.generate", text="生成中…" if submitting else "生成图片", icon='TIME' if submitting else 'PLAY')
    button.media_type = 'image'
    if submitting:
        layout.label(text=runtime.network_status or "正在连接、上传并提交任务…", icon='TIME')
    elif runtime.last_submitted_jobs.get('image'):
        submitted = layout.row(align=True)
        submitted.label(text="图片任务已提交", icon='CHECKMARK')
        submitted.operator("flynotes.open_task_center", text="打开任务中心", icon='VIEWZOOM')


def _draw_video_generation(layout, context):
    scene = context.scene
    _draw_labeled_property(layout, scene, "flynotes_video_model", "模型")
    _draw_labeled_property(layout, scene, "flynotes_video_mode", "生成方式")
    _draw_prompt(layout, context, 'video')
    session = runtime.local_video_session
    if scene.flynotes_video_mode != 'text':
        _draw_video_sources(layout, context, session)
    _draw_video_parameters(layout, scene)
    generate = layout.row(align=True)
    generate.scale_y = 2.0
    submitting = runtime.generation_status.get('video') == 'submitting'
    generate.enabled = not submitting
    button = generate.operator("flynotes.generate", text="生成中…" if submitting else "生成视频", icon='TIME' if submitting else 'PLAY')
    button.media_type = 'video'
    if submitting:
        layout.label(text=runtime.network_status or "正在连接、上传并提交任务…", icon='TIME')
    elif runtime.last_submitted_jobs.get('video'):
        submitted = layout.row(align=True)
        submitted.label(text="视频任务已提交", icon='CHECKMARK')
        submitted.operator("flynotes.open_task_center", text="打开任务中心", icon='VIEWZOOM')


class FLYNOTES_PT_generation(bpy.types.Panel):
    bl_label = "AI 生成"
    bl_idname = "FLYNOTES_PT_generation"
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Flynotes AI'

    def draw(self, context):
        layout, scene = self.layout, context.scene
        tabs = layout.row(align=True)
        tabs.scale_y = 1.35
        tabs.prop(scene, "flynotes_generation_tab", expand=True)
        layout.separator(factor=0.35)
        if scene.flynotes_generation_tab == 'image':
            _draw_image_generation(layout, context)
        else:
            _draw_video_generation(layout, context)


class FLYNOTES_PT_assets(bpy.types.Panel):
    bl_label = "本地素材"
    bl_idname = "FLYNOTES_PT_assets"
    bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Flynotes AI'

    def draw(self, context):
        layout, scene = self.layout, context.scene
        root = os.path.expanduser(bpy.path.abspath(prefs(context).assets_root))
        top = layout.row(align=True)
        open_folder = top.operator(
            "flynotes.reveal_file", text=os.path.basename(root) or root,
            icon='FILE_FOLDER', emboss=False,
        )
        open_folder.path = root
        top.operator("flynotes.refresh_assets", text="", icon='FILE_REFRESH')
        if runtime.asset_status:
            layout.label(text=runtime.asset_status, icon='TIME')
        if scene.flynotes_assets:
            _draw_asset_grid(layout, scene)
            index = min(max(0, scene.flynotes_asset_index), len(scene.flynotes_assets) - 1)
            item = scene.flynotes_assets[index]
            info = layout.box()
            info.label(
                text=f"图片名称：{os.path.basename(item.path)}",
                icon='IMAGE_DATA' if item.media_type == 'image' else 'SEQUENCE',
            )
            task_id, is_short_id = _asset_task_id(item)
            task = info.row(align=True)
            task.label(text=f"{'任务短编号' if is_short_id else '任务编号'}：{task_id or '—'}")
            copy = task.row(align=True)
            copy.enabled = bool(task_id)
            action = copy.operator("flynotes.copy_text", text="复制编号", icon='COPYDOWN')
            action.value = task_id
            info.label(text=f"文件大小：{item.size / 1024 / 1024:.1f} MB")
            reveal = info.operator("flynotes.reveal_file", text="打开所在位置", icon='FILE_FOLDER')
            reveal.path = item.path
        elif not background.is_active("assets-scan"):
            layout.label(text="暂无本地素材", icon='INFO')


PANEL_CLASSES = (
    FlynotesInputItem, FlynotesAssetItem,
    FLYNOTES_PT_task_center, FLYNOTES_PT_generation, FLYNOTES_PT_assets,
)


def register_properties():
    scene = bpy.types.Scene
    scene.flynotes_generation_tab = bpy.props.EnumProperty(name="生成类型", items=GENERATION_TAB_ITEMS, default='image')
    scene.flynotes_image_prompt = bpy.props.StringProperty(name="图片提示词", default="", options={'TEXTEDIT_UPDATE'})
    scene.flynotes_video_prompt = bpy.props.StringProperty(name="视频提示词", default="", options={'TEXTEDIT_UPDATE'})
    scene.flynotes_image_model = bpy.props.EnumProperty(name="图片模型", items=image_models, update=sync_image_model)
    scene.flynotes_video_model = bpy.props.EnumProperty(name="视频模型", items=video_models, update=sync_video_model)
    scene.flynotes_image_mode = bpy.props.EnumProperty(items=image_modes)
    scene.flynotes_video_mode = bpy.props.EnumProperty(items=video_modes, update=sync_video_mode)
    scene.flynotes_image_ratio = bpy.props.EnumProperty(items=image_ratios)
    scene.flynotes_video_ratio = bpy.props.EnumProperty(items=video_ratios)
    scene.flynotes_image_resolution = bpy.props.EnumProperty(items=image_resolutions)
    scene.flynotes_video_resolution = bpy.props.EnumProperty(items=video_resolutions)
    scene.flynotes_image_quality = bpy.props.EnumProperty(items=image_qualities)
    scene.flynotes_image_count = bpy.props.IntProperty(default=1, min=1, max=4)
    scene.flynotes_image_frame = bpy.props.IntProperty(name="渲染帧", default=1, min=0)
    scene.flynotes_video_duration = bpy.props.EnumProperty(items=video_durations)
    scene.flynotes_video_frame_start = bpy.props.IntProperty(name="起始帧", default=1, min=0)
    scene.flynotes_video_frame_end = bpy.props.IntProperty(name="结束帧", default=250, min=0)
    scene.flynotes_video_fps = bpy.props.IntProperty(name="帧率", default=24, min=1, max=120)
    scene.flynotes_h3_width = bpy.props.IntProperty(name="宽度", default=int(_H3_DEFAULTS["width"]), min=32, max=4096, step=32)
    scene.flynotes_h3_height = bpy.props.IntProperty(name="高度", default=int(_H3_DEFAULTS["height"]), min=32, max=4096, step=32)
    scene.flynotes_h3_steps = bpy.props.IntProperty(name="采样步数", default=int(_H3_DEFAULTS["steps"]), min=1, max=50)
    scene.flynotes_h3_seed = bpy.props.IntProperty(name="Seed", default=int(_H3_DEFAULTS["seed"]), min=-1)
    scene.flynotes_h3_ref_image_size = bpy.props.EnumProperty(
        name="参考图尺寸",
        items=[('match', 'match', '匹配输出尺寸'), ('max', 'max', '使用最大参考尺寸')],
        default=str(_H3_DEFAULTS["refImageSize"]),
    )
    scene.flynotes_video_use_workbench = bpy.props.BoolProperty(default=False, options={'HIDDEN'})
    scene.flynotes_image_inputs = bpy.props.CollectionProperty(type=FlynotesInputItem)
    scene.flynotes_video_inputs = bpy.props.CollectionProperty(type=FlynotesInputItem)
    scene.flynotes_assets = bpy.props.CollectionProperty(type=FlynotesAssetItem)
    scene.flynotes_asset_index = bpy.props.IntProperty(default=0)


def unregister_properties():
    for name in [name for name in dir(bpy.types.Scene) if name.startswith('flynotes_')]:
        delattr(bpy.types.Scene, name)
