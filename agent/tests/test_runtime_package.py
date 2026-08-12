from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from flynotes_agent.config import AgentConfig
from flynotes_agent.downloads import ResumableDownloader
from flynotes_agent.runtime_package import RuntimePackageManager
from flynotes_agent.schemas import RuntimePackageState


def _runtime_archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr("main.py", "# fixed runtime")
        bundle.writestr("python_runtime/python.exe", b"test-python")
    return output.getvalue()


@pytest.mark.asyncio
async def test_runtime_package_downloads_verifies_and_activates(config, tmp_path: Path) -> None:
    archive = _runtime_archive()
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    runtime_id = "win-nvidia-test-1"
    manifest = {
        "schemaVersion": 1,
        "runtimeId": runtime_id,
        "pythonVersion": "3.12.12",
        "comfyuiCommit": "a" * 40,
        "pytorchVersion": "2.12.1+cu130",
        "cudaVersion": "13.0",
        "ffmpegVersion": "test",
        "minimumDriver": "580.00",
        "archiveSize": len(archive),
        "archiveSha256": hashlib.sha256(archive).hexdigest(),
        "requiredFiles": ["main.py", "python_runtime/python.exe"],
        "parts": [
            {
                "name": "runtime-win-nvidia-test-1.part01",
                "url": "https://runtime.test/runtime.part01",
                "size": len(archive),
                "sha256": hashlib.sha256(archive).hexdigest(),
            }
        ],
    }
    payload = json.dumps(manifest, separators=(",", ":")).encode()
    signature = base64.b64encode(private_key.sign(payload))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("runtime-manifest.json.sig"):
            return httpx.Response(200, content=signature)
        if request.url.path.endswith("runtime-manifest.json"):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, content=archive)

    resolved = AgentConfig(
        comfy_root=tmp_path / "missing-runtime",
        data_root=tmp_path / "data",
        runtime_id=runtime_id,
        runtime_manifest_url="https://runtime.test/runtime-manifest.json",
        runtime_public_key=public_key,
    )
    resolved.ensure_directories()
    transport = httpx.MockTransport(handler)
    manager = RuntimePackageManager(
        resolved,
        transport=transport,
        downloader=ResumableDownloader(transport=transport, chunk_size=7),
    )

    status = await manager.install()

    assert status.state == RuntimePackageState.READY
    assert resolved.comfy_root == resolved.runtimes_path / runtime_id
    assert (resolved.comfy_root / "main.py").is_file()
    assert (resolved.comfy_root / "python_runtime" / "python.exe").is_file()
    pointer = json.loads(resolved.runtime_pointer_path.read_text(encoding="utf-8"))
    assert pointer["runtimeId"] == runtime_id


def test_runtime_status_reports_existing_runtime_ready(config) -> None:
    manager = RuntimePackageManager(config)

    assert manager.status().state == RuntimePackageState.READY
