from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class RuntimeState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    WARNING = "warning"
    ERROR = "error"
    STOPPING = "stopping"
    CONFLICT = "conflict"


class JobStatus(StrEnum):
    CREATED = "created"
    VALIDATING = "validating"
    WAITING_RUNTIME = "waiting_runtime"
    WAITING_AUTH = "waiting_auth"
    STAGING_INPUTS = "staging_inputs"
    QUEUED = "queued"
    RUNNING = "running"
    RECOVERING = "recovering"
    DOWNLOADING = "downloading"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "flynotes-local-agent"
    version: str
    comfyui: RuntimeState


class RuntimeStatusResponse(BaseModel):
    state: RuntimeState
    baseUrl: str
    root: str
    pid: int | None = None
    managed: bool = False
    comfyVersion: str | None = None
    pythonVersion: str | None = None
    queueRunning: int = 0
    queuePending: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    message: str = ""


class GpuStatsResponse(BaseModel):
    index: int
    name: str
    utilizationPercent: float | None = None
    memoryUsedBytes: int | None = None
    memoryTotalBytes: int | None = None
    temperatureC: float | None = None


class SystemMetricsResponse(BaseModel):
    cpuPercent: float | None = None
    memoryUsedBytes: int = 0
    memoryTotalBytes: int = 0
    memoryPercent: float | None = None
    gpus: list[GpuStatsResponse] = Field(default_factory=list)
    updatedAt: datetime


class ParameterField(BaseModel):
    key: str
    label: str
    type: Literal["string", "integer", "number", "boolean", "enum", "file-list"]
    default: Any = None
    required: bool = False
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    options: list[Any] = Field(default_factory=list)
    advanced: bool = False


class ModelSpec(BaseModel):
    id: str
    displayName: str
    provider: Literal["comfyui", "flynotes"]
    mediaType: Literal["video"] = "video"
    workflowId: str | None = None
    workflowVersion: str | None = None
    modes: list[str]
    available: bool = True
    requiresCloudAuth: bool = False
    statusMessage: str = ""
    fields: list[ParameterField] = Field(default_factory=list)


class JobInput(BaseModel):
    uploadId: str
    role: str


class JobClient(BaseModel):
    type: Literal["desktop", "blender"]
    version: str = "unknown"
    instanceId: str = ""


class JobCreateRequest(BaseModel):
    clientRequestId: str = Field(min_length=1, max_length=128)
    client: JobClient
    modelId: str
    mode: str
    prompt: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    inputs: list[JobInput] = Field(default_factory=list)


class JobResponse(BaseModel):
    id: str
    clientRequestId: str
    clientType: str
    clientInstanceId: str
    modelId: str
    provider: str
    workflowId: str | None = None
    workflowVersion: str | None = None
    mode: str
    prompt: str
    parameters: dict[str, Any]
    inputs: list[JobInput] = Field(default_factory=list)
    status: JobStatus
    progress: float = 0
    promptId: str | None = None
    remoteJobId: str | None = None
    actualSeed: int | None = None
    errorCode: str | None = None
    errorMessage: str | None = None
    resultPath: str | None = None
    createdAt: datetime
    updatedAt: datetime


class UploadResponse(BaseModel):
    id: str
    originalName: str
    size: int
    sha256: str
    contentType: str
    createdAt: datetime


class AssetResponse(BaseModel):
    id: str
    jobId: str
    path: str
    thumbnailPath: str | None = None
    mediaType: Literal["video"] = "video"
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    fps: float | None = None
    hasAudio: bool = False
    sizeBytes: int
    sha256: str
    modelId: str
    workflowVersion: str | None = None
    mode: str
    prompt: str
    parameters: dict[str, Any]
    actualSeed: int | None = None
    createdAt: datetime


class PluginStatusResponse(BaseModel):
    id: str = "flynotes-ai-blender"
    name: str = "Flynotes AI Blender 插件"
    repository: str = ""
    configured: bool = False
    blenderVersion: str = ""
    installedPath: str = ""
    installedVersion: str | None = None
    availableVersion: str | None = None
    stagedVersion: str | None = None
    updateAvailable: bool = False
    state: str = "not-installed"
    lastCheckedAt: datetime | None = None
    error: str = ""


class PluginStageRequest(BaseModel):
    manifest: dict[str, Any] | None = None


class BlenderHeartbeatRequest(BaseModel):
    instanceId: str
    blenderVersion: str
    pluginVersion: str
    state: Literal["idle", "busy"] = "idle"
    activeJobId: str = ""


class WorkflowState(StrEnum):
    NOT_INSTALLED = "not_installed"
    NEEDS_VERIFICATION = "needs_verification"
    NEEDS_REPAIR = "needs_repair"
    READY = "ready"
    INCOMPATIBLE = "incompatible"
    INSTALL_FAILED = "install_failed"


class WorkflowHardwareRequirements(BaseModel):
    gpuVendor: str = "nvidia"
    minimumVramGB: float = 8
    minimumRamGB: float = 16
    minimumDriver: str = "580.00"
    recommendedVramGB: float | None = None
    recommendedRamGB: float | None = None
    lowMemoryMode: bool = False


class WorkflowResourceStatus(BaseModel):
    id: str
    type: Literal["runtime", "node", "model", "wheel", "workflow"]
    installed: bool
    size: int | None = None
    path: str = ""
    message: str = ""


class WorkflowStatusResponse(BaseModel):
    id: str
    version: str
    displayName: str
    description: str = ""
    provider: Literal["comfyui"] = "comfyui"
    modes: list[str] = Field(default_factory=list)
    state: WorkflowState
    statusMessage: str = ""
    packagePath: str
    hardware: WorkflowHardwareRequirements
    hardwareCompatible: bool = True
    hardwareWarnings: list[str] = Field(default_factory=list)
    missingModels: list[str] = Field(default_factory=list)
    missingNodes: list[str] = Field(default_factory=list)
    uncheckedNodes: list[str] = Field(default_factory=list)
    resources: list[WorkflowResourceStatus] = Field(default_factory=list)
    downloadBytes: int = 0
    canInstall: bool = False


class WorkflowInstallPlanResponse(BaseModel):
    workflowId: str
    workflowVersion: str
    state: WorkflowState
    hardwareCompatible: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missingResources: list[WorkflowResourceStatus] = Field(default_factory=list)
    downloadBytes: int = 0
    requiredDiskBytes: int = 0
    canInstall: bool = False


class WorkflowInstallState(StrEnum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowInstallOperationResponse(BaseModel):
    id: str
    workflowId: str
    workflowVersion: str
    state: WorkflowInstallState
    currentResourceId: str = ""
    currentFilename: str = ""
    downloadedBytes: int = 0
    totalBytes: int = 0
    progressPercent: float = 0
    errorCode: str = ""
    errorMessage: str = ""
    createdAt: datetime
    updatedAt: datetime


class WorkflowCatalogStatusResponse(BaseModel):
    configured: bool
    url: str
    workflowCount: int = 0
    generatedAt: str = ""
    lastSyncedAt: datetime | None = None
    errorCode: str = ""
    errorMessage: str = ""


class RuntimePackageState(StrEnum):
    NOT_INSTALLED = "not_installed"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    INSTALLING = "installing"
    READY = "ready"
    FAILED = "failed"


class RuntimePackageStatusResponse(BaseModel):
    runtimeId: str
    state: RuntimePackageState
    configured: bool
    manifestUrl: str = ""
    installPath: str = ""
    downloadedBytes: int = 0
    totalBytes: int = 0
    progressPercent: float = 0
    errorCode: str = ""
    errorMessage: str = ""
