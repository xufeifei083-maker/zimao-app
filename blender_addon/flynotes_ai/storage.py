import hashlib
import os
import sqlite3
import subprocess
import sys
import uuid

from .compat import ensure_sequence_collection


if sys.platform.startswith("win"):
    import ctypes
    from ctypes import wintypes

    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168
    _LPBYTE = ctypes.POINTER(ctypes.c_ubyte)

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", _LPBYTE),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _PCREDENTIAL = ctypes.POINTER(_CREDENTIAL)
    _advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    _advapi32.CredWriteW.argtypes = [_PCREDENTIAL, wintypes.DWORD]
    _advapi32.CredWriteW.restype = wintypes.BOOL
    _advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_PCREDENTIAL)]
    _advapi32.CredReadW.restype = wintypes.BOOL
    _advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _advapi32.CredDeleteW.restype = wintypes.BOOL
    _advapi32.CredFree.argtypes = [ctypes.c_void_p]
    _advapi32.CredFree.restype = None


def installation_id():
    path = os.path.join(os.path.dirname(__file__), ".installation_id")
    try:
        with open(path, "r", encoding="utf-8") as source:
            value = source.read().strip()
            if value:
                return value
    except OSError:
        pass
    value = str(uuid.uuid4())
    try:
        with open(path, "w", encoding="utf-8") as output:
            output.write(value)
    except OSError:
        pass
    return value


def _service(session_id):
    return f"flynotes-blender:{session_id}"


def save_device_secret(session_id, secret):
    if sys.platform == "darwin":
        subprocess.run(["security", "add-generic-password", "-U", "-a", "flynotes", "-s", _service(session_id), "-w", secret], check=True, capture_output=True)
        return
    if sys.platform.startswith("win"):
        blob = secret.encode("utf-8")
        target = _service(session_id)
        target_buffer = ctypes.create_unicode_buffer(target)
        username_buffer = ctypes.create_unicode_buffer("flynotes")
        blob_buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = _CREDENTIAL(
            Type=_CRED_TYPE_GENERIC,
            TargetName=ctypes.cast(target_buffer, wintypes.LPWSTR),
            CredentialBlobSize=len(blob),
            CredentialBlob=ctypes.cast(blob_buffer, _LPBYTE),
            Persist=_CRED_PERSIST_LOCAL_MACHINE,
            UserName=ctypes.cast(username_buffer, wintypes.LPWSTR),
        )
        if not _advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise OSError(ctypes.get_last_error(), "Windows 凭据管理器保存失败")
        return
    raise RuntimeError("当前系统暂无安全密钥存储，请保持登录页打开")


def load_device_secret(session_id):
    if not session_id:
        return ""
    if sys.platform == "darwin":
        result = subprocess.run(["security", "find-generic-password", "-a", "flynotes", "-s", _service(session_id), "-w"], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else ""
    if sys.platform.startswith("win"):
        credential = _PCREDENTIAL()
        if not _advapi32.CredReadW(_service(session_id), _CRED_TYPE_GENERIC, 0, ctypes.byref(credential)):
            return ""
        try:
            blob = ctypes.string_at(credential.contents.CredentialBlob, credential.contents.CredentialBlobSize)
            return blob.decode("utf-8")
        finally:
            _advapi32.CredFree(credential)
    return ""


def remove_device_secret(session_id):
    if not session_id:
        return
    if sys.platform == "darwin":
        subprocess.run(["security", "delete-generic-password", "-a", "flynotes", "-s", _service(session_id)], capture_output=True)
    elif sys.platform.startswith("win"):
        if not _advapi32.CredDeleteW(_service(session_id), _CRED_TYPE_GENERIC, 0):
            error_code = ctypes.get_last_error()
            if error_code != _ERROR_NOT_FOUND:
                raise OSError(error_code, "Windows 凭据管理器删除失败")


def refresh_assets(root):
    os.makedirs(root, exist_ok=True)
    db_path = os.path.join(root, ".flynotes_assets.sqlite3")
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE IF NOT EXISTS assets(path TEXT PRIMARY KEY, media_type TEXT, size INTEGER, modified REAL, sha256 TEXT)")
    found = []
    allowed = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".mp4": "video", ".mov": "video", ".webm": "video", ".mkv": "video"}
    for folder, folders, files in os.walk(root):
        folders[:] = [name for name in folders if not name.startswith(".flynotes_")]
        for name in files:
            path = os.path.join(folder, name)
            media_type = allowed.get(os.path.splitext(name)[1].lower())
            if not media_type:
                continue
            stat = os.stat(path)
            row = connection.execute("SELECT size, modified, sha256 FROM assets WHERE path=?", (path,)).fetchone()
            digest = row[2] if row and row[0] == stat.st_size and row[1] == stat.st_mtime else _file_hash(path)
            connection.execute("INSERT OR REPLACE INTO assets(path, media_type, size, modified, sha256) VALUES(?,?,?,?,?)", (path, media_type, stat.st_size, stat.st_mtime, digest))
            found.append(path)
    if found:
        placeholders = ",".join("?" for _ in found)
        connection.execute(f"DELETE FROM assets WHERE path NOT IN ({placeholders})", found)
    else:
        connection.execute("DELETE FROM assets")
    connection.commit()
    rows = connection.execute("SELECT path, media_type, size, modified, sha256 FROM assets ORDER BY modified DESC").fetchall()
    connection.close()
    return rows


def ensure_video_thumbnail(video_path, root):
    import bpy
    folder = os.path.join(root, ".flynotes_thumbnails")
    os.makedirs(folder, exist_ok=True)
    name = hashlib.sha256(video_path.encode("utf-8")).hexdigest()[:24] + ".png"
    target = os.path.join(folder, name)
    if os.path.isfile(target) and os.path.getmtime(target) >= os.path.getmtime(video_path):
        return target
    clip = bpy.data.movieclips.load(video_path, check_existing=False)
    scene = bpy.data.scenes.new("Flynotes Video Thumbnail")
    try:
        width, height = clip.size
        scale = min(1.0, 512 / max(1, width, height))
        scene.render.resolution_x = max(2, round(width * scale))
        scene.render.resolution_y = max(2, round(height * scale))
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = 'PNG'
        scene.render.filepath = target
        strips = ensure_sequence_collection(scene)
        strips.new_movie("Flynotes source", video_path, channel=1, frame_start=1)
        scene.frame_set(1)
        bpy.ops.render.render(write_still=True, scene=scene.name)
    finally:
        bpy.data.scenes.remove(scene)
        bpy.data.movieclips.remove(clip)
    return target if os.path.isfile(target) else ""


def _file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
