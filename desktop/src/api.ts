import { invoke } from "@tauri-apps/api/core";

export const AGENT_URL = "http://127.0.0.1:17980";

export type RuntimeState = "stopped" | "starting" | "ready" | "warning" | "error" | "stopping" | "conflict";

export interface RuntimeStatus {
  state: RuntimeState;
  baseUrl: string;
  root: string;
  pid: number | null;
  managed: boolean;
  comfyVersion: string | null;
  pythonVersion: string | null;
  queueRunning: number;
  queuePending: number;
  errors: string[];
  warnings: string[];
  message: string;
}

export interface RuntimePackageStatus {
  runtimeId: string;
  state: "not_installed" | "downloading" | "verifying" | "installing" | "ready" | "failed";
  configured: boolean;
  manifestUrl: string;
  installPath: string;
  downloadedBytes: number;
  totalBytes: number;
  progressPercent: number;
  errorCode: string;
  errorMessage: string;
}

export interface GpuStats {
  index: number;
  name: string;
  utilizationPercent: number | null;
  memoryUsedBytes: number | null;
  memoryTotalBytes: number | null;
  temperatureC: number | null;
}

export interface SystemMetrics {
  cpuPercent: number | null;
  memoryUsedBytes: number;
  memoryTotalBytes: number;
  memoryPercent: number | null;
  gpus: GpuStats[];
  updatedAt: string;
}

export interface ModelField {
  key: string;
  label: string;
  type: string;
  default: unknown;
  required: boolean;
  minimum: number | null;
  maximum: number | null;
  step: number | null;
  options: unknown[];
  advanced: boolean;
}

export interface ModelSpec {
  id: string;
  displayName: string;
  provider: "comfyui" | "flynotes";
  workflowId: string | null;
  workflowVersion: string | null;
  modes: string[];
  available: boolean;
  requiresCloudAuth: boolean;
  statusMessage: string;
  fields: ModelField[];
}

export interface Job {
  id: string;
  clientRequestId: string;
  clientType: string;
  modelId: string;
  provider: string;
  mode: string;
  prompt: string;
  parameters: Record<string, unknown>;
  status: string;
  progress: number;
  promptId: string | null;
  actualSeed: number | null;
  errorCode: string | null;
  errorMessage: string | null;
  resultPath: string | null;
  createdAt: string;
}

export interface Asset {
  id: string;
  jobId: string;
  path: string;
  thumbnailPath: string | null;
  mediaType: "video";
  width: number | null;
  height: number | null;
  duration: number | null;
  fps: number | null;
  hasAudio: boolean;
  sizeBytes: number;
  sha256: string;
  modelId: string;
  workflowVersion: string | null;
  mode: string;
  prompt: string;
  actualSeed: number | null;
  createdAt: string;
}

export interface PluginStatus {
  id: string;
  name: string;
  repository: string;
  configured: boolean;
  blenderVersion: string;
  installedPath: string;
  installedVersion: string | null;
  availableVersion: string | null;
  stagedVersion: string | null;
  updateAvailable: boolean;
  state: string;
  lastCheckedAt: string | null;
  error: string;
}

export interface UploadRecord {
  id: string;
  originalName: string;
  size: number;
  sha256: string;
  contentType: string;
  createdAt: string;
}

export type WorkflowState = "not_installed" | "needs_verification" | "needs_repair" | "ready" | "incompatible" | "install_failed";

export interface WorkflowHardware {
  gpuVendor: string;
  minimumVramGB: number;
  minimumRamGB: number;
  minimumDriver: string;
  recommendedVramGB: number | null;
  recommendedRamGB: number | null;
  lowMemoryMode: boolean;
}

export interface WorkflowStatus {
  id: string;
  version: string;
  displayName: string;
  description: string;
  provider: "comfyui";
  modes: string[];
  state: WorkflowState;
  statusMessage: string;
  packagePath: string;
  hardware: WorkflowHardware;
  hardwareCompatible: boolean;
  hardwareWarnings: string[];
  missingModels: string[];
  missingNodes: string[];
  uncheckedNodes: string[];
  downloadBytes: number;
  canInstall: boolean;
}

export interface WorkflowInstallPlan {
  workflowId: string;
  workflowVersion: string;
  state: WorkflowState;
  hardwareCompatible: boolean;
  errors: string[];
  warnings: string[];
  downloadBytes: number;
  requiredDiskBytes: number;
  canInstall: boolean;
}

export type WorkflowInstallState = "queued" | "downloading" | "paused" | "verifying" | "succeeded" | "failed" | "cancelled";

export interface WorkflowInstallOperation {
  id: string;
  workflowId: string;
  workflowVersion: string;
  state: WorkflowInstallState;
  currentResourceId: string;
  currentFilename: string;
  downloadedBytes: number;
  totalBytes: number;
  progressPercent: number;
  errorCode: string;
  errorMessage: string;
  createdAt: string;
  updatedAt: string;
}

export interface WorkflowCatalogStatus {
  configured: boolean;
  url: string;
  workflowCount: number;
  generatedAt: string;
  lastSyncedAt: string | null;
  errorCode: string;
  errorMessage: string;
}

export interface LogResponse { source: string; path: string; lines: string[] }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData;
  const response = await fetch(`${AGENT_URL}${path}`, {
    ...init,
    headers: isForm ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail?.message ?? `请求失败 (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const agentApi = {
  ensureAgent: () => invoke<void>("start_agent"),
  runtime: () => request<RuntimeStatus>("/v1/runtime/comfyui"),
  runtimePackage: () => request<RuntimePackageStatus>("/v1/runtime/package"),
  runtimeAction: (action: "start" | "stop" | "restart") => request<RuntimeStatus>(`/v1/runtime/comfyui/${action}`, { method: "POST" }),
  systemMetrics: () => request<SystemMetrics>("/v1/system/metrics"),
  models: () => request<ModelSpec[]>("/v1/models"),
  catalog: () => request<WorkflowCatalogStatus>("/v1/catalog"),
  refreshCatalog: () => request<WorkflowCatalogStatus>("/v1/catalog/refresh", { method: "POST" }),
  workflows: () => request<WorkflowStatus[]>("/v1/workflows"),
  workflowPlan: (id: string) => request<WorkflowInstallPlan>(`/v1/workflows/${encodeURIComponent(id)}/plan`, { method: "POST" }),
  installWorkflow: (id: string) => request<WorkflowInstallOperation>(`/v1/workflows/${encodeURIComponent(id)}/install`, { method: "POST" }),
  downloads: () => request<WorkflowInstallOperation[]>("/v1/downloads"),
  downloadAction: (id: string, action: "pause" | "resume" | "retry") => request<WorkflowInstallOperation>(`/v1/downloads/${encodeURIComponent(id)}/${action}`, { method: "POST" }),
  cancelDownload: (id: string) => request<WorkflowInstallOperation>(`/v1/downloads/${encodeURIComponent(id)}`, { method: "DELETE" }),
  verifyWorkflow: (id: string) => request<WorkflowStatus>(`/v1/workflows/${encodeURIComponent(id)}/verify`, { method: "POST" }),
  jobs: () => request<Job[]>("/v1/jobs"),
  assets: () => request<Asset[]>("/v1/assets"),
  plugins: () => request<PluginStatus[]>("/v1/plugins"),
  logs: (source = "comfyui") => request<LogResponse>(`/v1/logs?source=${encodeURIComponent(source)}&tail=200`),
  createJob: (body: unknown) => request<Job>("/v1/jobs", { method: "POST", body: JSON.stringify(body) }),
  cancelJob: (id: string) => request<Job>(`/v1/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<UploadRecord>("/v1/uploads", { method: "POST", body: form });
  },
  checkPluginUpdates: () => request<PluginStatus[]>("/v1/plugins/check-updates", { method: "POST" }),
  stagePluginUpdate: () => request<PluginStatus[]>("/v1/plugins/stage-update", { method: "POST", body: "{}" }),
  applyPluginUpdate: (id: string) => request<PluginStatus[]>(`/v1/plugins/${encodeURIComponent(id)}/apply-update`, { method: "POST" }),
  rollbackPlugin: (id: string) => request<PluginStatus[]>(`/v1/plugins/${encodeURIComponent(id)}/rollback`, { method: "POST" }),
  assetContent: (id: string) => `${AGENT_URL}/v1/assets/${encodeURIComponent(id)}/content`,
  assetThumbnail: (id: string) => `${AGENT_URL}/v1/assets/${encodeURIComponent(id)}/thumbnail`,
};
