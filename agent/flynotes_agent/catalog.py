from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .config import AgentConfig
from .schemas import WorkflowCatalogStatusResponse
from .workflows import WorkflowManifest


class CatalogError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CatalogFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CatalogWorkflow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: WorkflowManifest
    workflowFiles: dict[str, CatalogFile]


class WorkflowCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: int = 1
    generatedAt: str
    workflows: list[CatalogWorkflow]


class WorkflowCatalogManager:
    def __init__(
        self,
        config: AgentConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport

    def _read_cache(self) -> dict:
        try:
            value = json.loads(self.config.catalog_cache_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def status(self) -> WorkflowCatalogStatusResponse:
        cached = self._read_cache()
        return WorkflowCatalogStatusResponse(
            configured=bool(
                self.config.workflow_catalog_url
                and self.config.workflow_catalog_public_key
            ),
            url=self.config.workflow_catalog_url,
            workflowCount=len(cached.get("workflows", [])),
            generatedAt=str(cached.get("generatedAt", "")),
            lastSyncedAt=cached.get("lastSyncedAt"),
            errorCode=str(cached.get("errorCode", "")),
            errorMessage=str(cached.get("errorMessage", "")),
        )

    def _verify(self, payload: bytes, signature: bytes) -> None:
        if not self.config.workflow_catalog_public_key:
            raise CatalogError("CATALOG_KEY_MISSING", "尚未配置工作流目录公钥")
        try:
            key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self.config.workflow_catalog_public_key, validate=True)
            )
            key.verify(base64.b64decode(signature.strip(), validate=True), payload)
        except CatalogError:
            raise
        except Exception as error:
            raise CatalogError("CATALOG_SIGNATURE_INVALID", "工作流目录签名验证失败") from error

    @staticmethod
    def _validate_files(workflow: CatalogWorkflow) -> None:
        expected = set(workflow.manifest.modes.values())
        supplied = set(workflow.workflowFiles)
        if expected != supplied:
            raise CatalogError(
                "CATALOG_WORKFLOW_FILES_INVALID",
                f"{workflow.manifest.id} 的工作流文件与 modes 不一致",
            )

    async def refresh(self) -> WorkflowCatalogStatusResponse:
        if not self.config.workflow_catalog_url:
            raise CatalogError("CATALOG_URL_MISSING", "尚未配置工作流目录地址")
        url = self.config.workflow_catalog_url
        try:
            async with httpx.AsyncClient(
                timeout=60, follow_redirects=True, transport=self.transport
            ) as client:
                catalog_response = await client.get(url)
                catalog_response.raise_for_status()
                signature_response = await client.get(f"{url}.sig")
                signature_response.raise_for_status()
                payload = catalog_response.content
                self._verify(payload, signature_response.content)
                catalog = WorkflowCatalog.model_validate_json(payload)
                if catalog.schemaVersion != 1:
                    raise CatalogError("CATALOG_VERSION_UNSUPPORTED", "工作流目录版本不受支持")
                downloaded: list[tuple[CatalogWorkflow, dict[str, bytes]]] = []
                for workflow in catalog.workflows:
                    self._validate_files(workflow)
                    files: dict[str, bytes] = {}
                    for name, resource in workflow.workflowFiles.items():
                        response = await client.get(str(resource.url))
                        response.raise_for_status()
                        content = response.content
                        if len(content) != resource.size:
                            raise CatalogError("WORKFLOW_SIZE_MISMATCH", f"{name} 文件大小不一致")
                        if hashlib.sha256(content).hexdigest() != resource.sha256:
                            raise CatalogError("WORKFLOW_HASH_MISMATCH", f"{name} 文件哈希不一致")
                        files[name] = content
                    downloaded.append((workflow, files))
        except CatalogError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            raise CatalogError("CATALOG_REFRESH_FAILED", str(error)) from error

        for workflow, files in downloaded:
            target = self.config.workflows_path / workflow.manifest.id / workflow.manifest.version
            target.mkdir(parents=True, exist_ok=True)
            for name, content in files.items():
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix + ".tmp")
                temporary.write_bytes(content)
                os.replace(temporary, destination)
            manifest_path = target / "manifest.json"
            temporary_manifest = manifest_path.with_suffix(".tmp")
            temporary_manifest.write_text(
                workflow.manifest.model_dump_json(indent=2), encoding="utf-8"
            )
            os.replace(temporary_manifest, manifest_path)

        cache = catalog.model_dump(mode="json")
        cache["lastSyncedAt"] = datetime.now(UTC).isoformat()
        cache_path = self.config.catalog_cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_cache = cache_path.with_suffix(".tmp")
        temporary_cache.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary_cache, cache_path)
        return self.status()
