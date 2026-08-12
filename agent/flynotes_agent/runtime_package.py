from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import time
import zipfile
from pathlib import Path
from typing import Callable

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .config import AgentConfig
from .downloads import DownloadPaused, ResumableDownloader
from .schemas import RuntimePackageState, RuntimePackageStatusResponse


class RuntimePackageError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class RuntimePart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^runtime-.+\.part[0-9]{2}$")
    url: HttpUrl
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuntimeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: int = 1
    runtimeId: str = Field(pattern=r"^win-nvidia-[A-Za-z0-9._-]+$")
    pythonVersion: str
    comfyuiCommit: str = Field(pattern=r"^[0-9a-f]{40}$")
    pytorchVersion: str
    cudaVersion: str
    ffmpegVersion: str
    minimumDriver: str
    archiveSize: int = Field(gt=0)
    archiveSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requiredFiles: list[str] = Field(default_factory=lambda: ["main.py", "python_runtime/python.exe"])
    parts: list[RuntimePart] = Field(min_length=1)


class RuntimePackageManager:
    def __init__(
        self,
        config: AgentConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        downloader: ResumableDownloader | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.downloader = downloader or ResumableDownloader(transport=transport, timeout=300)
        self._status = RuntimePackageStatusResponse(
            runtimeId=config.runtime_id,
            state=(
                RuntimePackageState.READY
                if not config.runtime_validation_errors()
                else RuntimePackageState.NOT_INSTALLED
            ),
            configured=bool(config.runtime_manifest_url and config.runtime_public_key),
            manifestUrl=config.runtime_manifest_url,
            installPath=str(config.comfy_root),
        )

    def status(self) -> RuntimePackageStatusResponse:
        if not self.config.runtime_validation_errors() and self._status.state not in {
            RuntimePackageState.DOWNLOADING,
            RuntimePackageState.VERIFYING,
            RuntimePackageState.INSTALLING,
        }:
            self._status.state = RuntimePackageState.READY
            self._status.installPath = str(self.config.comfy_root)
        return self._status

    def _verify_manifest(self, payload: bytes, signature: bytes) -> RuntimeManifest:
        if not self.config.runtime_public_key:
            raise RuntimePackageError("RUNTIME_KEY_MISSING", "尚未配置 Runtime 签名公钥")
        try:
            key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self.config.runtime_public_key, validate=True)
            )
            key.verify(base64.b64decode(signature.strip(), validate=True), payload)
            manifest = RuntimeManifest.model_validate_json(payload)
        except Exception as error:
            raise RuntimePackageError("RUNTIME_MANIFEST_INVALID", "Runtime 清单或签名验证失败") from error
        if manifest.schemaVersion != 1 or manifest.runtimeId != self.config.runtime_id:
            raise RuntimePackageError("RUNTIME_VERSION_MISMATCH", "Runtime 清单版本与软件要求不一致")
        for relative in manifest.requiredFiles:
            path = Path(relative)
            if path.is_absolute() or ".." in path.parts:
                raise RuntimePackageError("RUNTIME_MANIFEST_INVALID", "Runtime 必需文件路径不安全")
        return manifest

    async def fetch_manifest(self) -> RuntimeManifest:
        if not self.config.runtime_manifest_url:
            raise RuntimePackageError("RUNTIME_MANIFEST_URL_MISSING", "尚未配置 Runtime 下载地址")
        url = httpx.URL(self.config.runtime_manifest_url)
        signature_url = str(url.copy_with(path=f"{url.path}.sig"))
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=60, transport=self.transport
            ) as client:
                manifest_response = await client.get(str(url))
                manifest_response.raise_for_status()
                signature_response = await client.get(signature_url)
                signature_response.raise_for_status()
        except httpx.HTTPError as error:
            raise RuntimePackageError("RUNTIME_MANIFEST_DOWNLOAD_FAILED", str(error)) from error
        return self._verify_manifest(manifest_response.content, signature_response.content)

    @staticmethod
    def _safe_extract(archive: Path, target: Path) -> None:
        target_root = target.resolve()
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                destination = (target / member.filename).resolve()
                try:
                    destination.relative_to(target_root)
                except ValueError as error:
                    raise RuntimePackageError("RUNTIME_ARCHIVE_UNSAFE", member.filename) from error
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise RuntimePackageError("RUNTIME_ARCHIVE_UNSAFE", "Runtime 压缩包不能包含符号链接")
            bundle.extractall(target)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    async def install(
        self,
        *,
        progress: Callable[[int, int], None] | None = None,
        should_pause: Callable[[], bool] | None = None,
    ) -> RuntimePackageStatusResponse:
        if not self.config.runtime_validation_errors():
            return self.status()
        try:
            manifest = await self.fetch_manifest()
            total = sum(part.size for part in manifest.parts)
            required_space = manifest.archiveSize + total + int(manifest.archiveSize * 1.1)
            if shutil.disk_usage(self.config.data_root).free < required_space:
                raise RuntimePackageError("DISK_SPACE_INSUFFICIENT", "安装 Runtime 的磁盘空间不足")
            self._status.state = RuntimePackageState.DOWNLOADING
            self._status.totalBytes = total
            part_paths: list[Path] = []
            completed = 0
            download_root = self.config.runtime_downloads_path / manifest.runtimeId
            for part in manifest.parts:
                target = download_root / part.name
                await self.downloader.download(
                    str(part.url),
                    target,
                    expected_size=part.size,
                    expected_sha256=part.sha256,
                    should_pause=should_pause,
                    progress=lambda current, _part_total, done=completed: self._set_progress(
                        done + current, total, progress
                    ),
                )
                part_paths.append(target)
                completed += part.size
            self._status.state = RuntimePackageState.VERIFYING
            archive = download_root / f"{manifest.runtimeId}.zip"
            temporary_archive = archive.with_suffix(".assembling")
            digest = hashlib.sha256()
            written = 0
            with temporary_archive.open("wb") as output:
                for part_path in part_paths:
                    with part_path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                            output.write(chunk)
                            digest.update(chunk)
                            written += len(chunk)
            if written != manifest.archiveSize or digest.hexdigest() != manifest.archiveSha256:
                raise RuntimePackageError("RUNTIME_ARCHIVE_HASH_MISMATCH", "Runtime 合并包校验失败")
            os.replace(temporary_archive, archive)
            self._status.state = RuntimePackageState.INSTALLING
            target = self.config.runtimes_path / manifest.runtimeId
            staging = self.config.runtimes_path / f".{manifest.runtimeId}.staging-{int(time.time())}"
            staging.mkdir(parents=True, exist_ok=False)
            try:
                self._safe_extract(archive, staging)
                for relative in manifest.requiredFiles:
                    if not (staging / relative).is_file():
                        raise RuntimePackageError("RUNTIME_REQUIRED_FILE_MISSING", relative)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            if target.exists():
                backup = self.config.runtimes_path / f"{manifest.runtimeId}.previous-{int(time.time())}"
                os.replace(target, backup)
            os.replace(staging, target)
            self.config.activate_runtime(manifest.runtimeId, target)
            self._status.state = RuntimePackageState.READY
            self._status.installPath = str(target)
            self._status.errorCode = ""
            self._status.errorMessage = ""
            return self._status
        except DownloadPaused:
            self._status.state = RuntimePackageState.NOT_INSTALLED
            raise
        except RuntimePackageError as error:
            self._status.state = RuntimePackageState.FAILED
            self._status.errorCode = error.code
            self._status.errorMessage = str(error)
            raise

    def _set_progress(
        self,
        current: int,
        total: int,
        callback: Callable[[int, int], None] | None,
    ) -> None:
        self._status.downloadedBytes = current
        self._status.totalBytes = total
        self._status.progressPercent = current / total * 100 if total else 0
        if callback:
            callback(current, total)
