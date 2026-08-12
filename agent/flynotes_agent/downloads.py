from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import httpx


class DownloadError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DownloadPaused(DownloadError):
    def __init__(self) -> None:
        super().__init__("DOWNLOAD_PAUSED", "下载已暂停")


class ResumableDownloader:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
        chunk_size: int = 1024 * 1024,
    ) -> None:
        self.transport = transport
        self.timeout = timeout
        self.chunk_size = chunk_size

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def download(
        self,
        url: str,
        target: Path,
        *,
        expected_size: int | None = None,
        expected_sha256: str = "",
        progress: Callable[[int, int | None], None] | None = None,
        should_pause: Callable[[], bool] | None = None,
    ) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f"{target.name}.partial")
        offset = partial.stat().st_size if partial.is_file() else 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        timeout = httpx.Timeout(self.timeout, connect=min(self.timeout, 30))
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout,
                transport=self.transport,
            ) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    append = offset > 0 and response.status_code == 206
                    if offset and not append:
                        offset = 0
                    mode = "ab" if append else "wb"
                    content_length = response.headers.get("content-length")
                    total = expected_size or (
                        offset + int(content_length) if content_length else None
                    )
                    written = offset
                    with partial.open(mode) as stream:
                        async for chunk in response.aiter_bytes(self.chunk_size):
                            if should_pause and should_pause():
                                raise DownloadPaused()
                            stream.write(chunk)
                            written += len(chunk)
                            if progress:
                                progress(written, total)
        except DownloadPaused:
            raise
        except httpx.HTTPError as error:
            raise DownloadError("DOWNLOAD_FAILED", str(error)) from error

        size = partial.stat().st_size
        if expected_size is not None and size != expected_size:
            raise DownloadError(
                "DOWNLOAD_SIZE_MISMATCH",
                f"下载大小不一致：预期 {expected_size}，实际 {size}",
            )
        if expected_sha256:
            actual = self._sha256(partial)
            if actual.casefold() != expected_sha256.casefold():
                raise DownloadError(
                    "HASH_MISMATCH",
                    f"SHA256 不一致：预期 {expected_sha256}，实际 {actual}",
                )
        partial.replace(target)
        return target


def huggingface_file_url(repo: str, revision: str, filename: str) -> str:
    safe_path = "/".join(part for part in Path(filename).parts if part not in {"", "."})
    if not repo or not re_full_commit(revision) or not safe_path or ".." in Path(filename).parts:
        raise ValueError("Hugging Face 文件定位信息无效")
    return f"https://huggingface.co/{repo}/resolve/{revision}/{safe_path}?download=true"


def re_full_commit(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)
