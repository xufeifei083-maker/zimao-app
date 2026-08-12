import json
import http.client
import os
import platform
import urllib.error
import urllib.parse
import urllib.request


CLIENT_VERSION = "1.4.0"


class ApiError(RuntimeError):
    pass


def _client_headers():
    try:
        import bpy
        blender_version = bpy.app.version_string
    except Exception:
        blender_version = "unknown"
    return {
        "Accept": "application/json",
        "User-Agent": f"Flynotes-Blender/{CLIENT_VERSION} (Blender/{blender_version}; {platform.system()})",
        "X-Flynotes-Client": "blender-plugin",
        "X-Flynotes-Plugin-Version": CLIENT_VERSION,
    }


def _http_error(exc, fallback):
    raw = exc.read().decode("utf-8", errors="replace").strip()
    return _response_error(exc.code, raw, fallback)


def _response_error(status, raw, fallback):
    if status == 403 and ("1010" in raw or "browser" in raw.lower() or "signature" in raw.lower()):
        return ApiError("Flynotes 拒绝了旧版插件请求，请安装最新版插件")
    try:
        detail = json.loads(raw).get("detail")
    except Exception:
        detail = None
    if detail:
        return ApiError(detail)
    return ApiError(f"{fallback} ({status})")


def request_json(base_url, path, method="GET", data=None, token="", timeout=60):
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = _client_headers()
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _http_error(exc, "网络请求失败") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(f"无法连接 Flynotes：{exc}") from exc


def upload_file(base_url, path, file_path, token, timeout=600, progress=None):
    boundary = "----FlynotesBlenderBoundary7MA4YWxk"
    name = os.path.basename(file_path)
    encoded_name = urllib.parse.quote(name)
    prefix = (
        # Starlette's multipart parser does not consistently prefer filename*
        # on every version. Keep the regular filename ASCII-only while still
        # preserving the original extension needed by media loader nodes.
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{encoded_name}\"; filename*=UTF-8''{encoded_name}\r\n"
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    file_size = os.path.getsize(file_path)
    total = len(prefix) + file_size + len(suffix)
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    parsed = urllib.parse.urlsplit(url)
    headers = _client_headers()
    headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(total),
    })
    connection_class = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(parsed.hostname, parsed.port, timeout=timeout)
    try:
        target = parsed.path or "/"
        if parsed.query:
            target += f"?{parsed.query}"
        connection.putrequest("POST", target)
        for key, value in headers.items():
            connection.putheader(key, value)
        connection.endheaders()
        connection.send(prefix)
        sent = 0
        with open(file_path, "rb") as source:
            while chunk := source.read(1024 * 1024):
                connection.send(chunk)
                sent += len(chunk)
                if progress:
                    progress(sent, file_size)
        connection.send(suffix)
        response = connection.getresponse()
        raw = response.read().decode("utf-8", errors="replace")
        if response.status >= 400:
            raise _response_error(response.status, raw, "上传失败")
        return json.loads(raw)
    finally:
        connection.close()


def download_file(url, target, token="", timeout=600, progress=None):
    part = target + ".part"
    headers = _client_headers()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response, open(part, "wb") as output:
            expected = int(response.headers.get("Content-Length") or 0)
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                size += len(chunk)
                if progress:
                    progress(size, expected)
        if expected and size != expected:
            raise ApiError("下载文件不完整")
        os.replace(part, target)
        return size
    finally:
        if os.path.exists(part):
            os.remove(part)


def remote_file_size(url, token="", timeout=60):
    """Read the real remote size with a one-byte range request."""
    headers = _client_headers()
    headers["Range"] = "bytes=0-0"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        content_range = response.headers.get("Content-Range") or ""
        if "/" in content_range:
            total = content_range.rsplit("/", 1)[-1].strip()
            if total.isdigit():
                return int(total)
        length = response.headers.get("Content-Length") or ""
        return int(length) if length.isdigit() else 0
