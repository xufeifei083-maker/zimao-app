bl_info = {
    "name": "Flynotes AI",
    "author": "Flynotes",
    "version": (1, 4, 0),
    "blender": (4, 0, 0),
    "location": "3D 视图 > 侧边栏 > Flynotes AI",
    "description": "在 Blender 里使用 Flynotes 生成图片和视频",
    "category": "3D View",
}

import os
import bpy

from .builtin_config import CONFIG
from . import background, runtime, vse_encoder, workbench_frames
from .local_video_session import clear_session_files
from .operators import CLASSES as OPERATOR_CLASSES, _seconds_left, recover_local_jobs
from .panels import PANEL_CLASSES, register_previews, register_properties, unregister_previews, unregister_properties


class FlynotesPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__.split(".", 1)[0]

    # Hidden migration fields for pre-1.4 preferences. Cloud requests now use
    # the local control center configured below.
    api_base: bpy.props.StringProperty(default="https://flynotes.top/api/v1", options={'HIDDEN'})
    custom_api: bpy.props.BoolProperty(default=False, options={'HIDDEN'})
    show_advanced: bpy.props.BoolProperty(name="高级设置", default=False)
    local_agent_api: bpy.props.StringProperty(
        name="本地控制中心 API",
        default="http://127.0.0.1:17980/api/v1",
    )
    local_agent_timeout: bpy.props.IntProperty(name="请求超时（秒）", default=120, min=5, max=3600)
    debug_logging: bpy.props.BoolProperty(name="调试日志", default=False)
    assets_root: bpy.props.StringProperty(
        name="本地素材目录",
        subtype='DIR_PATH',
        default=os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "FlynotesAI", "generated"),
    )
    auto_add_vse: bpy.props.BoolProperty(name="下载视频后自动加入剪辑器", default=True)
    session_id: bpy.props.StringProperty(options={'HIDDEN'})
    valid_until: bpy.props.StringProperty(options={'HIDDEN'})
    username: bpy.props.StringProperty(options={'HIDDEN'})
    user_code: bpy.props.StringProperty(options={'HIDDEN'})
    online_config_json: bpy.props.StringProperty(options={'HIDDEN'})
    previous_config_json: bpy.props.StringProperty(options={'HIDDEN'})
    config_version: bpy.props.StringProperty(default=CONFIG["configVersion"], options={'HIDDEN'})
    config_notes: bpy.props.StringProperty(options={'HIDDEN'})
    status_message: bpy.props.StringProperty(options={'HIDDEN'})

    def draw(self, _context):
        layout = self.layout
        account = layout.box()
        account.label(text="Flynotes 账号", icon='USER')
        if not self.session_id:
            account.operator("flynotes.login", icon='URL')
            if self.user_code:
                account.label(text=f"验证码：{self.user_code}")
        else:
            account.label(text=self.username or "已登录")
            if _seconds_left(self.valid_until) <= 0:
                account.operator("flynotes.verify", text="继续使用 7 天")
            elif not runtime.access_token:
                account.operator("flynotes.resume", text="恢复本次登录")
            account.operator("flynotes.logout", text="退出登录")
        layout.prop(self, "assets_root")
        layout.prop(self, "auto_add_vse")
        advanced = layout.box()
        advanced.prop(
            self,
            "show_advanced",
            text="高级设置",
            icon='TRIA_DOWN' if self.show_advanced else 'TRIA_RIGHT',
            emboss=False,
        )
        if self.show_advanced:
            advanced.prop(self, "local_agent_api")
            row = advanced.row(align=True)
            row.operator("flynotes.test_local_agent", text="测试连接", icon='LINKED')
            row.operator("flynotes.reset_local_agent", text="恢复默认", icon='LOOP_BACK')
            advanced.prop(self, "local_agent_timeout")
            advanced.prop(self, "debug_logging")
            advanced.label(text="云端请求由本地控制中心统一转发", icon='INFO')
        box = layout.box(); box.label(text=f"配置版本：{self.config_version}")
        if self.config_notes: box.label(text=self.config_notes)
        box.operator("flynotes.update_config")
        if self.previous_config_json:
            box.operator("flynotes.rollback_config")
        if self.status_message: layout.label(text=self.status_message, icon='INFO')


CLASSES = (FlynotesPreferences, *OPERATOR_CLASSES, *PANEL_CLASSES)


def _cleanup_orphan_scenes():
    workbench_frames.remove_orphan_scenes()
    vse_encoder.remove_orphan_scenes()
    return None


def _recover_jobs_after_register():
    recover_local_jobs()
    return None


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    register_properties()
    register_previews()
    if not bpy.app.timers.is_registered(background.pump):
        bpy.app.timers.register(background.pump, first_interval=0.1, persistent=True)
    bpy.app.timers.register(_cleanup_orphan_scenes, first_interval=0.1)
    if not bpy.app.timers.is_registered(_recover_jobs_after_register):
        bpy.app.timers.register(_recover_jobs_after_register, first_interval=0.5)


def unregister():
    if runtime.local_video_session and not runtime.local_video_session.is_active:
        clear_session_files(runtime.local_video_session)
        runtime.local_video_session = None
    runtime.session_jobs.clear()
    runtime.download_progress.clear()
    runtime.connection_status = "disconnected"
    runtime.connection_latency_ms = None
    runtime.generation_status.clear()
    runtime.generation_message.clear()
    runtime.last_submitted_jobs.clear()
    runtime.asset_preview_queue.clear()
    runtime.clear_camera_files()
    background.clear()
    if bpy.app.timers.is_registered(background.pump):
        bpy.app.timers.unregister(background.pump)
    if bpy.app.timers.is_registered(_recover_jobs_after_register):
        bpy.app.timers.unregister(_recover_jobs_after_register)
    unregister_previews()
    unregister_properties()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
