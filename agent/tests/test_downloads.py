from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from flynotes_agent.downloads import DownloadError, ResumableDownloader, huggingface_file_url


@pytest.mark.asyncio
async def test_downloads_and_verifies_file(tmp_path: Path) -> None:
    payload = b"zimao-workflow-model"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    target = tmp_path / "model.bin"
    downloader = ResumableDownloader(transport=httpx.MockTransport(handler))
    result = await downloader.download(
        "https://example.invalid/model.bin",
        target,
        expected_size=len(payload),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )

    assert result.read_bytes() == payload
    assert not (tmp_path / "model.bin.partial").exists()


@pytest.mark.asyncio
async def test_resumes_partial_download(tmp_path: Path) -> None:
    payload = b"0123456789"
    target = tmp_path / "model.bin"
    partial = tmp_path / "model.bin.partial"
    partial.write_bytes(payload[:4])
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["range"] = request.headers.get("range")
        return httpx.Response(
            206,
            content=payload[4:],
            headers={"Content-Range": "bytes 4-9/10"},
        )

    downloader = ResumableDownloader(transport=httpx.MockTransport(handler))
    await downloader.download(
        "https://example.invalid/model.bin", target, expected_size=len(payload)
    )

    assert captured["range"] == "bytes=4-"
    assert target.read_bytes() == payload


@pytest.mark.asyncio
async def test_hash_mismatch_keeps_partial_for_diagnostics(tmp_path: Path) -> None:
    downloader = ResumableDownloader(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"corrupt")
        )
    )
    with pytest.raises(DownloadError) as captured:
        await downloader.download(
            "https://example.invalid/model.bin",
            tmp_path / "model.bin",
            expected_sha256="0" * 64,
        )

    assert captured.value.code == "HASH_MISMATCH"
    assert (tmp_path / "model.bin.partial").is_file()


def test_huggingface_url_requires_fixed_commit() -> None:
    with pytest.raises(ValueError):
        huggingface_file_url("Comfy-Org/MiniMax-H3", "main", "vae/model.safetensors")
    assert huggingface_file_url(
        "Comfy-Org/MiniMax-H3", "a" * 40, "vae/model.safetensors"
    ).endswith("/vae/model.safetensors?download=true")
