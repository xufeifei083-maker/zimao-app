from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import psutil
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .comfy import ComfyClient
from .config import AgentConfig
from .schemas import (
    WorkflowHardwareRequirements,
    WorkflowInstallPlanResponse,
    WorkflowResourceStatus,
    WorkflowState,
    WorkflowStatusResponse,
)
from .system_metrics import read_system_metrics


class WorkflowModelResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    filename: str = ""
    source: str = "huggingface"
    repo: str = ""
    revision: str = ""
    file: str = ""
    installTo: str = ""
    size: int | None = None
    sha256: str = ""
    licenseUrl: str = ""
    gated: bool = False

    @model_validator(mode="after")
    def validate_source_and_path(self) -> "WorkflowModelResource":
        if self.installTo:
            path = Path(self.installTo)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("模型安装路径不安全")
        if self.repo or self.file or self.revision:
            if not (self.repo and self.file and re.fullmatch(r"[0-9a-f]{40}", self.revision)):
                raise ValueError("Hugging Face 模型必须使用仓库、文件和完整 commit hash")
        if self.sha256 and not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("模型 SHA256 格式无效")
        return self

    @property
    def expected_filename(self) -> str:
        return self.filename or Path(self.installTo or self.file).name or self.id


class WorkflowNodeResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = ""
    url: str = ""
    installTo: str = ""
    size: int | None = None
    sha256: str = ""

    @model_validator(mode="after")
    def validate_path_and_hash(self) -> "WorkflowNodeResource":
        if self.installTo:
            path = Path(self.installTo)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("节点安装路径不安全")
        if self.sha256 and not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("节点 SHA256 格式无效")
        return self


class WorkflowManifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 1
    id: str
    version: str
    displayName: str = ""
    name: str = ""
    description: str = ""
    provider: str = "comfyui"
    runtimeVersion: str = ""
    modes: dict[str, str]
    models: list[WorkflowModelResource] = Field(default_factory=list)
    nodes: list[WorkflowNodeResource] = Field(default_factory=list)
    requiredModels: list[str] = Field(default_factory=list)
    requiredNodes: list[str] = Field(default_factory=list)
    requiredNodeClasses: list[str] = Field(default_factory=list)
    hardware: WorkflowHardwareRequirements = Field(
        default_factory=WorkflowHardwareRequirements
    )

    @field_validator("id", "version")
    @classmethod
    def validate_path_segment(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError("工作流 ID 和版本只能包含字母、数字、点、下划线和连字符")
        return value

    @field_validator("modes")
    @classmethod
    def validate_modes(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("工作流至少需要一种模式")
        for filename in value.values():
            safe = Path(filename)
            if safe.is_absolute() or ".." in safe.parts:
                raise ValueError("工作流文件路径不安全")
        return value

    @property
    def title(self) -> str:
        return self.displayName or self.name or self.id

    @property
    def model_resources(self) -> list[WorkflowModelResource]:
        if self.models:
            return self.models
        return [
            WorkflowModelResource(id=name, filename=name)
            for name in self.requiredModels
        ]

    @property
    def node_classes(self) -> list[str]:
        return self.requiredNodeClasses or self.requiredNodes


@dataclass(slots=True)
class InstalledWorkflow:
    manifest: WorkflowManifest
    package_path: Path


def _parse_version(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", value)
    return tuple(int(item) for item in numbers[:4])


def _nvidia_driver_version() -> str:
    command = [
        "nvidia-smi",
        "--query-gpu=driver_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.splitlines()[0].strip() if completed.stdout else ""


class WorkflowManager:
    def __init__(
        self,
        config: AgentConfig,
        *,
        builtin_root: Path | None = None,
        comfy_client: ComfyClient | None = None,
    ) -> None:
        self.config = config
        self.builtin_root = builtin_root or Path(__file__).parent / "workflow_packages"
        self.comfy_client = comfy_client or ComfyClient(config.comfy_base_url)
        self._model_cache: tuple[float, dict[str, Path]] | None = None

    def initialize(self) -> None:
        self.config.workflows_path.mkdir(parents=True, exist_ok=True)
        self.config.models_path.mkdir(parents=True, exist_ok=True)

    def invalidate_resource_cache(self) -> None:
        self._model_cache = None

    @staticmethod
    def _load_manifest(path: Path) -> WorkflowManifest:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return WorkflowManifest.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise ValueError(f"工作流 Manifest 无效：{path}: {error}") from error

    def discover(self) -> list[InstalledWorkflow]:
        found: dict[tuple[str, str], InstalledWorkflow] = {}
        roots = (self.builtin_root, self.config.workflows_path)
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.glob("*/*/manifest.json"):
                manifest = self._load_manifest(path)
                found[(manifest.id, manifest.version)] = InstalledWorkflow(
                    manifest=manifest, package_path=path.parent
                )
        latest: dict[str, InstalledWorkflow] = {}
        for package in found.values():
            current = latest.get(package.manifest.id)
            if current is None or _parse_version(package.manifest.version) > _parse_version(
                current.manifest.version
            ):
                latest[package.manifest.id] = package
        return sorted(latest.values(), key=lambda item: item.manifest.title.lower())

    def get(self, workflow_id: str) -> InstalledWorkflow | None:
        return next(
            (item for item in self.discover() if item.manifest.id == workflow_id),
            None,
        )

    def _model_index(self) -> dict[str, Path]:
        if self._model_cache and time.monotonic() - self._model_cache[0] < 30:
            return self._model_cache[1]
        result: dict[str, Path] = {}
        roots = [self.config.models_path, self.config.comfy_root / "models"]
        for root in roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file():
                    result.setdefault(path.name.casefold(), path)
        self._model_cache = (time.monotonic(), result)
        return result

    @staticmethod
    def _hardware_check(
        requirements: WorkflowHardwareRequirements,
    ) -> tuple[bool, list[str], list[str]]:
        metrics = read_system_metrics()
        errors: list[str] = []
        warnings: list[str] = []
        memory_gb = metrics["memoryTotalBytes"] / (1024**3)
        if memory_gb + 0.1 < requirements.minimumRamGB:
            errors.append(
                f"系统内存 {memory_gb:.1f} GB，最低需要 {requirements.minimumRamGB:g} GB"
            )
        gpus = metrics.get("gpus") or []
        if requirements.gpuVendor.casefold() == "nvidia" and not gpus:
            errors.append("未检测到受支持的 NVIDIA GPU")
        elif gpus:
            vram_gb = max((gpu.get("memoryTotalBytes") or 0) for gpu in gpus) / (1024**3)
            if vram_gb + 0.1 < requirements.minimumVramGB:
                errors.append(
                    f"显存 {vram_gb:.1f} GB，最低需要 {requirements.minimumVramGB:g} GB"
                )
            elif (
                requirements.recommendedVramGB
                and vram_gb + 0.1 < requirements.recommendedVramGB
            ):
                warnings.append("当前显存低于推荐配置，将启用或建议使用低显存模式")
        driver = _nvidia_driver_version()
        if requirements.minimumDriver and driver:
            if _parse_version(driver) < _parse_version(requirements.minimumDriver):
                errors.append(
                    f"NVIDIA 驱动 {driver}，最低需要 {requirements.minimumDriver}"
                )
        elif requirements.minimumDriver and gpus:
            warnings.append("无法读取 NVIDIA 驱动版本")
        return not errors, errors, warnings

    async def inspect(self, *, verify_nodes: bool = True) -> list[WorkflowStatusResponse]:
        packages = self.discover()
        model_index = self._model_index()
        object_info: dict[str, Any] | None = None
        if verify_nodes:
            try:
                object_info = await self.comfy_client.object_info()
            except Exception:  # ComfyUI may legitimately be stopped.
                object_info = None
        return [
            self._inspect_package(package, model_index, object_info)
            for package in packages
        ]

    def _inspect_package(
        self,
        package: InstalledWorkflow,
        model_index: dict[str, Path],
        object_info: dict[str, Any] | None,
    ) -> WorkflowStatusResponse:
        manifest = package.manifest
        compatible, hardware_errors, hardware_warnings = self._hardware_check(
            manifest.hardware
        )
        resources: list[WorkflowResourceStatus] = []
        missing_models: list[str] = []
        download_bytes = 0
        can_install = True
        for model in manifest.model_resources:
            path = model_index.get(model.expected_filename.casefold())
            installed = path is not None
            if not installed:
                missing_models.append(model.expected_filename)
                download_bytes += model.size or 0
                if not (model.repo and model.revision and model.file):
                    can_install = False
            resources.append(
                WorkflowResourceStatus(
                    id=model.id,
                    type="model",
                    installed=installed,
                    size=model.size,
                    path=str(path or ""),
                    message="已安装" if installed else "缺少模型",
                )
            )
        missing_nodes: list[str] = []
        unchecked_nodes: list[str] = []
        if object_info is None:
            unchecked_nodes = list(manifest.node_classes)
        else:
            missing_nodes = [
                name for name in manifest.node_classes if name not in object_info
            ]
            if missing_nodes and not manifest.nodes:
                can_install = False
        if not compatible:
            state = WorkflowState.INCOMPATIBLE
            message = "；".join(hardware_errors)
        elif missing_models or missing_nodes:
            state = WorkflowState.NEEDS_REPAIR
            message = f"缺少 {len(missing_models)} 个模型、{len(missing_nodes)} 个节点"
        elif unchecked_nodes:
            state = WorkflowState.NEEDS_VERIFICATION
            message = "启动 ComfyUI 后可完成节点验证"
        else:
            state = WorkflowState.READY
            message = "工作流可以使用"
        return WorkflowStatusResponse(
            id=manifest.id,
            version=manifest.version,
            displayName=manifest.title,
            description=manifest.description,
            modes=list(manifest.modes),
            state=state,
            statusMessage=message,
            packagePath=str(package.package_path),
            hardware=manifest.hardware,
            hardwareCompatible=compatible,
            hardwareWarnings=hardware_warnings,
            missingModels=missing_models,
            missingNodes=missing_nodes,
            uncheckedNodes=unchecked_nodes,
            resources=resources,
            downloadBytes=download_bytes,
            canInstall=can_install and bool(missing_models),
        )

    async def plan(self, workflow_id: str) -> WorkflowInstallPlanResponse | None:
        workflows = await self.inspect(verify_nodes=True)
        workflow = next((item for item in workflows if item.id == workflow_id), None)
        if workflow is None:
            return None
        missing = [item for item in workflow.resources if not item.installed]
        errors: list[str] = []
        if not workflow.hardwareCompatible:
            errors.append(workflow.statusMessage)
        if missing and not workflow.canInstall:
            errors.append("当前工作流资源尚未配置固定下载来源")
        runtime_errors = self.config.runtime_validation_errors()
        if runtime_errors:
            errors.extend(runtime_errors)
        return WorkflowInstallPlanResponse(
            workflowId=workflow.id,
            workflowVersion=workflow.version,
            state=workflow.state,
            hardwareCompatible=workflow.hardwareCompatible,
            errors=errors,
            warnings=workflow.hardwareWarnings,
            missingResources=missing,
            downloadBytes=workflow.downloadBytes,
            requiredDiskBytes=int(workflow.downloadBytes * 1.15),
            canInstall=(
                workflow.canInstall
                and workflow.hardwareCompatible
                and not runtime_errors
            ),
        )
