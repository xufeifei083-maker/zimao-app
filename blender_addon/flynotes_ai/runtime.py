import os
import shutil
import tempfile


access_token = ""
pending_device_code = ""
pending_started_at = 0.0
last_error = ""
local_video_session = None
session_jobs = []
network_status = ""
connection_status = "disconnected"
connection_latency_ms = None
job_poll_failure_count = 0
job_poll_retry_at = 0.0
last_auth_refresh_at = 0.0
generation_status = {"image": "", "video": ""}
generation_message = {"image": "", "video": ""}
last_submitted_jobs = {"image": "", "video": ""}
download_progress = {}
asset_status = ""
asset_preview_queue = []
camera_temp_files = []
CAMERA_TEMP_PREFIXES = ("flynotes_camera_view_", "flynotes_camera_white_")


def clear_camera_files(paths=None):
    """Delete only Flynotes-owned camera capture folders from the system temp directory."""
    targets = list(paths if paths is not None else camera_temp_files)
    remove_folders = paths is None
    temp_root = os.path.realpath(tempfile.gettempdir())
    for path in targets:
        folder = os.path.realpath(os.path.dirname(path))
        if (
            any(os.path.basename(folder).startswith(prefix) for prefix in CAMERA_TEMP_PREFIXES)
            and os.path.commonpath([temp_root, folder]) == temp_root
        ):
            if remove_folders:
                shutil.rmtree(folder, ignore_errors=True)
            else:
                try:
                    os.remove(path)
                except FileNotFoundError:
                    pass
                try:
                    os.rmdir(folder)
                except OSError:
                    pass
    camera_temp_files[:] = [path for path in camera_temp_files if path not in targets]
