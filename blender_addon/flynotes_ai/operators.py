import datetime
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
import uuid
import webbrowser

import bpy
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import background, runtime
from .api import ApiError, download_file, remote_file_size, request_json, upload_file
from .builtin_config import CONFIG
from .compat import ensure_sequence_collection, sequence_collection, set_image_media_type
from .local_video_session import clear_frame_files, clear_session_files, create_session
from .storage import ensure_video_thumbnail, installation_id, load_device_secret, refresh_assets, remove_device_secret, save_device_secret
from . import vse_encoder, workbench_frames

LOCAL_AGENT_MODEL_ID = "minimax-h3-local"
DEFAULT_LOCAL_AGENT_API = "http://127.0.0.1:17980/api/v1"
PLUGIN_VERSION = "1.4.0"
AUTH_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60


def redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def report_error(error):
    runtime.network_status = str(error)
    try:
        prefs().status_message = str(error)
    except Exception:
        pass
    redraw()


def report_connection_error(error):
    runtime.connection_status = "error"
    runtime.connection_latency_ms = None
    report_error(error)


def _set_generation_status(media_type, status="", message=""):
    runtime.generation_status[media_type] = status
    runtime.generation_message[media_type] = message
    if message:
        runtime.network_status = message
    redraw()


def prefs(context=None):
    context = context or bpy.context
    # Release packages run below flynotes_ai.versions.vX_Y_Z while the stable
    # loader remains the add-on root registered in Blender preferences.
    return context.preferences.addons[__package__.split(".", 1)[0]].preferences


def api_base(preference):
    # Blender never talks to Flynotes cloud directly. The local Agent owns the
    # upstream address, diagnostics and future provider routing.
    return f"{local_agent_base(preference)}/blender/cloud"


def local_agent_base(preference):
    return (preference.local_agent_api or DEFAULT_LOCAL_AGENT_API).strip().rstrip("/")


def _is_local_model(model_id):
    return model_id == LOCAL_AGENT_MODEL_ID


def _merge_local_model(config):
    local = next(
        (item for item in CONFIG.get("models", []) if item.get("modelId") == LOCAL_AGENT_MODEL_ID),
        None,
    )
    if not local:
        return config
    models = [item for item in config.get("models", []) if item.get("modelId") != LOCAL_AGENT_MODEL_ID]
    return {**config, "models": [local, *models]}


def active_config(context=None):
    try:
        preference = prefs(context)
    except (KeyError, AttributeError):
        # Blender may ask for dynamic enum values while an add-on is being
        # registered or hot-reloaded, before its preferences entry exists.
        return _merge_local_model(CONFIG)
    value = preference.online_config_json
    if value:
        try:
            online = json.loads(value)
            online_version = _config_version_tuple(online.get("configVersion"))
            builtin_version = _config_version_tuple(CONFIG.get("configVersion"))
            if not online_version or online_version >= builtin_version:
                return _merge_local_model(online)
        except Exception:
            pass
    return _merge_local_model(CONFIG)


def _config_version_tuple(value):
    try:
        return tuple(int(part) for part in str(value or "").split(".") if part.isdigit())
    except (TypeError, ValueError):
        return ()


_MODEL_ITEMS = {}


def _enum_models(media_type):
    def callback(_self, context):
        models = [
            model for model in active_config(context).get("models", [])
            if model.get("mediaType") == media_type and model.get("enabled", True)
        ]
        _MODEL_ITEMS[media_type] = [
            (model["modelId"], model["displayName"], "", index)
            for index, model in enumerate(models)
        ] or [("", "无可用模型", "", 0)]
        return _MODEL_ITEMS[media_type]
    return callback


image_models = _enum_models("image")
video_models = _enum_models("video")


def _model(model_id, media_type):
    return next((item for item in active_config().get("models", []) if item.get("modelId") == model_id and item.get("mediaType") == media_type), None)


def _seconds_left(value):
    if not value:
        return -1
    try:
        end = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (end - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    except ValueError:
        return -1


def _set_login(data, preference):
    global_token = data.get("accessToken", "")
    runtime.access_token = global_token
    preference.session_id = data.get("sessionId", preference.session_id)
    preference.valid_until = data.get("validUntil", "")
    user = data.get("user") or {}
    preference.username = user.get("username", preference.username)
    if data.get("deviceSecret"):
        save_device_secret(preference.session_id, data["deviceSecret"])
    runtime.last_auth_refresh_at = time.time()
    runtime.connection_status = "connected"


def _check_online_config(preference, base):
    """Fetch a newer public config when the user connects."""
    manifest = request_json(base, "/blender/config/manifest")
    if manifest["configVersion"] == preference.config_version:
        return manifest, None
    payload = request_json(base, f"/blender/config/{manifest['configVersion']}")
    raw = json.dumps(payload["config"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != payload["sha256"]:
        raise ApiError("配置校验失败，未应用更新")
    return manifest, payload


def _apply_online_config(preference, manifest, payload):
    if payload is None:
        return False
    preference.previous_config_json = preference.online_config_json
    preference.online_config_json = json.dumps(payload["config"], ensure_ascii=False)
    preference.config_version = manifest["configVersion"]
    preference.config_notes = manifest.get("notes", "")
    return True


def _connected_with_config(preference, data, latency_ms, config_result=None, config_error=""):
    _set_login(data, preference)
    updated = _apply_online_config(preference, *config_result) if config_result else False
    runtime.connection_latency_ms = latency_ms
    runtime.network_status = ""
    if config_error:
        preference.status_message = f"已连接，配置检查失败：{config_error}"
    else:
        preference.status_message = "已连接，配置已自动更新" if updated else "已连接"
    _resume_session_job_polling()
    redraw()


def poll_login():
    if not runtime.pending_device_code:
        return None
    if background.is_active("login-poll"):
        return 0.5
    preference = prefs()

    def success(data):
        if data.get("status") == "pending":
            return
        _set_login(data, preference)
        runtime.pending_device_code = ""
        preference.status_message = "登录成功，正在检查配置…"
        base = api_base(preference)

        def work():
            try:
                return _check_online_config(preference, base), ""
            except Exception as error:
                return None, str(error)

        def config_success(result):
            config_result, config_error = result
            updated = _apply_online_config(preference, *config_result) if config_result else False
            runtime.network_status = ""
            preference.status_message = (
                f"登录成功，配置检查失败：{config_error}" if config_error
                else "登录成功，配置已自动更新" if updated else "登录成功"
            )
            redraw()

        background.start("config-after-login", work, config_success, report_error)

    def failure(error):
        if time.time() - runtime.pending_started_at < 620 and "失效" not in str(error):
            return
        runtime.pending_device_code = ""
        runtime.connection_status = "error"
        runtime.connection_latency_ms = None
        preference.status_message = str(error)
        runtime.network_status = str(error)
        redraw()

    code = runtime.pending_device_code
    base = api_base(preference)
    background.start(
        "login-poll",
        lambda: request_json(base, "/blender/auth/complete", "POST", {"deviceCode": code}, timeout=10),
        success,
        failure,
    )
    return 1.0 if runtime.pending_device_code else None


class FLYNOTES_OT_login(bpy.types.Operator):
    bl_idname = "flynotes.login"
    bl_label = "登录 Flynotes"

    def execute(self, context):
        preference = prefs(context)
        if background.is_active("login-start"):
            return {'CANCELLED'}
        runtime.connection_status = "connecting"
        runtime.connection_latency_ms = None
        preference.status_message = "正在连接 Flynotes…"
        base = api_base(preference)
        blender_version = bpy.app.version_string

        def success(data):
            runtime.pending_device_code = data["deviceCode"]
            runtime.pending_started_at = time.time()
            preference.user_code = data["userCode"]
            preference.status_message = "请在浏览器确认登录"
            webbrowser.open(data["verificationUrl"])
            if not bpy.app.timers.is_registered(poll_login):
                bpy.app.timers.register(poll_login, first_interval=3.0)
            redraw()

        background.start(
            "login-start",
            lambda: request_json(base, "/blender/auth/start", "POST", {
                "pluginVersion": PLUGIN_VERSION, "deviceName": f"Blender {blender_version}",
            }),
            success,
            report_connection_error,
        )
        return {'FINISHED'}


class FLYNOTES_OT_verify(bpy.types.Operator):
    bl_idname = "flynotes.verify"
    bl_label = "继续使用 7 天"

    def execute(self, context):
        preference = prefs(context)
        try:
            secret = load_device_secret(preference.session_id)
            if not secret:
                raise ApiError("未找到设备密钥，请重新登录")
            preference.status_message = "正在验证…"
            runtime.connection_status = "connecting"
            runtime.connection_latency_ms = None
            base, session_id = api_base(preference), preference.session_id

            def work():
                started = time.perf_counter()
                data = request_json(base, "/blender/auth/verify", "POST", {"sessionId": session_id, "deviceSecret": secret})
                try:
                    config_result, config_error = _check_online_config(preference, base), ""
                except Exception as error:
                    config_result, config_error = None, str(error)
                return data, round((time.perf_counter() - started) * 1000), config_result, config_error

            def success(result):
                data, latency_ms, config_result, config_error = result
                _connected_with_config(preference, data, latency_ms, config_result, config_error)
                if not config_error:
                    preference.status_message = "已续期 7 天，配置已自动更新" if config_result and config_result[1] else "已续期 7 天"

            background.start(
                "auth-verify",
                work, success, report_connection_error,
            )
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class FLYNOTES_OT_resume(bpy.types.Operator):
    bl_idname = "flynotes.resume"
    bl_label = "恢复本次登录"

    def execute(self, context):
        preference = prefs(context)
        try:
            secret = load_device_secret(preference.session_id)
            if not secret:
                raise ApiError("未找到设备密钥，请重新登录")
            preference.status_message = "正在恢复登录…"
            runtime.connection_status = "connecting"
            runtime.connection_latency_ms = None
            base, session_id = api_base(preference), preference.session_id

            def work():
                started = time.perf_counter()
                data = request_json(base, "/blender/auth/refresh", "POST", {"sessionId": session_id, "deviceSecret": secret})
                try:
                    config_result, config_error = _check_online_config(preference, base), ""
                except Exception as error:
                    config_result, config_error = None, str(error)
                return data, round((time.perf_counter() - started) * 1000), config_result, config_error

            def success(result):
                data, latency_ms, config_result, config_error = result
                _connected_with_config(preference, data, latency_ms, config_result, config_error)
                if not config_error:
                    preference.status_message = "登录已恢复，配置已自动更新" if config_result and config_result[1] else "登录已恢复"

            background.start(
                "auth-resume",
                work, success, report_connection_error,
            )
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class FLYNOTES_OT_logout(bpy.types.Operator):
    bl_idname = "flynotes.logout"
    bl_label = "退出登录"

    def execute(self, context):
        preference = prefs(context)
        token, base = runtime.access_token, api_base(preference)
        if token:
            background.start("auth-revoke", lambda: request_json(base, "/blender/auth/revoke", "POST", {}, token))
        remove_device_secret(preference.session_id)
        runtime.access_token = ""
        runtime.last_auth_refresh_at = 0.0
        runtime.connection_status = "disconnected"
        runtime.connection_latency_ms = None
        preference.session_id = preference.valid_until = preference.username = ""
        return {'FINISHED'}


class FLYNOTES_OT_update_config(bpy.types.Operator):
    bl_idname = "flynotes.update_config"
    bl_label = "检查并更新配置"

    def execute(self, context):
        preference = prefs(context)
        if background.is_active("config-update"):
            return {'CANCELLED'}
        preference.status_message = "正在检查配置…"
        base = api_base(preference)

        def work():
            return _check_online_config(preference, base)

        def success(result):
            manifest, payload = result
            if payload is None:
                preference.status_message = "配置已是最新"
                redraw()
                return
            _apply_online_config(preference, manifest, payload)
            preference.status_message = "配置更新成功"
            redraw()

        background.start("config-update", work, success, report_error)
        return {'FINISHED'}


class FLYNOTES_OT_rollback_config(bpy.types.Operator):
    bl_idname = "flynotes.rollback_config"
    bl_label = "撤回配置"

    def execute(self, context):
        preference = prefs(context)
        if preference.previous_config_json:
            preference.online_config_json, preference.previous_config_json = preference.previous_config_json, preference.online_config_json
            preference.config_version = json.loads(preference.online_config_json).get("configVersion", CONFIG["configVersion"])
        else:
            preference.online_config_json = ""
            preference.config_version = CONFIG["configVersion"]
        return {'FINISHED'}


def _ensure_token():
    preference = prefs()
    if runtime.access_token and _seconds_left(preference.valid_until) > 0:
        return runtime.access_token
    if preference.session_id:
        raise ApiError("请先在插件偏好设置中恢复登录")
    raise ApiError("请先在插件偏好设置中登录 Flynotes")


def _auth_refresh_due(preference):
    if not runtime.access_token or _seconds_left(preference.valid_until) <= 0:
        return True
    return time.time() - runtime.last_auth_refresh_at >= AUTH_REFRESH_INTERVAL_SECONDS


def _start_auto_auth(preference, on_success, on_error=None):
    """Connect before generation, following the web client's 24-hour refresh gate."""
    secret = load_device_secret(preference.session_id)
    if not secret:
        raise ApiError("未找到设备密钥，请重新登录")
    base, session_id = api_base(preference), preference.session_id
    expired = _seconds_left(preference.valid_until) <= 0
    path = "/blender/auth/verify" if expired else "/blender/auth/refresh"
    preference.status_message = "正在自动连接…" if not expired else "登录已到期，正在恢复…"
    runtime.connection_status = "connecting"
    runtime.connection_latency_ms = None

    def work():
        started = time.perf_counter()
        body = {"sessionId": session_id, "deviceSecret": secret}
        try:
            data = request_json(base, path, "POST", body)
        except ApiError as error:
            if path != "/blender/auth/refresh" or "超过 7 天" not in str(error):
                raise
            data = request_json(base, "/blender/auth/verify", "POST", body)
        try:
            config_result, config_error = _check_online_config(preference, base), ""
        except Exception as error:
            config_result, config_error = None, str(error)
        return data, round((time.perf_counter() - started) * 1000), config_result, config_error

    def success(result):
        data, latency_ms, config_result, config_error = result
        _connected_with_config(preference, data, latency_ms, config_result, config_error)
        on_success(runtime.access_token)

    def failure(error):
        if on_error:
            on_error(error)
        else:
            report_connection_error(error)

    return background.start("auth-auto", work, success, failure)


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
ACTIVE_JOB_STATUSES = {"queued", "running"}
JOB_POLL_MAX_RETRY_SECONDS = 30


def _inputs(scene, media_type):
    return scene.flynotes_image_inputs if media_type == "image" else scene.flynotes_video_inputs


def _set_inputs(scene, media_type, values):
    collection = _inputs(scene, media_type)
    collection.clear()
    for path, role, source in values:
        item = collection.add()
        item.path, item.role, item.source = path, role, source


def _append_inputs(scene, media_type, values, limit):
    collection = _inputs(scene, media_type)
    existing = {os.path.realpath(item.path) for item in collection}
    added = []
    for path, role, source in values:
        real_path = os.path.realpath(path)
        if real_path in existing or len(collection) >= limit:
            continue
        item = collection.add()
        item.path, item.role, item.source = path, role, source
        existing.add(real_path)
        added.append(path)
    return added


def _job_percent(job):
    if job.get("status") == "done":
        return 100
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    value = metadata.get("progressPercent", metadata.get("progress", 0))
    try:
        value = float(value or 0)
        if 0 < value <= 1:
            value *= 100
        return max(0, min(99, round(value)))
    except (TypeError, ValueError):
        return 0


def _task_id_from_path(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    if not stem.startswith("flynotes_"):
        return ""
    value = stem[len("flynotes_"):]
    candidate = value[:36]
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError):
        return value.split("_", 1)[0]


def _show_downloaded_assets(scene, paths, task_id=""):
    """Show completed downloads immediately; the background scan fills hashes and thumbnails."""
    for path in reversed(paths):
        if not os.path.isfile(path):
            continue
        item = next((entry for entry in scene.flynotes_assets if entry.path == path), None)
        if item is None:
            item = scene.flynotes_assets.add()
        item.path = path
        item.media_type = "video" if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS else "image"
        item.size = os.path.getsize(path)
        item.task_id = task_id or _task_id_from_path(path)
        item.thumbnail_path = path if item.media_type == "image" else ""
        current_index = next((index for index, entry in enumerate(scene.flynotes_assets) if entry.path == path), -1)
        if current_index > 0:
            scene.flynotes_assets.move(current_index, 0)
    if paths:
        scene.flynotes_asset_index = 0


def _active_session_jobs():
    return [job for job in runtime.session_jobs if job.get("status") in ACTIVE_JOB_STATUSES]


def _set_job_poll_retry(error):
    """Keep the task visible and retry after a temporary network failure."""
    runtime.job_poll_failure_count += 1
    delay = min(JOB_POLL_MAX_RETRY_SECONDS, 2 ** min(runtime.job_poll_failure_count, 5))
    runtime.job_poll_retry_at = time.monotonic() + delay
    runtime.network_status = f"任务状态同步失败，{delay} 秒后自动重试"
    try:
        prefs().status_message = runtime.network_status
    except Exception:
        pass
    redraw()


def _reset_job_poll_retry():
    runtime.job_poll_failure_count = 0
    runtime.job_poll_retry_at = 0.0


def _resume_session_job_polling():
    """After a successful connection, immediately reconcile this Blender session's tasks."""
    if not _active_session_jobs():
        return
    _reset_job_poll_retry()
    if not bpy.app.timers.is_registered(poll_session_jobs):
        bpy.app.timers.register(poll_session_jobs, first_interval=0.1)
    poll_session_jobs()


def recover_local_jobs():
    """Restore Blender-originated Local Agent tasks after add-on reload/restart."""
    if background.is_active("local-job-recovery"):
        return
    try:
        preference = prefs()
    except Exception:
        return

    def work():
        return request_json(
            local_agent_base(preference),
            "/blender/jobs?limit=100",
            timeout=min(preference.local_agent_timeout, 30),
        )

    def success(rows):
        known = {job.get("jobId") for job in runtime.session_jobs}
        for job in reversed(rows if isinstance(rows, list) else []):
            if job.get("jobId") in known:
                continue
            job["_mediaType"] = "video"
            job["_provider"] = "local-agent"
            job["_prompt"] = (job.get("prompt") or "")[:160]
            runtime.session_jobs.insert(0, job)
        if _active_session_jobs():
            _resume_session_job_polling()
        redraw()

    def failure(_error):
        # Agent may legitimately be unavailable while Blender is starting.
        return None

    background.start("local-job-recovery", work, success, failure)


def poll_session_jobs():
    active = _active_session_jobs()
    if not active:
        return None
    if background.is_active("job-poll"):
        return 0.5
    wait_seconds = runtime.job_poll_retry_at - time.monotonic()
    if wait_seconds > 0:
        return max(0.5, min(wait_seconds, JOB_POLL_MAX_RETRY_SECONDS))
    try:
        preference = prefs()
    except Exception:
        return 2.0
    jobs = [(job["jobId"], job.get("_provider", "flynotes")) for job in active]

    def work():
        rows, errors = [], []
        # One failed request must not prevent the other tasks from refreshing.
        for job_id, provider in jobs:
            try:
                is_local = provider == "local-agent"
                base = local_agent_base(preference) if is_local else api_base(preference)
                token = "" if is_local else runtime.access_token
                row = request_json(base, f"/blender/jobs/{job_id}", token=token, timeout=20)
                row["_provider"] = provider
                rows.append(row)
            except Exception as error:
                errors.append(error)
        return rows, errors

    def success(result):
        rows, errors = result
        by_id = {row["jobId"]: row for row in rows}
        for index, old in enumerate(runtime.session_jobs):
            if old.get("jobId") in by_id:
                updated = by_id[old["jobId"]]
                updated["_mediaType"] = old.get("_mediaType")
                updated["_prompt"] = old.get("_prompt", "")
                updated["_provider"] = old.get("_provider", updated.get("_provider", "flynotes"))
                runtime.session_jobs[index] = updated
                if preference.debug_logging:
                    print(
                        "FLYNOTES_JOB_SYNC",
                        updated.get("jobId"),
                        old.get("status"),
                        "->",
                        updated.get("status"),
                        flush=True,
                    )
        if errors:
            _set_job_poll_retry(errors[0])
        else:
            _reset_job_poll_retry()
            if runtime.network_status.startswith("任务状态同步失败"):
                runtime.network_status = ""
        redraw()

    background.start("job-poll", work, success, _set_job_poll_retry)
    return 2.0


class FLYNOTES_OT_test_local_agent(bpy.types.Operator):
    bl_idname = "flynotes.test_local_agent"
    bl_label = "测试本地控制中心连接"

    def execute(self, context):
        preference = prefs(context)

        def work():
            return request_json(
                local_agent_base(preference),
                "/blender/config/manifest",
                timeout=preference.local_agent_timeout,
            )

        def success(data):
            preference.status_message = f"本地控制中心已连接 · Agent {data.get('agentVersion', 'unknown')}"
            runtime.network_status = ""
            redraw()

        if not background.start("agent-test", work, success, report_error):
            self.report({'INFO'}, "正在测试连接")
            return {'CANCELLED'}
        return {'FINISHED'}


class FLYNOTES_OT_reset_local_agent(bpy.types.Operator):
    bl_idname = "flynotes.reset_local_agent"
    bl_label = "恢复默认本地控制中心地址"

    def execute(self, context):
        prefs(context).local_agent_api = DEFAULT_LOCAL_AGENT_API
        self.report({'INFO'}, "已恢复默认地址")
        return {'FINISHED'}


class FLYNOTES_OT_generate(bpy.types.Operator):
    bl_idname = "flynotes.generate"
    bl_label = "开始生成"
    media_type: bpy.props.EnumProperty(items=[("image", "图片", ""), ("video", "视频", "")])

    def execute(self, context):
        scene, preference = context.scene, prefs(context)
        media_type = self.media_type
        status_started = False
        if background.is_active("generate") or background.is_active("auth-auto"):
            self.report({'INFO'}, "已有任务正在提交")
            return {'CANCELLED'}
        try:
            model_id = scene.flynotes_image_model if self.media_type == "image" else scene.flynotes_video_model
            mode = scene.flynotes_image_mode if self.media_type == "image" else scene.flynotes_video_mode
            prompt = (scene.flynotes_image_prompt if self.media_type == "image" else scene.flynotes_video_prompt).strip()
            if not prompt:
                raise ApiError("请填写提示词")
            if not _model(model_id, self.media_type):
                raise ApiError("请先选择模型")
            local_session = runtime.local_video_session
            selected = [(item.path, item.role) for item in _inputs(scene, self.media_type) if os.path.isfile(item.path)]
            if self.media_type == "video" and scene.flynotes_video_use_workbench:
                if not local_session or local_session.phase != "ready" or not os.path.isfile(local_session.output_path):
                    raise ApiError("请先完成摄像机视图模式 MP4")
                selected.insert(0, (local_session.output_path, "reference_video"))
                mode = "reference"
            if self.media_type == "video" and mode == "reference":
                slots = (_model(model_id, "video") or {}).get("inputSlots", {})
                image_count = sum(os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS for path, _role in selected)
                video_count = sum(os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS for path, _role in selected)
                audio_count = sum(os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS for path, _role in selected)
                if image_count > int(slots.get("maxImages", 9)):
                    raise ApiError("参考图片数量超出当前模型上限")
                if video_count > int(slots.get("maxVideos", 3)):
                    raise ApiError("参考视频数量超出当前模型上限")
                if audio_count > int(slots.get("maxAudios", 3)):
                    raise ApiError("参考音频数量超出当前模型上限")
            _set_generation_status(media_type, "submitting", "正在准备提交…")
            status_started = True

            def generation_failure(error):
                message = str(error)
                _set_generation_status(media_type, "", message)
                runtime.network_status = message
                preference.status_message = message
                redraw()

            def start_generation(token):
                is_local = media_type == "video" and _is_local_model(model_id)
                if is_local:
                    parameters = {
                        "width": scene.flynotes_h3_width,
                        "height": scene.flynotes_h3_height,
                        "duration": float(scene.flynotes_video_duration),
                        "steps": scene.flynotes_h3_steps,
                        "seed": scene.flynotes_h3_seed,
                        "refImageSize": scene.flynotes_h3_ref_image_size,
                    }
                else:
                    parameters = {
                        "aspectRatio": scene.flynotes_image_ratio if media_type == "image" else scene.flynotes_video_ratio,
                        "resolution": scene.flynotes_image_resolution if media_type == "image" else scene.flynotes_video_resolution,
                    }
                if media_type == "image":
                    quality_mode = {"normal": "low", "standard": "low"}.get(scene.flynotes_image_quality, scene.flynotes_image_quality)
                    parameters.update({"qualityMode": quality_mode, "count": scene.flynotes_image_count})
                elif not is_local:
                    parameters["duration"] = int(scene.flynotes_video_duration)
                base = local_agent_base(preference) if is_local else api_base(preference)
                payload = {
                    "clientRequestId": str(uuid.uuid4()), "installationId": installation_id(),
                    "pluginVersion": PLUGIN_VERSION, "configVersion": preference.config_version,
                    "mediaType": media_type, "modelId": model_id, "prompt": prompt,
                    "mode": mode, "parameters": parameters,
                }
                runtime.network_status = "正在准备素材…"

                def progress(sent, total):
                    message = f"正在上传 {round(sent / max(1, total) * 100)}%"
                    if runtime.network_status != message:
                        runtime.network_status = message
                        background.request_redraw()

                def work():
                    uploads = []
                    for path, role in selected:
                        uploaded = upload_file(base, "/blender/uploads", path, token, progress=progress)
                        uploads.append({"uploadId": uploaded["uploadId"], "role": role})
                    payload["inputs"] = uploads
                    return request_json(base, "/blender/jobs", "POST", payload, token, timeout=120)

                def success(job):
                    job["_mediaType"] = media_type
                    job["_prompt"] = prompt[:160]
                    job["_provider"] = "local-agent" if is_local else "flynotes"
                    runtime.session_jobs.insert(0, job)
                    runtime.last_submitted_jobs[media_type] = job.get("jobId", "")
                    _set_generation_status(media_type, "", "任务已提交")
                    runtime.network_status = "任务已提交"
                    preference.status_message = "任务已提交"
                    if media_type == "video" and scene.flynotes_video_use_workbench and local_session:
                        local_session.set_phase("submitted", progress=1.0, message="任务已进入任务中心")
                    _resume_session_job_polling()
                    redraw()

                if not background.start("generate", work, success, generation_failure):
                    generation_failure(ApiError("已有任务正在提交"))

            if media_type == "video" and _is_local_model(model_id):
                start_generation("")
            elif _auth_refresh_due(preference):
                if not preference.session_id:
                    raise ApiError("请先在插件偏好设置中登录 Flynotes")
                if not _start_auto_auth(preference, start_generation, generation_failure):
                    self.report({'INFO'}, "正在自动连接 Flynotes")
                    return {'CANCELLED'}
            else:
                start_generation(_ensure_token())
            return {'FINISHED'}
        except Exception as error:
            if status_started:
                _set_generation_status(media_type, "", str(error))
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class FLYNOTES_OT_job_action(bpy.types.Operator):
    bl_idname = "flynotes.job_action"
    bl_label = "任务操作"
    job_id: bpy.props.StringProperty()
    action: bpy.props.EnumProperty(items=[("remove", "取消", ""), ("download", "下载", ""), ("copy", "复制编号", "")])

    def execute(self, context):
        job_id = self.job_id
        action = self.action
        job = next((item for item in runtime.session_jobs if item.get("jobId") == job_id), None)
        if not job:
            return {'CANCELLED'}
        if action == "copy":
            context.window_manager.clipboard = job_id
            self.report({'INFO'}, "任务编号已复制")
            return {'FINISHED'}
        if action == "remove":
            if job.get("status") != "failed":
                return {'CANCELLED'}
            runtime.session_jobs.remove(job)
            redraw()
            return {'FINISHED'}
        if background.is_active(f"job-{job_id}"):
            return {'CANCELLED'}
        try:
            preference = prefs(context)
            is_local = job.get("_provider") == "local-agent" or _is_local_model(job.get("modelId"))
            token = "" if is_local else _ensure_token()
            base = local_agent_base(preference) if is_local else api_base(preference)
            if job.get("status") != "done":
                raise ApiError("任务还没完成")
            root = os.path.expanduser(bpy.path.abspath(preference.assets_root))
            output_count = max(1, int((job.get("result") or {}).get("outputCount", 0)))
            extension = ".mp4" if job.get("_mediaType") == "video" else ".png"
            runtime.download_progress[job_id] = {
                "state": "sizing", "percent": 0, "receivedBytes": 0, "totalBytes": 0,
            }
            redraw()

            def work():
                if preference.debug_logging:
                    print("FLYNOTES_RESULT_RESOLVE", job_id, "local=" + str(is_local), flush=True)
                os.makedirs(root, exist_ok=True)
                local_path = (job.get("result") or {}).get("localPath") if is_local else ""
                if local_path and os.path.isfile(local_path):
                    runtime.download_progress[job_id] = {
                        "state": "done", "percent": 100,
                        "receivedBytes": os.path.getsize(local_path),
                        "totalBytes": os.path.getsize(local_path),
                    }
                    paths = [os.path.abspath(local_path)]
                    if preference.debug_logging:
                        print("FLYNOTES_RESULT_READY", job_id, paths[0], flush=True)
                    return paths
                urls = [f"{base}/blender/jobs/{job_id}/outputs/{index}" for index in range(output_count)]
                sizes = [remote_file_size(url, token) for url in urls]
                total_bytes = sum(sizes) if sizes and all(size > 0 for size in sizes) else 0
                runtime.download_progress[job_id] = {
                    "state": "downloading", "percent": 0,
                    "receivedBytes": 0, "totalBytes": total_bytes,
                }
                background.request_redraw()
                paths = []
                completed_bytes = 0
                for index in range(output_count):
                    suffix = f"_{index + 1}" if output_count > 1 else ""
                    target = os.path.join(root, f"flynotes_{job_id}{suffix}{extension}")

                    def progress(received, _expected, downloaded_before=completed_bytes):
                        received_bytes = downloaded_before + received
                        percent = round(received_bytes / total_bytes * 100) if total_bytes else 0
                        updated = {
                            "state": "downloading",
                            "percent": max(0, min(99, percent)),
                            "receivedBytes": received_bytes,
                            "totalBytes": total_bytes,
                        }
                        if runtime.download_progress.get(job_id) != updated:
                            runtime.download_progress[job_id] = updated
                            background.request_redraw()

                    download_file(
                        urls[index],
                        target, token, progress=progress,
                    )
                    completed_bytes += os.path.getsize(target)
                    paths.append(target)
                return paths

            def success(paths):
                if preference.debug_logging:
                    print("FLYNOTES_RESULT_APPLY", job_id, paths, flush=True)
                total_bytes = sum(os.path.getsize(path) for path in paths)
                runtime.download_progress[job_id] = {
                    "state": "done", "percent": 100,
                    "receivedBytes": total_bytes, "totalBytes": total_bytes,
                }
                runtime.network_status = ""
                scene = context.scene
                _show_downloaded_assets(scene, paths, job_id)
                if job.get("_mediaType") == "video" and preference.auto_add_vse:
                    strips = ensure_sequence_collection(scene)
                    strips.new_movie(
                        os.path.basename(paths[0]),
                        paths[0],
                        channel=1,
                        frame_start=scene.frame_current,
                    )
                _start_asset_refresh(scene, root)
                redraw()

            def failure(error):
                runtime.download_progress[job_id] = {"state": "failed", "percent": 0}
                report_error(error)

            started = background.start(f"job-{job_id}", work, success, failure)
            if not started:
                raise ApiError("结果处理任务已经在运行")
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


class FLYNOTES_OT_edit_prompt(bpy.types.Operator):
    bl_idname = "flynotes.edit_prompt"
    bl_label = "手动输入提示词"
    media_type: bpy.props.EnumProperty(items=[("image", "图片", ""), ("video", "视频", "")])
    prompt: bpy.props.StringProperty(name="提示词", options={'TEXTEDIT_UPDATE'})

    def invoke(self, context, _event):
        property_name = "flynotes_image_prompt" if self.media_type == "image" else "flynotes_video_prompt"
        self.prompt = getattr(context.scene, property_name)
        return context.window_manager.invoke_props_dialog(self, width=620)

    def draw(self, _context):
        self.layout.prop(self, "prompt", text="")

    def execute(self, context):
        property_name = "flynotes_image_prompt" if self.media_type == "image" else "flynotes_video_prompt"
        setattr(context.scene, property_name, self.prompt)
        redraw()
        return {'FINISHED'}


class FLYNOTES_OT_prompt_clipboard(bpy.types.Operator):
    bl_idname = "flynotes.prompt_clipboard"
    bl_label = "提示词剪贴板"
    media_type: bpy.props.EnumProperty(items=[("image", "图片", ""), ("video", "视频", "")])
    action: bpy.props.EnumProperty(items=[("paste", "粘贴", ""), ("copy", "复制", ""), ("clear", "清空", "")])

    def execute(self, context):
        property_name = "flynotes_image_prompt" if self.media_type == "image" else "flynotes_video_prompt"
        if self.action == "copy":
            context.window_manager.clipboard = getattr(context.scene, property_name)
            self.report({'INFO'}, "提示词已复制")
        elif self.action == "clear":
            setattr(context.scene, property_name, "")
        else:
            value = context.window_manager.clipboard.replace("\r\n", "\n").replace("\r", "\n").strip()
            if not value:
                self.report({'ERROR'}, "剪贴板里没有文字")
                return {'CANCELLED'}
            if len(value) > 12000:
                self.report({'ERROR'}, "提示词不能超过 12000 个字符")
                return {'CANCELLED'}
            setattr(context.scene, property_name, value)
            self.report({'INFO'}, f"已粘贴 {len(value)} 个字符")
        redraw()
        return {'FINISHED'}


class FLYNOTES_OT_copy_text(bpy.types.Operator):
    bl_idname = "flynotes.copy_text"
    bl_label = "复制文字"
    value: bpy.props.StringProperty()

    def execute(self, context):
        if not self.value:
            return {'CANCELLED'}
        context.window_manager.clipboard = self.value
        self.report({'INFO'}, "已复制编号")
        return {'FINISHED'}


class FLYNOTES_OT_choose_files(bpy.types.Operator, ImportHelper):
    bl_idname = "flynotes.choose_files"
    bl_label = "选择本地素材"
    filename_ext = ""
    filter_glob: bpy.props.StringProperty(default="*.png;*.jpg;*.jpeg;*.webp;*.mp4;*.mov;*.webm;*.mkv;*.wav;*.mp3;*.m4a;*.aac;*.flac;*.ogg", options={'HIDDEN'})
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    media_type: bpy.props.EnumProperty(items=[("image", "图片", ""), ("video", "视频", "")])

    def invoke(self, context, event):
        root = os.path.expanduser(bpy.path.abspath(prefs(context).assets_root))
        self.filepath = os.path.join(root, "")
        return ImportHelper.invoke(self, context, event)

    def execute(self, context):
        directory = getattr(self, "directory", "") or os.path.dirname(self.filepath)
        paths = [os.path.join(directory, item.name) for item in self.files] or [self.filepath]
        paths = [os.path.abspath(path) for path in paths if os.path.isfile(path)]
        scene = context.scene
        if self.media_type == "image":
            paths = [path for path in paths if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS][:16]
            values = [(path, "reference_image", "local") for path in paths]
        else:
            mode = scene.flynotes_video_mode
            if mode == "first_frame":
                paths = [path for path in paths if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS][:1]
                roles = ["first_frame"]
            elif mode == "first_last":
                paths = [path for path in paths if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS][:2]
                roles = ["first_frame", "last_frame"]
            else:
                paths = [path for path in paths if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS][:15]
                roles = [
                    "reference_video" if os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS
                    else "reference_audio" if os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS
                    else "reference_image"
                    for path in paths
                ]
            values = [(path, role, "local") for path, role in zip(paths, roles)]
        if not values:
            self.report({'ERROR'}, "没有选择可用的素材")
            return {'CANCELLED'}
        if self.media_type == "image":
            added = _append_inputs(scene, "image", values, 16)
            if not added:
                self.report({'INFO'}, "素材已在列表中，或已达 16 个上限")
                return {'CANCELLED'}
        elif scene.flynotes_video_mode == "reference":
            added = _append_inputs(scene, "video", values, 15)
            if not added:
                self.report({'INFO'}, "素材已在列表中，或已达上限")
                return {'CANCELLED'}
        else:
            _clear_camera_inputs(scene, self.media_type)
            _set_inputs(scene, self.media_type, values)
        redraw()
        return {'FINISHED'}


class FLYNOTES_OT_remove_input(bpy.types.Operator):
    bl_idname = "flynotes.remove_input"
    bl_label = "移除素材"
    media_type: bpy.props.EnumProperty(items=[("image", "图片", ""), ("video", "视频", "")])
    index: bpy.props.IntProperty()

    def execute(self, context):
        collection = _inputs(context.scene, self.media_type)
        if 0 <= self.index < len(collection):
            item = collection[self.index]
            if item.source == "camera":
                runtime.clear_camera_files([item.path])
            collection.remove(self.index)
        if self.media_type == "video":
            redraw()
        return {'FINISHED'}


class FLYNOTES_OT_open_input(bpy.types.Operator):
    bl_idname = "flynotes.open_input"
    bl_label = "查看素材"
    media_type: bpy.props.EnumProperty(items=[("image", "图片", ""), ("video", "视频", "")])
    index: bpy.props.IntProperty()

    def execute(self, context):
        items = _inputs(context.scene, self.media_type)
        if not (0 <= self.index < len(items)) or not os.path.isfile(items[self.index].path):
            self.report({'ERROR'}, "素材文件不存在")
            return {'CANCELLED'}
        path = os.path.abspath(items[self.index].path)
        if platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        elif platform.system() == "Windows":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
        return {'FINISHED'}


class FLYNOTES_OT_save_input(bpy.types.Operator, ExportHelper):
    bl_idname = "flynotes.save_input"
    bl_label = "另存素材"
    filename_ext = ""
    filter_glob: bpy.props.StringProperty(
        default="*.png;*.jpg;*.jpeg;*.webp;*.mp4;*.mov;*.webm;*.mkv;*.wav;*.mp3;*.m4a;*.aac;*.flac;*.ogg",
        options={'HIDDEN'},
    )
    media_type: bpy.props.EnumProperty(items=[("image", "图片", ""), ("video", "视频", "")])
    index: bpy.props.IntProperty()

    def _source(self, context):
        items = _inputs(context.scene, self.media_type)
        if 0 <= self.index < len(items):
            return os.path.abspath(items[self.index].path)
        return ""

    def invoke(self, context, event):
        source = self._source(context)
        if not source or not os.path.isfile(source):
            self.report({'ERROR'}, "素材文件不存在")
            return {'CANCELLED'}
        folder = "Pictures" if self.media_type == "image" else "Movies"
        self.filepath = os.path.join(os.path.expanduser(f"~/{folder}"), os.path.basename(source))
        return ExportHelper.invoke(self, context, event)

    def execute(self, context):
        source = self._source(context)
        if not source or not os.path.isfile(source):
            self.report({'ERROR'}, "素材文件不存在")
            return {'CANCELLED'}
        target = os.path.abspath(bpy.path.abspath(self.filepath))
        source_extension = os.path.splitext(source)[1]
        if source_extension and not os.path.splitext(target)[1]:
            target += source_extension
        if os.path.normcase(source) == os.path.normcase(target):
            self.report({'INFO'}, "该位置就是当前素材")
            return {'FINISHED'}
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        self.report({'INFO'}, "素材已保存")
        return {'FINISHED'}


def _selected_camera(context):
    obj = context.active_object
    return obj if obj and obj.type == 'CAMERA' and obj.select_get() else None


def _clear_camera_inputs(scene, media_type):
    paths = [item.path for item in _inputs(scene, media_type) if item.source == "camera"]
    if paths:
        runtime.clear_camera_files(paths)


def _capture_camera_frames(context, camera, frames, media_type, roles, append=False, limit=16):
    folder = tempfile.mkdtemp(prefix="flynotes_camera_view_")
    scene = None
    paths = []
    view_state = workbench_frames.snapshot_view(context.space_data)
    try:
        scene = workbench_frames.create_workbench_scene(context.scene, camera)
        for index, frame in enumerate(frames):
            path = os.path.join(folder, f"camera_{frame}_{index + 1}.png")
            workbench_frames.render_frame(
                context, scene, frame, path, camera=camera, view_state=view_state,
            )
            paths.append(path)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        if scene:
            workbench_frames.remove_workbench_scene(scene)
    values = [(path, role, "camera") for path, role in zip(paths, roles)]
    if append:
        added = _append_inputs(context.scene, media_type, values, limit)
        rejected = [path for path in paths if path not in added]
        if rejected:
            runtime.clear_camera_files(rejected)
        if not added:
            raise ApiError(f"素材已达 {limit} 个上限")
        runtime.camera_temp_files.extend(added)
    else:
        _clear_camera_inputs(context.scene, media_type)
        runtime.camera_temp_files.extend(paths)
        _set_inputs(context.scene, media_type, values)


class FLYNOTES_OT_camera_input(bpy.types.Operator):
    bl_idname = "flynotes.camera_input"
    bl_label = "渲染当前摄像机画面"
    media_type: bpy.props.EnumProperty(items=[("image", "图片", ""), ("video", "视频", "")])

    def execute(self, context):
        camera = _selected_camera(context)
        if not camera:
            self.report({'ERROR'}, "请先选中一个摄像机")
            return {'CANCELLED'}
        scene = context.scene
        try:
            if self.media_type == "image":
                _capture_camera_frames(
                    context, camera, [scene.flynotes_image_frame], "image", ["source_image"],
                    append=True, limit=16,
                )
                return {'FINISHED'}
            mode = scene.flynotes_video_mode
            if mode == "first_frame":
                _capture_camera_frames(context, camera, [scene.flynotes_video_frame_start], "video", ["first_frame"])
                scene.flynotes_video_use_workbench = False
            elif mode == "first_last":
                _capture_camera_frames(
                    context, camera,
                    [scene.flynotes_video_frame_start, scene.flynotes_video_frame_end],
                    "video", ["first_frame", "last_frame"],
                )
                scene.flynotes_video_use_workbench = False
            elif mode == "reference":
                scene.flynotes_video_use_workbench = True
                result = bpy.ops.flynotes.workbench_video('INVOKE_DEFAULT')
                if 'RUNNING_MODAL' not in result:
                    raise ApiError("视图模式视频没有启动")
            else:
                raise ApiError("纯文字方式不需要摄像机素材")
            return {'FINISHED'}
        except Exception as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}


def load_asset_previews():
    if not runtime.asset_preview_queue:
        runtime.asset_status = ""
        redraw()
        return None
    path = runtime.asset_preview_queue.pop(0)
    try:
        scene = bpy.context.scene
        item = next((entry for entry in scene.flynotes_assets if entry.path == path), None)
        if item:
            if item.media_type == "video":
                item.thumbnail_path = ensure_video_thumbnail(path, os.path.expanduser(bpy.path.abspath(prefs().assets_root)))
            else:
                item.thumbnail_path = path
            from .panels import cache_preview
            cache_preview(item.thumbnail_path)
    except Exception:
        pass
    runtime.asset_status = f"正在准备缩略图（剩余 {len(runtime.asset_preview_queue)}）"
    redraw()
    return 0.05


class FLYNOTES_OT_refresh_assets(bpy.types.Operator):
    bl_idname = "flynotes.refresh_assets"
    bl_label = "刷新本地素材"

    def execute(self, context):
        root = os.path.expanduser(bpy.path.abspath(prefs(context).assets_root))
        return {'FINISHED'} if _start_asset_refresh(context.scene, root) else {'CANCELLED'}


def _start_asset_refresh(scene, root):
    if background.is_active("assets-scan"):
        return False
    runtime.asset_status = "正在扫描本地素材…"
    known_task_ids = {item.path: item.task_id for item in scene.flynotes_assets if item.task_id}

    def success(rows):
        scene.flynotes_assets.clear()
        for path, media_type, size, _modified, digest in rows:
            item = scene.flynotes_assets.add()
            item.path, item.media_type, item.size, item.sha256 = path, media_type, size, digest
            item.task_id = known_task_ids.get(path) or _task_id_from_path(path)
        runtime.asset_preview_queue = [row[0] for row in rows]
        if runtime.asset_preview_queue and not bpy.app.timers.is_registered(load_asset_previews):
            bpy.app.timers.register(load_asset_previews, first_interval=0.05)
        redraw()

    return background.start("assets-scan", lambda: refresh_assets(root), success, report_error)


def _reveal(path):
    if platform.system() == "Darwin":
        subprocess.Popen(["open", path] if os.path.isdir(path) else ["open", "-R", path])
    elif platform.system() == "Windows":
        subprocess.Popen(["explorer", os.path.normpath(path)] if os.path.isdir(path) else ["explorer", "/select,", os.path.normpath(path)])
    else:
        subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])


class FLYNOTES_OT_reveal_file(bpy.types.Operator):
    bl_idname = "flynotes.reveal_file"
    bl_label = "打开所在位置"
    path: bpy.props.StringProperty(subtype='FILE_PATH')

    def execute(self, _context):
        if os.path.exists(self.path):
            _reveal(self.path)
            return {'FINISHED'}
        return {'CANCELLED'}


class FLYNOTES_OT_asset_click(bpy.types.Operator):
    bl_idname = "flynotes.asset_click"
    bl_label = "选择素材"
    index: bpy.props.IntProperty()

    def execute(self, context):
        if not (0 <= self.index < len(context.scene.flynotes_assets)):
            return {'CANCELLED'}
        context.scene.flynotes_asset_index = self.index
        return {'FINISHED'}


class FLYNOTES_OT_open_history(bpy.types.Operator):
    bl_idname = "flynotes.open_history"
    bl_label = "前往官网查看历史任务"

    def execute(self, _context):
        webbrowser.open("https://flynotes.top/")
        return {'FINISHED'}


class FLYNOTES_OT_open_task_center(bpy.types.Operator):
    bl_idname = "flynotes.open_task_center"
    bl_label = "打开任务中心"

    def execute(self, _context):
        try:
            bpy.ops.wm.call_panel(name="FLYNOTES_PT_task_center")
        except Exception as error:
            report_error(error)
            return {'CANCELLED'}
        return {'FINISHED'}


class FLYNOTES_OT_workbench_video(bpy.types.Operator):
    bl_idname = "flynotes.workbench_video"
    bl_label = "生成 Workbench 视频"
    bl_options = {'REGISTER'}

    reencode_only: bpy.props.BoolProperty(default=False, options={'HIDDEN'})

    def _reset_runtime_flags(self):
        self._timer = None
        self._source_scene = None
        self._source_scene_name = ""
        self._source_snapshot = None
        self._selected_camera = None
        self._view_state = None
        self._workbench_scene = None
        self._encode_scene = None
        self._next_frame_index = 0
        self._encode_completed = False
        self._encode_cancelled = False
        self._encoded_writes = 0
        self._encode_job_seen = False
        self._handlers_registered = False
        self._render_display_type = None
        self._windows_before_encoding = set()
        self._finished = False

    @staticmethod
    def _scene_snapshot(scene):
        render = scene.render
        image = render.image_settings
        strips = []
        if scene.sequence_editor:
            collection = sequence_collection(scene.sequence_editor)
            strips = [(strip.name, strip.type, strip.frame_start, strip.frame_final_end, strip.channel) for strip in collection]
        return {
            "pointer": scene.as_pointer(),
            "camera": scene.camera.as_pointer() if scene.camera else 0,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "frame_current": scene.frame_current,
            "fps": render.fps,
            "fps_base": render.fps_base,
            "resolution": (render.resolution_x, render.resolution_y, render.resolution_percentage),
            "filepath": render.filepath,
            "media_type": getattr(image, "media_type", None),
            "file_format": image.file_format,
            "color_mode": image.color_mode,
            "strips": strips,
        }

    def invoke(self, context, _event):
        if context.area.type != 'VIEW_3D' or context.region.type != 'WINDOW':
            self.report({'ERROR'}, "请在 3D 视图里使用")
            return {'CANCELLED'}
        if runtime.local_video_session and runtime.local_video_session.is_active:
            self.report({'ERROR'}, "已有本地视图模式任务正在运行")
            return {'CANCELLED'}
        self._reset_runtime_flags()
        self._source_scene = context.scene
        self._source_scene_name = context.scene.name
        self._source_snapshot = self._scene_snapshot(context.scene)
        try:
            if self.reencode_only:
                session = runtime.local_video_session
                if not session or not session.can_reencode:
                    raise RuntimeError("没有可重新合成的完整视图模式图片序列")
                self._selected_camera = bpy.data.objects.get(session.camera_name)
                session.cancel_requested = False
                session.error = ""
                session.encoded_frames = 0
                session.set_phase("preparing", progress=0.70, message="正在准备重新合成")
            else:
                self._selected_camera = _selected_camera(context)
                if not self._selected_camera:
                    raise RuntimeError("请先选中一个摄像机")
                self._view_state = workbench_frames.snapshot_view(context.space_data)
                if context.scene.flynotes_video_frame_end < context.scene.flynotes_video_frame_start:
                    raise RuntimeError("结束帧不能小于起始帧")
                previous = runtime.local_video_session
                if previous:
                    clear_session_files(previous)
                session = create_session(
                    context.scene,
                    self._selected_camera,
                    context.scene.flynotes_video_frame_start,
                    context.scene.flynotes_video_frame_end,
                    context.scene.flynotes_video_fps,
                )
                runtime.local_video_session = session
                self._workbench_scene = workbench_frames.create_workbench_scene(context.scene, self._selected_camera)
                session.set_phase("preparing", progress=0.02, message="正在创建独立视图模式场景")
            self._timer = context.window_manager.event_timer_add(0.02, window=context.window)
            context.window_manager.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception as error:
            self.report({'ERROR'}, str(error))
            self._cleanup(context)
            return {'CANCELLED'}

    def modal(self, context, event):
        session = runtime.local_video_session
        if not session:
            return self._finish_operator(context, cancelled=True)
        if event.type == 'ESC':
            if session.phase == "encoding":
                session.set_phase("cancelling", message="正在停止 MP4 合成")
                return {'PASS_THROUGH'}
            session.cancel_requested = True
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        try:
            if session.cancel_requested and session.phase != "encoding":
                return self._cancel_before_encoding(context)
            if session.phase == "preparing":
                if self.reencode_only:
                    self._start_encoding(context, session)
                else:
                    session.set_phase("rendering_frames", progress=0.05, message="正在渲染第 1 帧")
            elif session.phase == "rendering_frames":
                self._render_next_frame(context, session)
            elif session.phase in {"encoding", "cancelling"}:
                job_running = bpy.app.is_job_running("RENDER")
                self._encode_job_seen = self._encode_job_seen or job_running
                if self._encode_cancelled:
                    return self._finish_encoding_cancel(context, session)
                if self._encode_completed:
                    return self._finish_encoding_success(context, session)
                if self._encode_job_seen and not job_running:
                    raise RuntimeError("Blender 视频编码意外停止，图片序列已保留")
            return {'RUNNING_MODAL'}
        except Exception as error:
            return self._fail(context, session, error)

    def cancel(self, context):
        session = runtime.local_video_session
        if session and session.phase != "encoding":
            self._cancel_before_encoding(context)

    def _render_next_frame(self, context, session):
        if self._next_frame_index >= session.frame_count:
            session.width, session.height = self._even_frame_size(session.frame_paths[0])
            self._start_encoding(context, session)
            return
        source_frame = session.frame_start + self._next_frame_index
        target = workbench_frames.frame_path(session, self._next_frame_index)
        workbench_frames.render_frame(
            context,
            self._workbench_scene,
            source_frame,
            target,
            camera=self._selected_camera,
            view_state=self._view_state,
        )
        session.frame_paths.append(target)
        session.rendered_frames = len(session.frame_paths)
        self._next_frame_index += 1
        factor = self._next_frame_index / max(1, session.frame_count)
        session.progress = 0.05 + factor * 0.65
        session.message = f"视图模式帧 {self._next_frame_index}/{session.frame_count}"

    def _start_encoding(self, context, session):
        if not session.width or not session.height:
            session.width, session.height = self._even_frame_size(session.frame_paths[0])
        self._encode_scene = vse_encoder.create_encode_scene(session)
        self._encode_completed = False
        self._encode_cancelled = False
        self._encoded_writes = 0
        self._encode_job_seen = False
        self._register_handlers()
        session.set_phase("encoding", progress=0.70, message="正在合成 MP4，按 Esc 可取消")
        self._windows_before_encoding = {
            window.as_pointer() for window in context.window_manager.windows
        }
        self._render_display_type = context.preferences.view.render_display_type
        context.preferences.view.render_display_type = 'WINDOW'
        result = bpy.ops.render.render('INVOKE_DEFAULT', animation=True, scene=self._encode_scene.name)
        if 'RUNNING_MODAL' not in result:
            raise RuntimeError(f"Blender 视频合成没有启动：{result}")

    @staticmethod
    def _even_frame_size(path):
        width, height = workbench_frames.read_frame_size(path)
        return max(2, width - width % 2), max(2, height - height % 2)

    def _on_render_write(self, scene, _depsgraph=None):
        if scene != self._encode_scene:
            return
        self._encoded_writes += 1
        session = runtime.local_video_session
        if session:
            session.encoded_frames = min(self._encoded_writes, session.frame_count)
            factor = session.encoded_frames / max(1, session.frame_count)
            session.progress = 0.70 + factor * 0.29
            session.message = f"MP4 合成 {session.encoded_frames}/{session.frame_count}"

    def _on_render_complete(self, scene, _depsgraph=None):
        if scene == self._encode_scene:
            self._encode_completed = True

    def _on_render_cancel(self, scene, _depsgraph=None):
        if scene == self._encode_scene:
            self._encode_cancelled = True

    def _register_handlers(self):
        bpy.app.handlers.render_write.append(self._on_render_write)
        bpy.app.handlers.render_complete.append(self._on_render_complete)
        bpy.app.handlers.render_cancel.append(self._on_render_cancel)
        self._handlers_registered = True

    def _remove_handlers(self):
        if not self._handlers_registered:
            return
        for collection, callback in (
            (bpy.app.handlers.render_write, self._on_render_write),
            (bpy.app.handlers.render_complete, self._on_render_complete),
            (bpy.app.handlers.render_cancel, self._on_render_cancel),
        ):
            if callback in collection:
                collection.remove(callback)
        self._handlers_registered = False

    def _finish_encoding_success(self, context, session):
        path = vse_encoder.validate_output(session)
        self._remove_handlers()
        vse_encoder.remove_encode_scene(self._encode_scene)
        self._encode_scene = None
        workbench_frames.remove_workbench_scene(self._workbench_scene)
        self._workbench_scene = None
        clear_frame_files(session)
        self._source_scene.flynotes_video_use_workbench = True
        session.set_phase("ready", progress=1.0, message="MP4 已就绪，点击 AI 渲染后才会上传")
        self.report({'INFO'}, "视图模式 MP4 已生成")
        return self._finish_operator(context)

    def _finish_encoding_cancel(self, context, session):
        vse_encoder.delete_outputs(session.output_path)
        session.set_phase("encode_cancelled", progress=0.70, message="图片序列已保留，可仅重新合成")
        self._cleanup(context)
        return self._finish_operator(context, cancelled=True)

    def _cancel_before_encoding(self, context):
        session = runtime.local_video_session
        if session:
            clear_frame_files(session)
            session.set_phase("frame_cancelled", progress=0.0, message="本地视图模式渲染已取消")
        self._cleanup(context)
        return self._finish_operator(context, cancelled=True)

    def _fail(self, context, session, error):
        message = str(error)
        if session.phase in {"encoding", "cancelling"}:
            vse_encoder.delete_outputs(session.output_path)
            session.set_phase("encode_failed", progress=0.70, message="图片序列已保留，可仅重新合成", error=message)
        else:
            clear_frame_files(session)
            session.set_phase("frame_failed", progress=0.0, error=message)
        self.report({'ERROR'}, message)
        self._cleanup(context)
        return self._finish_operator(context, cancelled=True)

    def _cleanup(self, context):
        self._remove_handlers()
        vse_encoder.remove_encode_scene(self._encode_scene)
        self._encode_scene = None
        workbench_frames.remove_workbench_scene(self._workbench_scene)
        self._workbench_scene = None
        self._close_render_windows(context)
        if self._render_display_type is not None:
            try:
                context.preferences.view.render_display_type = self._render_display_type
            finally:
                self._render_display_type = None
        if self._source_scene and self._source_scene.name in bpy.data.scenes and self._source_snapshot:
            current = self._scene_snapshot(self._source_scene)
            if current != self._source_snapshot:
                runtime.last_error = "本地视图模式任务检测到用户 Scene 状态变化"

    def _close_render_windows(self, context):
        if not self._windows_before_encoding:
            return
        for window in list(context.window_manager.windows):
            if window.as_pointer() in self._windows_before_encoding:
                continue
            if not any(area.type == 'IMAGE_EDITOR' for area in window.screen.areas):
                continue
            try:
                with context.temp_override(window=window):
                    bpy.ops.wm.window_close()
            except (ReferenceError, RuntimeError):
                pass
        self._windows_before_encoding.clear()

    def _finish_operator(self, context, cancelled=False):
        if self._finished:
            return {'CANCELLED'} if cancelled else {'FINISHED'}
        self._finished = True
        self._cleanup(context)
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        for area in context.screen.areas if context.screen else []:
            area.tag_redraw()
        return {'CANCELLED'} if cancelled else {'FINISHED'}


class FLYNOTES_OT_cancel_local_video(bpy.types.Operator):
    bl_idname = "flynotes.cancel_local_video"
    bl_label = "取消本地视图模式任务"

    def execute(self, _context):
        session = runtime.local_video_session
        if not session or not session.is_active:
            return {'CANCELLED'}
        if session.phase in {"encoding", "cancelling"}:
            self.report({'INFO'}, "MP4 合成阶段请按 Esc 取消")
            return {'CANCELLED'}
        session.cancel_requested = True
        session.message = "正在取消"
        return {'FINISHED'}


class FLYNOTES_OT_clear_local_video(bpy.types.Operator):
    bl_idname = "flynotes.clear_local_video"
    bl_label = "清理本地视图模式任务"

    def execute(self, context):
        session = runtime.local_video_session
        if session and session.is_active:
            self.report({'ERROR'}, "请先取消正在运行的本地任务")
            return {'CANCELLED'}
        clear_session_files(session)
        runtime.local_video_session = None
        context.scene.flynotes_video_use_workbench = False
        for area in context.screen.areas if context.screen else []:
            area.tag_redraw()
        return {'FINISHED'}


class FLYNOTES_OT_open_local_video(bpy.types.Operator):
    bl_idname = "flynotes.open_local_video"
    bl_label = "播放本地视图模式视频"

    def execute(self, _context):
        session = runtime.local_video_session
        path = os.path.abspath(session.output_path) if session and session.output_path else ""
        if not path or not os.path.isfile(path):
            self.report({'ERROR'}, "MP4 文件不存在")
            return {'CANCELLED'}
        if platform.system() == "Darwin":
            subprocess.Popen(["open", path])
        elif platform.system() == "Windows":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])
        return {'FINISHED'}


class FLYNOTES_OT_save_local_video(bpy.types.Operator, ExportHelper):
    bl_idname = "flynotes.save_local_video"
    bl_label = "另存本地视图模式视频"
    filename_ext = ".mp4"
    filter_glob: bpy.props.StringProperty(default="*.mp4", options={'HIDDEN'})

    def invoke(self, context, event):
        session = runtime.local_video_session
        if not session or not session.output_path or not os.path.isfile(session.output_path):
            self.report({'ERROR'}, "MP4 文件不存在")
            return {'CANCELLED'}
        self.filepath = os.path.join(os.path.expanduser("~/Movies"), "flynotes_workbench.mp4")
        return ExportHelper.invoke(self, context, event)

    def execute(self, _context):
        session = runtime.local_video_session
        source = os.path.abspath(session.output_path) if session and session.output_path else ""
        if not source or not os.path.isfile(source):
            self.report({'ERROR'}, "MP4 文件不存在")
            return {'CANCELLED'}
        target = os.path.abspath(bpy.path.abspath(self.filepath))
        if not target.lower().endswith(".mp4"):
            target += ".mp4"
        if os.path.normcase(source) == os.path.normcase(target):
            self.report({'INFO'}, "该位置就是当前 MP4")
            return {'FINISHED'}
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        self.report({'INFO'}, "视频已保存")
        return {'FINISHED'}


CLASSES = (
    FLYNOTES_OT_login, FLYNOTES_OT_verify, FLYNOTES_OT_resume, FLYNOTES_OT_logout, FLYNOTES_OT_update_config,
    FLYNOTES_OT_rollback_config, FLYNOTES_OT_test_local_agent, FLYNOTES_OT_reset_local_agent,
    FLYNOTES_OT_generate, FLYNOTES_OT_job_action,
    FLYNOTES_OT_edit_prompt, FLYNOTES_OT_prompt_clipboard, FLYNOTES_OT_copy_text,
    FLYNOTES_OT_choose_files, FLYNOTES_OT_remove_input, FLYNOTES_OT_open_input,
    FLYNOTES_OT_save_input, FLYNOTES_OT_camera_input,
    FLYNOTES_OT_refresh_assets, FLYNOTES_OT_reveal_file,
    FLYNOTES_OT_asset_click, FLYNOTES_OT_open_history, FLYNOTES_OT_open_task_center, FLYNOTES_OT_workbench_video,
    FLYNOTES_OT_cancel_local_video, FLYNOTES_OT_clear_local_video,
    FLYNOTES_OT_open_local_video, FLYNOTES_OT_save_local_video,
)
