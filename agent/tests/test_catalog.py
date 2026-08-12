from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from flynotes_agent.catalog import CatalogError, WorkflowCatalogManager


def _configured(config, public_key: str):
    return type(config)(
        comfy_root=config.comfy_root,
        data_root=config.data_root,
        workflow_catalog_url="https://catalog.test/catalog.json",
        workflow_catalog_public_key=public_key,
    )


@pytest.mark.asyncio
async def test_signed_catalog_installs_verified_workflow_files(config) -> None:
    workflow_bytes = b'{"1":{"class_type":"TestNode"}}'
    catalog = {
        "schemaVersion": 1,
        "generatedAt": "2026-08-12T00:00:00Z",
        "workflows": [
            {
                "manifest": {
                    "id": "tiny",
                    "version": "1.0.0",
                    "displayName": "Tiny",
                    "modes": {"text": "text.json"},
                },
                "workflowFiles": {
                    "text.json": {
                        "url": "https://catalog.test/text.json",
                        "size": len(workflow_bytes),
                        "sha256": hashlib.sha256(workflow_bytes).hexdigest(),
                    }
                },
            }
        ],
    }
    payload = json.dumps(catalog, separators=(",", ":")).encode()
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    signature = base64.b64encode(private_key.sign(payload))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("catalog.json.sig"):
            return httpx.Response(200, content=signature)
        if request.url.path.endswith("catalog.json"):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, content=workflow_bytes)

    resolved = _configured(config, public_key)
    resolved.ensure_directories()
    manager = WorkflowCatalogManager(resolved, transport=httpx.MockTransport(handler))

    status = await manager.refresh()

    target = resolved.workflows_path / "tiny" / "1.0.0"
    assert status.configured is True
    assert status.workflowCount == 1
    assert (target / "text.json").read_bytes() == workflow_bytes
    assert json.loads((target / "manifest.json").read_text(encoding="utf-8"))["id"] == "tiny"


@pytest.mark.asyncio
async def test_catalog_rejects_invalid_signature(config) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    ).decode()
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"invalid"))
    manager = WorkflowCatalogManager(_configured(config, public_key), transport=transport)

    with pytest.raises(CatalogError) as raised:
        await manager.refresh()

    assert raised.value.code == "CATALOG_SIGNATURE_INVALID"
