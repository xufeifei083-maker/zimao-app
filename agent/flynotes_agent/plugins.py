from __future__ import annotations

import ast
import base64
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any
import zipfile

import httpx

from .config import AgentConfig
from .schemas import BlenderHeartbeatRequest, PluginStatusResponse


class PluginUpdateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _version_tuple(value: str | None) -> tuple[int, ...]:
    if not value:
        return ()
    try:
        return tuple(int(part) for part in value.lstrip("v").split("."))
    except ValueError:
        return ()


def _addon_version(addon_path: Path) -> str | None:
    candidates = [addon_path / "__init__.py"]
    pointer = addon_path / "current.json"
    if pointer.is_file():
        try:
            version = json.loads(pointer.read_text(encoding="utf-8"))["version"]
            candidates.insert(0, addon_path / "versions" / f"v{version.replace('.', '_')}" / "__init__.py")
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            pass
    for source in candidates:
        if not source.is_file():
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "bl_info"
                    for target in node.targets
                ):
                    value = ast.literal_eval(node.value)
                    version = value.get("version")
                    if isinstance(version, tuple):
                        return ".".join(str(part) for part in version)
        except (OSError, SyntaxError, ValueError):
            continue
    return None


class PluginManager:
    """Discover, verify, stage and atomically activate the Blender add-on."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._heartbeats: dict[str, tuple[BlenderHeartbeatRequest, datetime]] = {}
        self._state: dict[str, Any] = {}

    def initialize(self) -> None:
        self.config.plugin_path.mkdir(parents=True, exist_ok=True)
        if self.config.plugin_state_path.is_file():
            try:
                self._state = json.loads(
                    self.config.plugin_state_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                self._state = {}

    def _save(self) -> None:
        temporary = self.config.plugin_state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self.config.plugin_state_path)

    @staticmethod
    def _installations() -> list[tuple[str, Path]]:
        roaming = Path(os.environ.get("APPDATA", str(Path.home())))
        blender_root = roaming / "Blender Foundation" / "Blender"
        found: list[tuple[str, Path]] = []
        if blender_root.is_dir():
            for version_root in blender_root.iterdir():
                addon = version_root / "scripts" / "addons" / "flynotes_ai"
                if addon.is_dir():
                    found.append((version_root.name, addon))
        return sorted(found, key=lambda item: _version_tuple(item[0]), reverse=True)

    def statuses(self) -> list[PluginStatusResponse]:
        manifest = self._state.get("manifest") or {}
        available = manifest.get("version")
        checked = self._state.get("lastCheckedAt")
        installations = self._installations()
        if not installations:
            installations = [("5.0", Path())]
        result = []
        for blender_version, path in installations:
            installed = _addon_version(path) if path else None
            staged = self._state.get("stagedVersion")
            state = "not-installed"
            if installed:
                state = "update-available" if _version_tuple(available) > _version_tuple(installed) else "installed"
            if staged:
                state = "staged"
            result.append(
                PluginStatusResponse(
                    id=f"flynotes-ai-blender:{blender_version}",
                    repository=self.config.plugin_repository,
                    configured=bool(self.config.plugin_repository and self.config.plugin_public_key),
                    blenderVersion=blender_version,
                    installedPath=str(path) if path else "",
                    installedVersion=installed,
                    availableVersion=available,
                    stagedVersion=staged,
                    updateAvailable=_version_tuple(available) > _version_tuple(installed),
                    state=state,
                    lastCheckedAt=datetime.fromisoformat(checked) if checked else None,
                    error=self._state.get("error", ""),
                )
            )
        return result

    async def check_updates(self) -> list[PluginStatusResponse]:
        repository = self.config.plugin_repository.strip().strip("/")
        if not repository:
            self._state["error"] = "尚未配置 Blender 插件 GitHub 仓库"
            self._state["lastCheckedAt"] = datetime.now(UTC).isoformat()
            self._save()
            return self.statuses()
        url = f"https://api.github.com/repos/{repository}/releases/latest"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Flynotes-Local-Agent"},
            )
            response.raise_for_status()
            release = response.json()
            asset = next(
                (item for item in release.get("assets", []) if item.get("name") == "flynotes-plugin-release.json"),
                None,
            )
            if not asset:
                raise PluginUpdateError("RELEASE_MANIFEST_MISSING", "GitHub Release 缺少 flynotes-plugin-release.json")
            manifest_response = await client.get(asset["browser_download_url"])
            manifest_response.raise_for_status()
            manifest = manifest_response.json()
        self._validate_manifest(manifest)
        self._state.update(
            manifest=manifest,
            lastCheckedAt=datetime.now(UTC).isoformat(),
            error="",
        )
        self._save()
        return self.statuses()

    @staticmethod
    def _validate_manifest(manifest: dict[str, Any]) -> None:
        if manifest.get("schemaVersion") != 1 or manifest.get("pluginId") != "flynotes-ai-blender":
            raise PluginUpdateError("INVALID_RELEASE_MANIFEST", "插件更新清单格式不受支持")
        package = manifest.get("package") or {}
        if not manifest.get("version") or not package.get("url") or not package.get("sha256") or not package.get("signature"):
            raise PluginUpdateError("INVALID_RELEASE_MANIFEST", "插件更新清单缺少版本、下载地址、哈希或签名")

    def _verify_signature(self, digest: str, signature: str) -> None:
        if not self.config.plugin_public_key:
            raise PluginUpdateError("SIGNING_KEY_MISSING", "尚未配置插件 Ed25519 公钥")
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            public_key = Ed25519PublicKey.from_public_bytes(
                base64.b64decode(self.config.plugin_public_key)
            )
            public_key.verify(base64.b64decode(signature), digest.encode("ascii"))
        except PluginUpdateError:
            raise
        except Exception as error:
            raise PluginUpdateError("SIGNATURE_INVALID", "插件包签名验证失败") from error

    async def stage(self, manifest: dict[str, Any] | None = None) -> list[PluginStatusResponse]:
        resolved = manifest or self._state.get("manifest")
        if not isinstance(resolved, dict):
            raise PluginUpdateError("UPDATE_NOT_CHECKED", "请先手动检查插件更新")
        self._validate_manifest(resolved)
        package = resolved["package"]
        async with httpx.AsyncClient(timeout=300, follow_redirects=True) as client:
            response = await client.get(package["url"])
            response.raise_for_status()
            payload = response.content
        digest = hashlib.sha256(payload).hexdigest()
        if digest.lower() != str(package["sha256"]).lower():
            raise PluginUpdateError("HASH_MISMATCH", "插件包 SHA256 校验失败")
        self._verify_signature(digest, package["signature"])
        version = str(resolved["version"])
        target = self.config.plugin_path / "staged" / f"v{version.replace('.', '_')}"
        with tempfile.TemporaryDirectory(dir=self.config.plugin_path) as temporary:
            archive = Path(temporary) / "plugin.zip"
            archive.write_bytes(payload)
            extracted = Path(temporary) / "extracted"
            extracted.mkdir()
            with zipfile.ZipFile(archive) as bundle:
                for member in bundle.infolist():
                    destination = (extracted / member.filename).resolve()
                    try:
                        destination.relative_to(extracted.resolve())
                    except ValueError as error:
                        raise PluginUpdateError("UNSAFE_ARCHIVE", "插件包包含路径穿越条目") from error
                bundle.extractall(extracted)
            source = extracted / "flynotes_ai"
            if not source.is_dir():
                candidates = [item for item in extracted.rglob("flynotes_ai") if item.is_dir()]
                source = candidates[0] if len(candidates) == 1 else source
            if not source.is_dir() or _addon_version(source) != version:
                raise PluginUpdateError("PACKAGE_VERSION_MISMATCH", "插件包版本与更新清单不一致")
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target)
        self._state.update(manifest=resolved, stagedVersion=version, error="")
        self._save()
        return self.statuses()

    def heartbeat(self, request: BlenderHeartbeatRequest) -> None:
        self._heartbeats[request.instanceId] = (request, datetime.now(UTC))

    def _busy_instances(self) -> list[BlenderHeartbeatRequest]:
        cutoff = datetime.now(UTC) - timedelta(seconds=15)
        return [request for request, seen in self._heartbeats.values() if seen >= cutoff and request.state == "busy"]

    def apply(self, plugin_id: str) -> list[PluginStatusResponse]:
        if self._busy_instances():
            raise PluginUpdateError("PLUGIN_BUSY", "Blender 正在生成、渲染或编码，更新已暂缓")
        status = next((item for item in self.statuses() if item.id == plugin_id), None)
        if not status or not status.installedPath:
            raise PluginUpdateError("PLUGIN_NOT_INSTALLED", "未找到目标 Blender 插件目录")
        version = self._state.get("stagedVersion")
        staged = self.config.plugin_path / "staged" / f"v{str(version).replace('.', '_')}"
        if not version or not staged.is_dir():
            raise PluginUpdateError("UPDATE_NOT_STAGED", "没有已验证的待安装版本")
        addon = Path(status.installedPath).resolve()
        expected_root = Path(os.environ.get("APPDATA", str(Path.home()))).resolve()
        try:
            addon.relative_to(expected_root)
        except ValueError as error:
            raise PluginUpdateError("UNSAFE_INSTALL_PATH", "插件安装路径不在当前用户 Blender 目录") from error
        backup = self.config.plugin_path / "backups" / status.blenderVersion / f"v{(status.installedVersion or 'unknown').replace('.', '_')}"
        loader = Path(__file__).parent / "plugin_loader" / "flynotes_ai"
        version_target = addon / "versions" / f"v{version.replace('.', '_')}"
        try:
            if addon.is_dir() and not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(addon, backup)
            addon.mkdir(parents=True, exist_ok=True)
            version_target.parent.mkdir(parents=True, exist_ok=True)
            if version_target.exists():
                shutil.rmtree(version_target)
            shutil.copytree(staged, version_target)
            shutil.copy2(loader / "__init__.py", addon / "__init__.py")
            pointer = addon / "current.json"
            temporary = pointer.with_suffix(".tmp")
            temporary.write_text(json.dumps({"version": version}, indent=2), encoding="utf-8")
            os.replace(temporary, pointer)
        except Exception as error:
            if backup.is_dir():
                for source in backup.rglob("*"):
                    relative = source.relative_to(backup)
                    destination = addon / relative
                    if source.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
            raise PluginUpdateError("PLUGIN_UPDATE_FAILED", "插件更新失败，已恢复上一版本") from error
        self._state.update(stagedVersion=None, error="")
        self._save()
        return self.statuses()

    def rollback(self, plugin_id: str) -> list[PluginStatusResponse]:
        status = next((item for item in self.statuses() if item.id == plugin_id), None)
        if not status or not status.installedPath:
            raise PluginUpdateError("PLUGIN_NOT_INSTALLED", "未找到目标 Blender 插件目录")
        backups = self.config.plugin_path / "backups" / status.blenderVersion
        candidates = sorted((item for item in backups.glob("v*") if item.is_dir()), reverse=True) if backups.is_dir() else []
        if not candidates:
            raise PluginUpdateError("ROLLBACK_NOT_AVAILABLE", "没有可回滚的插件版本")
        addon = Path(status.installedPath)
        source = candidates[0]
        for item in source.rglob("*"):
            relative = item.relative_to(source)
            destination = addon / relative
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)
        return self.statuses()
