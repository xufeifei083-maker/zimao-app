import {
  Activity,
  Check,
  CircleStop,
  Cpu,
  Film,
  Gauge,
  HardDrive,
  Layers3,
  Library,
  PackageOpen,
  LoaderCircle,
  Play,
  PlugZap,
  RefreshCw,
  RotateCw,
  Settings,
  Sparkles,
  Upload,
  WandSparkles,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { agentApi, Asset, Job, LogResponse, ModelSpec, PluginStatus, RuntimePackageStatus, RuntimeStatus, SystemMetrics, WorkflowInstallOperation, WorkflowStatus } from "./api";

type Tab = "service" | "workflows" | "generate" | "library" | "plugins";

const tabs = [
  { id: "service" as Tab, label: "ComfyUI 服务", icon: Gauge },
  { id: "workflows" as Tab, label: "工作流中心", icon: PackageOpen },
  { id: "generate" as Tab, label: "视频生成", icon: WandSparkles },
  { id: "library" as Tab, label: "素材库", icon: Library },
  { id: "plugins" as Tab, label: "插件列表", icon: PlugZap },
];

const modeLabels: Record<string, string> = {
  text: "文生视频",
  first_frame: "首帧生成",
  first_last: "首尾帧生成",
  reference: "全能参考",
};

const stateLabels: Record<string, string> = {
  stopped: "已停止",
  starting: "启动中",
  ready: "运行正常",
  warning: "兼容运行",
  error: "异常",
  stopping: "停止中",
  conflict: "端口冲突",
};

const jobStatusLabels: Record<string, string> = {
  created: "已创建",
  validating: "校验中",
  waiting_runtime: "等待服务",
  staging_inputs: "准备素材",
  queued: "排队中",
  running: "生成中",
  recovering: "恢复中",
  downloading: "整理结果",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const emptyRuntime: RuntimeStatus = {
  state: "stopped",
  baseUrl: "http://127.0.0.1:8188",
  root: "—",
  pid: null,
  managed: false,
  comfyVersion: null,
  pythonVersion: null,
  queueRunning: 0,
  queuePending: 0,
  errors: [],
  warnings: [],
  message: "正在连接本地服务…",
};

const emptySystemMetrics: SystemMetrics = {
  cpuPercent: null,
  memoryUsedBytes: 0,
  memoryTotalBytes: 0,
  memoryPercent: null,
  gpus: [],
  updatedAt: "",
};

const emptyRuntimePackage: RuntimePackageStatus = {
  runtimeId: "win-nvidia-h3-2026.08.1", state: "not_installed", configured: false,
  manifestUrl: "", installPath: "", downloadedBytes: 0, totalBytes: 0,
  progressPercent: 0, errorCode: "", errorMessage: "",
};

export default function App() {
  const [tab, setTab] = useState<Tab>("service");
  const [runtime, setRuntime] = useState<RuntimeStatus>(emptyRuntime);
  const [runtimePackage, setRuntimePackage] = useState<RuntimePackageStatus>(emptyRuntimePackage);
  const [models, setModels] = useState<ModelSpec[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowStatus[]>([]);
  const [downloads, setDownloads] = useState<WorkflowInstallOperation[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [plugins, setPlugins] = useState<PluginStatus[]>([]);
  const [logs, setLogs] = useState<LogResponse>({ source: "comfyui", path: "", lines: [] });
  const [systemMetrics, setSystemMetrics] = useState<SystemMetrics>(emptySystemMetrics);
  const [connected, setConnected] = useState(false);
  const [toast, setToast] = useState("");

  const refresh = useCallback(async () => {
    try {
      // Runtime connectivity is the source of truth for the service badge.
      // Keep it separate from optional panels so one stale endpoint cannot
      // incorrectly turn the whole Agent indicator offline.
      const nextRuntime = await agentApi.runtime();
      setRuntime(nextRuntime);
      setConnected(true);
      const [models, workflows, downloads, jobs, assets, plugins, logs, systemMetrics, runtimePackage] = await Promise.allSettled([
        agentApi.models(), agentApi.workflows(), agentApi.downloads(), agentApi.jobs(), agentApi.assets(), agentApi.plugins(), agentApi.logs(), agentApi.systemMetrics(), agentApi.runtimePackage(),
      ]);
      if (models.status === "fulfilled") setModels(models.value);
      if (workflows.status === "fulfilled") setWorkflows(workflows.value);
      if (downloads.status === "fulfilled") setDownloads(downloads.value);
      if (jobs.status === "fulfilled") setJobs(jobs.value);
      if (assets.status === "fulfilled") setAssets(assets.value);
      if (plugins.status === "fulfilled") setPlugins(plugins.value);
      if (logs.status === "fulfilled") setLogs(logs.value);
      if (systemMetrics.status === "fulfilled") setSystemMetrics(systemMetrics.value);
      if (runtimePackage.status === "fulfilled") setRuntimePackage(runtimePackage.value);
    } catch {
      setConnected(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 3500);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const pending = jobs.filter((job) => !["succeeded", "failed", "cancelled"].includes(job.status)).length;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><Sparkles size={19} /></div><div><strong>Flynotes</strong><span>AI 控制中心</span></div></div>
        <nav>
          <p className="nav-caption">控制台</p>
          {tabs.map((item) => {
            const Icon = item.icon;
            return <button key={item.id} className={tab === item.id ? "nav-item active" : "nav-item"} onClick={() => setTab(item.id)}><Icon size={18} /><span>{item.label}</span>{item.id === "generate" && <i>本地</i>}</button>;
          })}
        </nav>
        <div className="sidebar-foot">
          <div className="agent-card"><span className={`status-dot ${connected ? "online" : "offline"}`} /><div><strong>Local Agent</strong><small>{connected ? "后台服务已连接" : "等待 17980 端口"}</small></div></div>
          <button className="settings-button"><Settings size={17} /> 设置</button>
          <span className="build">RELEASE CANDIDATE · 0.1.0</span>
        </div>
      </aside>
      <main>
        <header className="topbar"><div><span className="eyebrow">LOCAL AI WORKSPACE</span><h1>{tabs.find((item) => item.id === tab)?.label}</h1></div><div className="top-status"><StatusPill online={connected} label={connected ? "Agent 在线" : "Agent 离线"} /><StatusPill online={["ready", "warning"].includes(runtime.state)} label={`ComfyUI ${stateLabels[runtime.state]}`} warn={runtime.state === "warning"} /><div className="queue-count"><Layers3 size={15} /><b>{pending}</b><span>任务</span></div></div></header>
        <div className="content">
          {tab === "service" && <ServicePanel runtime={runtime} runtimePackage={runtimePackage} connected={connected} logs={logs} systemMetrics={systemMetrics} refresh={refresh} notify={setToast} />}
          {tab === "workflows" && <WorkflowCenter workflows={workflows} downloads={downloads} refresh={refresh} notify={setToast} useWorkflow={() => setTab("generate")} />}
          {tab === "generate" && <GeneratePanel models={models} runtime={runtime} notify={setToast} created={() => { void refresh(); setTab("library"); }} />}
          {tab === "library" && <LibraryPanel assets={assets} jobs={jobs} refresh={refresh} notify={setToast} />}
          {tab === "plugins" && <PluginsPanel plugins={plugins} refresh={refresh} notify={setToast} />}
        </div>
      </main>
      {toast && <div className="toast"><Check size={16} />{toast}</div>}
    </div>
  );
}

function StatusPill({ online, label, warn = false }: { online: boolean; label: string; warn?: boolean }) {
  return <div className={`status-pill ${online ? (warn ? "warn" : "online") : "offline"}`}><span />{label}</div>;
}

function formatBytes(value: number | null | undefined): string {
  if (!value || value < 0) return "未检测";
  const units = ["B", "GB", "TB"];
  let amount = value;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

function formatPercent(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? "未检测" : `${Math.round(value)}%`;
}

const workflowStateLabels: Record<string, string> = {
  not_installed: "未安装",
  needs_verification: "等待验证",
  needs_repair: "需要修复",
  ready: "可以使用",
  incompatible: "硬件不兼容",
  install_failed: "安装失败",
};

function WorkflowCenter({ workflows, downloads, refresh, notify, useWorkflow }: { workflows: WorkflowStatus[]; downloads: WorkflowInstallOperation[]; refresh: () => Promise<void>; notify: (text: string) => void; useWorkflow: () => void }) {
  const [busy, setBusy] = useState("");
  const verify = async (workflow: WorkflowStatus) => {
    setBusy(workflow.id);
    try {
      const result = await agentApi.verifyWorkflow(workflow.id);
      notify(result.statusMessage);
      await refresh();
    } catch (error) { notify(error instanceof Error ? error.message : "验证失败"); }
    finally { setBusy(""); }
  };
  const inspectPlan = async (workflow: WorkflowStatus) => {
    setBusy(workflow.id);
    try {
      const plan = await agentApi.workflowPlan(workflow.id);
      if (plan.errors.length) notify(plan.errors.join("；"));
      else if (plan.downloadBytes) notify(`需要下载 ${formatBytes(plan.downloadBytes)}`);
      else notify("当前资源已经齐全");
    } catch (error) { notify(error instanceof Error ? error.message : "无法生成安装计划"); }
    finally { setBusy(""); }
  };
  const install = async (workflow: WorkflowStatus) => {
    setBusy(workflow.id);
    try {
      await agentApi.installWorkflow(workflow.id);
      notify("已开始下载工作流资源");
      await refresh();
    } catch (error) { notify(error instanceof Error ? error.message : "无法开始安装"); }
    finally { setBusy(""); }
  };
  const downloadAction = async (operation: WorkflowInstallOperation, action: "pause" | "resume" | "retry" | "cancel") => {
    setBusy(operation.id);
    try {
      if (action === "cancel") await agentApi.cancelDownload(operation.id);
      else await agentApi.downloadAction(operation.id, action);
      await refresh();
    } catch (error) { notify(error instanceof Error ? error.message : "下载操作失败"); }
    finally { setBusy(""); }
  };
  const syncCatalog = async () => {
    setBusy("catalog");
    try {
      const result = await agentApi.refreshCatalog();
      notify(`已同步 ${result.workflowCount} 个工作流`);
      await refresh();
    } catch (error) { notify(error instanceof Error ? error.message : "目录同步失败"); }
    finally { setBusy(""); }
  };
  return <section className="stack">
    <div className="plugins-intro"><div><span className="eyebrow">ZIMAO WORKFLOW CATALOG</span><h2>工作流中心</h2><p>所有工作流共用固定的 ComfyUI 与 Python。紫猫会检查硬件、模型和节点，只有验证通过后才能使用。</p></div><div className="workflow-catalog-actions"><button disabled={busy === "catalog"} onClick={() => void syncCatalog()}><RefreshCw className={busy === "catalog" ? "spin" : ""} size={16} />同步目录</button><button onClick={() => void refresh()}><RefreshCw size={16} />重新检查</button></div></div>
    <div className="workflow-grid">
      {workflows.map((workflow) => { const operation = downloads.find((item) => item.workflowId === workflow.id && !["succeeded", "cancelled"].includes(item.state)); return <article className="workflow-card" key={workflow.id}>
        <div className="workflow-card-head"><div className="workflow-icon"><WandSparkles size={22} /></div><div><h3>{workflow.displayName}</h3><span>版本 {workflow.version}</span></div><span className={`workflow-state ${workflow.state}`}>{workflowStateLabels[workflow.state] ?? workflow.state}</span></div>
        <p>{workflow.description || "紫猫审核并维护的本地 AI 工作流"}</p>
        <div className="workflow-modes">{workflow.modes.map((mode) => <span key={mode}>{modeLabels[mode] ?? mode}</span>)}</div>
        <dl className="workflow-requirements"><dt>最低显存</dt><dd>{workflow.hardware.minimumVramGB} GB</dd><dt>最低内存</dt><dd>{workflow.hardware.minimumRamGB} GB</dd><dt>低显存模式</dt><dd>{workflow.hardware.lowMemoryMode ? "支持" : "不支持"}</dd><dt>缺少资源</dt><dd>{workflow.missingModels.length} 模型 / {workflow.missingNodes.length} 节点</dd></dl>
        <div className={`workflow-message ${workflow.hardwareCompatible ? "" : "error"}`}>{workflow.statusMessage}</div>
        {workflow.hardwareWarnings.map((warning) => <small className="workflow-warning" key={warning}>{warning}</small>)}
        {operation && <div className="workflow-download"><div><strong>{operation.state === "verifying" ? "正在验证" : operation.state === "paused" ? "下载已暂停" : operation.state === "failed" ? "安装失败" : "正在下载"}</strong><span>{operation.currentFilename || operation.errorMessage || `${operation.progressPercent.toFixed(1)}%`}</span></div><div className="workflow-progress"><i style={{ width: `${Math.max(0, Math.min(100, operation.progressPercent))}%` }} /></div><small>{formatBytes(operation.downloadedBytes)} / {formatBytes(operation.totalBytes)}</small></div>}
        <div className="workflow-actions">
          {workflow.state === "ready" ? <button className="primary" onClick={useWorkflow}><Play size={16} />立即使用</button> : !operation && <button className="primary" disabled={busy === workflow.id || !workflow.canInstall} onClick={() => void install(workflow)}><HardDrive size={16} />一键安装</button>}
          {operation?.state === "downloading" && <button disabled={busy === operation.id} onClick={() => void downloadAction(operation, "pause")}>暂停</button>}
          {operation?.state === "paused" && <button disabled={busy === operation.id} onClick={() => void downloadAction(operation, "resume")}>继续</button>}
          {operation?.state === "failed" && <button disabled={busy === operation.id} onClick={() => void downloadAction(operation, "retry")}>重试</button>}
          {operation && !["succeeded", "cancelled", "verifying"].includes(operation.state) && <button disabled={busy === operation.id} onClick={() => void downloadAction(operation, "cancel")}>取消</button>}
          {!operation && workflow.state !== "ready" && <button disabled={busy === workflow.id} onClick={() => void inspectPlan(workflow)}>查看计划</button>}
          <button disabled={busy === workflow.id} onClick={() => void verify(workflow)}><RefreshCw className={busy === workflow.id ? "spin" : ""} size={16} />验证</button>
        </div>
      </article>; })}
      {!workflows.length && <div className="empty-state"><PackageOpen size={36} /><strong>暂未发现工作流</strong><span>请检查 Local Agent 和工作流包目录。</span></div>}
    </div>
  </section>;
}

function ServicePanel({ runtime, runtimePackage, connected, logs, systemMetrics, refresh, notify }: { runtime: RuntimeStatus; runtimePackage: RuntimePackageStatus; connected: boolean; logs: LogResponse; systemMetrics: SystemMetrics; refresh: () => Promise<void>; notify: (text: string) => void }) {
  const [busy, setBusy] = useState("");
  const action = async (name: "start" | "stop" | "restart") => {
    setBusy(name);
    try {
      if (name === "start") {
        // Recover from a late Agent launch so one click can bring up both
        // background services.
        await agentApi.ensureAgent();
        let agentReady = false;
        for (let attempt = 0; attempt < 40; attempt += 1) {
          try {
            await agentApi.runtime();
            agentReady = true;
            break;
          } catch {
            await new Promise((resolve) => window.setTimeout(resolve, 500));
          }
        }
        if (!agentReady) throw new Error("Local Agent 启动超时，请重试");
      }
      await agentApi.runtimeAction(name);
      await refresh();
      notify(name === "stop" ? "ComfyUI 已停止" : "ComfyUI 运行状态已更新");
    } catch (error) { notify(error instanceof Error ? error.message : "操作失败"); }
    finally { setBusy(""); }
  };
  const ready = ["ready", "warning"].includes(runtime.state);
  return <section className="stack">
    <div className="hero-card"><div className="hero-orb"><Cpu size={32} /></div><div className="hero-copy"><div className="title-row"><h2>ComfyUI Runtime</h2><span className={`runtime-badge ${runtime.state}`}>{stateLabels[runtime.state]}</span></div><p>{connected ? runtime.message : "点击“启动全部服务”，系统会先启动 Local Agent，再启动 ComfyUI。"}</p><div className="runtime-actions"><button className="primary" disabled={ready || Boolean(busy)} onClick={() => void action("start")}><Play size={16} />{busy === "start" ? "正在启动…" : "启动全部服务"}</button><button disabled={!ready || !runtime.managed || Boolean(busy)} onClick={() => void action("stop")}><CircleStop size={16} />停止</button><button disabled={!ready || !runtime.managed || Boolean(busy)} onClick={() => void action("restart")}><RotateCw className={busy === "restart" ? "spin" : ""} size={16} />重启</button></div></div></div>
    {(runtime.errors.length > 0 || runtime.warnings.length > 0) && <div className={runtime.errors.length ? "notice error" : "notice warning"}><Activity size={18} /><div><strong>{runtime.errors.length ? "运行异常" : "运行警告"}</strong><p>{[...runtime.errors, ...runtime.warnings].join("；")}</p></div></div>}
    <div className="metric-grid"><Metric icon={Activity} label="运行状态" value={stateLabels[runtime.state]} meta={runtime.managed ? "由控制中心托管" : "外部进程保护中"} /><Metric icon={Cpu} label="进程" value={runtime.pid ? `PID ${runtime.pid}` : "未运行"} meta={runtime.comfyVersion ? `ComfyUI ${runtime.comfyVersion}` : "等待版本检测"} /><Metric icon={Layers3} label="任务队列" value={`${runtime.queueRunning} 运行 / ${runtime.queuePending} 等待`} meta="桌面端与 Blender 共用" /><Metric icon={HardDrive} label="固定 Runtime" value={runtimePackage.state === "ready" ? "已就绪" : runtimePackage.state === "downloading" ? `${runtimePackage.progressPercent.toFixed(1)}%` : "等待安装"} meta={runtimePackage.runtimeId} /></div>
    <SystemResourcePanel metrics={systemMetrics} />
    <div className="split-grid"><div className="panel-card"><div className="panel-heading"><div><span className="eyebrow">ENVIRONMENT</span><h3>运行环境</h3></div><button className="icon-button" onClick={() => void refresh()}><RefreshCw size={16} /></button></div><dl className="details"><dt>服务地址</dt><dd>{runtime.baseUrl}</dd><dt>Runtime ID</dt><dd>{runtimePackage.runtimeId}</dd><dt>安装路径</dt><dd title={runtimePackage.installPath || runtime.root}>{runtimePackage.installPath || runtime.root}</dd><dt>进程归属</dt><dd>{runtime.managed ? "Local Agent" : "未托管"}</dd><dt>Gradio 7860</dt><dd className="good">不启动、不访问</dd></dl></div><div className="panel-card terminal-card"><div className="panel-heading"><div><span className="eyebrow">LIVE LOG</span><h3>ComfyUI 日志</h3></div><span className="live-label"><i />LIVE</span></div><div className="terminal">{logs.lines.slice(-12).map((line, index) => <p key={`${index}-${line}`}><span>Runtime</span> {line}</p>)}</div></div></div>
  </section>;
}

function Metric({ icon: Icon, label, value, meta }: { icon: typeof Activity; label: string; value: string; meta: string }) {
  return <div className="metric"><div className="metric-icon"><Icon size={18} /></div><span>{label}</span><strong>{value}</strong><small>{meta}</small></div>;
}

function SystemResourcePanel({ metrics }: { metrics: SystemMetrics }) {
  const gpu = metrics.gpus[0];
  const gpuMemoryPercent = gpu?.memoryUsedBytes != null && gpu.memoryTotalBytes ? (gpu.memoryUsedBytes / gpu.memoryTotalBytes) * 100 : null;
  return <div className="panel-card system-resource-card"><div className="panel-heading"><div><span className="eyebrow">SYSTEM MONITOR</span><h3>电脑运行状态</h3></div><span className="live-label"><i />每 3 秒更新</span></div><div className="resource-grid"><ResourceTile icon={Cpu} label="CPU" value={formatPercent(metrics.cpuPercent)} detail="处理器占用" percent={metrics.cpuPercent} /><ResourceTile icon={HardDrive} label="内存" value={formatBytes(metrics.memoryUsedBytes)} detail={`${formatPercent(metrics.memoryPercent)} · ${formatBytes(metrics.memoryTotalBytes)} 总计`} percent={metrics.memoryPercent} /><ResourceTile icon={Cpu} label="显卡" value={gpu ? formatPercent(gpu.utilizationPercent) : "未检测到"} detail={gpu?.name ?? "仅支持 NVIDIA nvidia-smi"} percent={gpu?.utilizationPercent} /><ResourceTile icon={Layers3} label="显存" value={gpu ? formatBytes(gpu.memoryUsedBytes) : "未检测"} detail={gpu ? `${formatPercent(gpuMemoryPercent)} · ${formatBytes(gpu.memoryTotalBytes)} 总计` : "显卡数据不可用"} percent={gpuMemoryPercent} /></div>{gpu?.temperatureC != null && <small className="resource-footnote">{gpu.name} · GPU 温度 {Math.round(gpu.temperatureC)}°C</small>}</div>;
}

function ResourceTile({ icon: Icon, label, value, detail, percent }: { icon: typeof Cpu; label: string; value: string; detail: string; percent: number | null | undefined }) {
  const width = percent == null ? 0 : Math.min(Math.max(percent, 0), 100);
  return <div className="resource-tile"><div className="resource-tile-top"><div className="resource-icon"><Icon size={15} /></div><span>{label}</span><strong>{value}</strong></div><small>{detail}</small><div className="resource-bar"><i style={{ width: `${width}%` }} /></div></div>;
}

const generationModeMeta: Record<string, { label: string; hint: string }> = {
  text: { label: "文生视频", hint: "根据文字描述生成视频" },
  first_frame: { label: "首帧生成", hint: "根据首帧图像生成视频" },
  first_last: { label: "首尾帧生成", hint: "连接首尾画面并生成视频" },
  reference: { label: "全能参考", hint: "结合多种参考素材生成视频" },
};

const aspectPresets: Record<string, [number, number]> = {
  "16:9": [832, 480],
  "9:16": [480, 832],
  "1:1": [640, 640],
  "4:5": [576, 720],
};

function GeneratePanel({ models, runtime, notify, created }: { models: ModelSpec[]; runtime: RuntimeStatus; notify: (text: string) => void; created: () => void }) {
  const [modelId, setModelId] = useState("minimax-h3-local");
  const model = models.find((item) => item.id === modelId) ?? models[0];
  const [mode, setMode] = useState("text");
  const [prompt, setPrompt] = useState("");
  const [width, setWidth] = useState(480);
  const [height, setHeight] = useState(832);
  const [duration, setDuration] = useState(5);
  const [steps, setSteps] = useState(20);
  const [seed, setSeed] = useState(-1);
  const [files, setFiles] = useState<Record<string, File[]>>({});
  const [submitting, setSubmitting] = useState(false);
  const promptRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (model && !model.modes.includes(mode)) setMode(model.modes[0] ?? "text");
  }, [model, mode]);

  const aspect = Object.entries(aspectPresets).find(([, value]) => value[0] === width && value[1] === height)?.[0] ?? "自定义";
  const setAspect = (value: string) => {
    const preset = aspectPresets[value];
    if (preset) {
      setWidth(preset[0]);
      setHeight(preset[1]);
    }
  };
  const reset = () => {
    setWidth(480);
    setHeight(832);
    setDuration(5);
    setSteps(20);
    setSeed(-1);
  };
  const setInput = (role: string, list: FileList | null) => setFiles((old) => ({ ...old, [role]: list ? Array.from(list) : [] }));
  const insertReference = (token: string) => {
    const textarea = promptRef.current;
    if (!textarea) {
      setPrompt((value) => value ? `${value} ${token}` : token);
      return;
    }
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const next = `${prompt.slice(0, start)}${token}${prompt.slice(end)}`.slice(0, 2000);
    setPrompt(next);
    requestAnimationFrame(() => {
      textarea.focus();
      const position = Math.min(start + token.length, next.length);
      textarea.setSelectionRange(position, position);
    });
  };
  const referenceTokens = mode === "reference" ? [
    ...(files.reference_image ?? []).map((_, index) => ({ token: `<Picture ${index + 1}>`, label: `图片 ${index + 1}` })),
    ...(files.reference_video ?? []).map((_, index) => ({ token: `<Video ${index + 1}>`, label: `视频 ${index + 1}` })),
    ...(files.reference_audio ?? []).map((_, index) => ({ token: `<Audio ${index + 1}>`, label: `音频 ${index + 1}` })),
  ] : [];
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!model || !model.available) return notify(model?.statusMessage || "模型暂不可用");
    if (!prompt.trim()) return notify("请先填写提示词");
    if (! ["ready", "warning"].includes(runtime.state)) return notify("请先启动 ComfyUI");
    if (["first_frame", "first_last"].includes(mode) && !files.first_frame?.length) return notify("请选择首帧图片");
    if (mode === "first_last" && !files.last_frame?.length) return notify("请选择尾帧图片");
    setSubmitting(true);
    try {
      const inputs: Array<{ uploadId: string; role: string }> = [];
      for (const [role, roleFiles] of Object.entries(files)) {
        for (const file of roleFiles) inputs.push({ uploadId: (await agentApi.upload(file)).id, role });
      }
      await agentApi.createJob({
        clientRequestId: crypto.randomUUID(),
        client: { type: "desktop", version: "0.1.0", instanceId: "desktop" },
        modelId: model.id,
        mode,
        prompt: prompt.trim(),
        parameters: { width, height, duration, steps, seed, refImageSize: "match" },
        inputs,
      });
      notify("任务已提交到本地队列");
      created();
    } catch (error) {
      notify(error instanceof Error ? error.message : "任务提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  return <form className="generation-workspace" onSubmit={submit}>
    <div className="generation-main">
      <section className="generation-card model-card-v2">
        <div className="section-heading"><div><span className="eyebrow">MODEL</span><h3>选择模型</h3></div><span className="section-status">{model?.available ? "本地可用" : "暂不可用"}</span></div>
        <div className="model-select-large"><div className="model-glyph"><Sparkles size={17} /></div><div className="model-select-copy"><select value={modelId} onChange={(event) => setModelId(event.target.value)}>{models.map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.displayName}{item.available ? "" : "（未接入）"}</option>)}</select><small>{model?.workflowVersion ? `工作流 ${model.workflowVersion}` : model?.statusMessage}</small></div><span className="select-chevron">⌄</span></div>
      </section>

      <section className="generation-card">
        <div className="section-heading"><div><span className="eyebrow">MODE</span><h3>生成模式</h3></div><span className="section-hint">选择一种创作方式</span></div>
        <div className="mode-grid-v2">{model?.modes.map((item) => { const meta = generationModeMeta[item] ?? { label: modeLabels[item] ?? item, hint: "" }; return <button type="button" key={item} className={mode === item ? "mode-card selected" : "mode-card"} onClick={() => setMode(item)}><span className="mode-icon"><Film size={21} /></span><strong>{meta.label}</strong><small>{meta.hint}</small>{mode === item && <span className="mode-check">✓</span>}</button>; })}</div>
      </section>

      <section className="generation-card prompt-card-v2">
        <div className="section-heading"><div><span className="eyebrow">PROMPT</span><h3>提示词</h3></div><span className="prompt-count">{prompt.length} / 2000</span></div>
        <textarea ref={promptRef} className="prompt-editor" value={prompt} onChange={(event) => setPrompt(event.target.value.slice(0, 2000))} rows={7} placeholder="描述镜头、主体、动作、光线与声音，越具体越好…" />
        <div className="prompt-helper"><span>示例提示词</span><button type="button" onClick={() => setPrompt(mode === "reference" ? "让 <Picture 1> 作为主体，参考 <Picture 2> 的色彩与构图，镜头缓慢推进。" : "一位宇航员在外太空缓慢旋转，电影级光线，史诗感，镜头平稳")}>{mode === "reference" ? "让 <Picture 1> 作为主体，参考 <Picture 2> 的色彩与构图" : "一位宇航员在外太空缓慢旋转，电影级光线，史诗感"} <Sparkles size={12} /></button></div>
      </section>

      {mode !== "text" && <section className="generation-card reference-card-v2"><div className="section-heading"><div><span className="eyebrow">REFERENCE MEDIA</span><h3>参考素材 <small>可选</small></h3></div><span className="section-hint">支持 JPG / PNG / MP4</span></div><div className="upload-grid">{["first_frame", "first_last"].includes(mode) && <UploadField label="首帧图片" accept="image/*" onFiles={(value) => setInput("first_frame", value)} />}{mode === "first_last" && <UploadField label="尾帧图片" accept="image/*" onFiles={(value) => setInput("last_frame", value)} />}{mode === "reference" && <><UploadField label="参考图片（最多 9 张）" accept="image/*" multiple onFiles={(value) => setInput("reference_image", value)} /><UploadField label="参考视频（最多 3 个）" accept="video/*" multiple onFiles={(value) => setInput("reference_video", value)} /><UploadField label="参考音频（最多 3 个）" accept="audio/*" multiple onFiles={(value) => setInput("reference_audio", value)} /></>}</div>{mode === "reference" && <div className="reference-token-toolbar"><div className="token-toolbar-heading"><strong>插入提示词引用</strong><span>点击后会插入到当前光标位置</span></div>{referenceTokens.length > 0 ? <div className="token-groups">{referenceTokens.map(({ token, label }) => <button type="button" className="token-button" key={token} onClick={() => insertReference(token)}>{label}<code>{token}</code></button>)}</div> : <span className="token-empty">先上传参考图片、视频或音频，再插入对应引用</span>}<small className="token-note">图片按上传顺序对应 Picture 1–9；视频和音频对应 Video / Audio 1–3。</small></div>}</section>}
    </div>

    <aside className="parameter-panel inspector-v2">
      <div className="inspector-heading"><div><span className="eyebrow">PARAMETERS</span><h3>生成参数</h3></div><button type="button" className="reset-button" onClick={reset}><RefreshCw size={13} />重置</button></div>
      <div className="preview-frame"><div className="preview-ratio" style={{ aspectRatio: `${width} / ${height}` }}><span>{aspect}</span></div><small>实时画面预览</small></div>
      <div className="inspector-label">画面比例</div><div className="choice-grid aspect-grid">{Object.keys(aspectPresets).map((item) => <button type="button" key={item} className={aspect === item ? "choice-button selected" : "choice-button"} onClick={() => setAspect(item)}>{item}</button>)}</div>
      <div className="inspector-label">分辨率（宽 × 高）</div><div className="two-fields"><NumberField label="宽度" value={width} setValue={setWidth} step={32} /><NumberField label="高度" value={height} setValue={setHeight} step={32} /></div>
      <div className="inspector-label">时长（秒）</div><div className="choice-grid duration-grid">{[4, 5, 6, 8, 10].map((item) => <button type="button" key={item} className={duration === item ? "choice-button selected" : "choice-button"} onClick={() => setDuration(item)}>{item}s</button>)}</div>
      <div className="inspector-label seed-label">随机种子 <span>Seed</span></div><div className="seed-control"><input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /><button type="button" onClick={() => setSeed(-1)} aria-label="随机种子"><RefreshCw size={14} /></button></div>
      <div className="advanced-control"><label>采样步数 <input type="number" value={steps} min={1} max={50} onChange={(event) => setSteps(Number(event.target.value))} /></label><span>步数越高，细节越丰富</span></div>
      <div className="inspector-estimate"><div><small>预计耗时</small><strong>约 2 分 10 秒</strong></div><div><small>本地 GPU</small><strong>RTX 3090</strong></div></div>
      <button className="submit-button" type="submit" disabled={submitting || !model?.available}>{submitting ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}{submitting ? "正在提交…" : "开始生成"}</button>
      <p className="submit-note">提交后任务进入本地队列，桌面端关闭也会继续执行。</p>
    </aside>
  </form>;
}

function LegacyGeneratePanel({ models, runtime, notify, created }: { models: ModelSpec[]; runtime: RuntimeStatus; notify: (text: string) => void; created: () => void }) {
  const [modelId, setModelId] = useState("minimax-h3-local");
  const model = models.find((item) => item.id === modelId) ?? models[0];
  const [mode, setMode] = useState("text");
  const [prompt, setPrompt] = useState("");
  const [width, setWidth] = useState(480);
  const [height, setHeight] = useState(832);
  const [duration, setDuration] = useState(5);
  const [steps, setSteps] = useState(20);
  const [seed, setSeed] = useState(-1);
  const [files, setFiles] = useState<Record<string, File[]>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => { if (model && !model.modes.includes(mode)) setMode(model.modes[0] ?? "text"); }, [model, mode]);

  const setInput = (role: string, list: FileList | null) => setFiles((old) => ({ ...old, [role]: list ? Array.from(list) : [] }));
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!model || !model.available) return notify(model?.statusMessage || "模型暂不可用");
    if (!prompt.trim()) return notify("请先填写提示词");
    if (!["ready", "warning"].includes(runtime.state)) return notify("请先启动 ComfyUI");
    if (["first_frame", "first_last"].includes(mode) && !files.first_frame?.length) return notify("请选择首帧图片");
    if (mode === "first_last" && !files.last_frame?.length) return notify("请选择尾帧图片");
    setSubmitting(true);
    try {
      const inputs: Array<{ uploadId: string; role: string }> = [];
      for (const [role, roleFiles] of Object.entries(files)) for (const file of roleFiles) inputs.push({ uploadId: (await agentApi.upload(file)).id, role });
      await agentApi.createJob({ clientRequestId: crypto.randomUUID(), client: { type: "desktop", version: "0.1.0", instanceId: "desktop" }, modelId: model.id, mode, prompt: prompt.trim(), parameters: { width, height, duration, steps, seed, refImageSize: "match" }, inputs });
      notify("任务已提交到本地队列");
      created();
    } catch (error) { notify(error instanceof Error ? error.message : "任务提交失败"); }
    finally { setSubmitting(false); }
  };

  return <form className="generate-layout" onSubmit={submit}><div className="generation-main stack"><div className="form-card"><span className="eyebrow">MODEL</span><h3>选择模型</h3><div className="select-wrap"><select value={modelId} onChange={(event) => setModelId(event.target.value)}>{models.map((item) => <option key={item.id} value={item.id} disabled={!item.available}>{item.displayName}{item.available ? "" : "（未接入）"}</option>)}</select></div><div className="model-meta"><span className="local-tag">{model?.provider === "comfyui" ? "本地" : "云端"}</span><span>{model?.workflowVersion ? `工作流 ${model.workflowVersion}` : model?.statusMessage}</span></div></div>
    <div className="form-card"><span className="eyebrow">MODE</span><h3>生成模式</h3><div className="mode-grid">{model?.modes.map((item) => <button type="button" key={item} className={mode === item ? "mode selected" : "mode"} onClick={() => setMode(item)}><Film size={18} /><span>{modeLabels[item] ?? item}</span></button>)}</div></div>
    <div className="form-card"><span className="eyebrow">PROMPT</span><h3>提示词</h3><textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} rows={6} placeholder="描述镜头、主体、动作、光线与声音…" /></div>
    {mode !== "text" && <div className="form-card"><span className="eyebrow">INPUTS</span><h3>参考素材</h3><div className="upload-grid">{["first_frame", "first_last"].includes(mode) && <UploadField label="首帧" accept="image/*" onFiles={(value) => setInput("first_frame", value)} />}{mode === "first_last" && <UploadField label="尾帧" accept="image/*" onFiles={(value) => setInput("last_frame", value)} />}{mode === "reference" && <><UploadField label="参考图片（最多 9 张）" accept="image/*" multiple onFiles={(value) => setInput("reference_image", value)} /><UploadField label="参考视频（最多 3 个）" accept="video/*" multiple onFiles={(value) => setInput("reference_video", value)} /><UploadField label="参考音频（最多 3 个）" accept="audio/*" multiple onFiles={(value) => setInput("reference_audio", value)} /></>}</div></div>}
    </div><aside className="parameter-panel"><span className="eyebrow">PARAMETERS</span><h3>生成参数</h3><NumberField label="宽度" value={width} setValue={setWidth} step={32} /><NumberField label="高度" value={height} setValue={setHeight} step={32} /><NumberField label="时长（秒）" value={duration} setValue={setDuration} /><NumberField label="采样步数" value={steps} setValue={setSteps} /><NumberField label="Seed（-1 随机）" value={seed} setValue={setSeed} /><button className="submit-button" type="submit" disabled={submitting || !model?.available}>{submitting ? <LoaderCircle className="spin" size={17} /> : <Sparkles size={17} />}开始生成</button><p className="submit-note">桌面端关闭后任务仍由 Agent 继续执行。</p></aside></form>;
}

function UploadField({ label, accept, multiple = false, onFiles }: { label: string; accept: string; multiple?: boolean; onFiles: (files: FileList | null) => void }) {
  const [selected, setSelected] = useState<File[]>([]);
  const handleChange = (files: FileList | null) => {
    const next = files ? Array.from(files) : [];
    setSelected(next);
    onFiles(files);
  };
  const names = selected.map((file) => file.name).join("、");
  return <label className={selected.length ? "upload-box selected" : "upload-box"}><Upload size={20} /><strong>{selected.length ? `已选择 ${selected.length} 个文件 · 待提交上传` : label}</strong><span title={names}>{selected.length ? `${names}（点击可更换）` : "点击选择文件"}</span><input type="file" accept={accept} multiple={multiple} onChange={(event) => handleChange(event.target.files)} /></label>;
}

function NumberField({ label, value, setValue, step = 1 }: { label: string; value: number; setValue: (value: number) => void; step?: number }) {
  return <label className="field-group"><span>{label}</span><input className="number-field" type="number" value={value} step={step} onChange={(event) => setValue(Number(event.target.value))} /></label>;
}

function LibraryPanel({ assets, jobs, refresh, notify }: { assets: Asset[]; jobs: Job[]; refresh: () => Promise<void>; notify: (text: string) => void }) {
  const [filter, setFilter] = useState("all");
  const shownJobs = useMemo(() => filter === "all" ? jobs : jobs.filter((job) => job.status === filter), [filter, jobs]);
  const cancel = async (id: string) => { try { await agentApi.cancelJob(id); await refresh(); notify("任务已取消"); } catch (error) { notify(error instanceof Error ? error.message : "取消失败"); } };
  return <section className="stack"><div className="library-toolbar"><div><span className="eyebrow">GENERATED ASSETS</span><h2>生成素材</h2></div><button className="icon-button" onClick={() => void refresh()}><RefreshCw size={16} /></button></div>{assets.length ? <div className="asset-grid">{assets.map((asset) => <article className="asset-card" key={asset.id}><div className="asset-preview"><video controls preload="metadata" poster={asset.thumbnailPath ? agentApi.assetThumbnail(asset.id) : undefined} src={agentApi.assetContent(asset.id)} /></div><div className="asset-info"><strong>{modeLabels[asset.mode] ?? asset.mode}</strong><span>{asset.width}×{asset.height} · {asset.duration?.toFixed(1)} 秒 · {asset.hasAudio ? "含音频" : "无音频"}</span><small title={asset.path}>{asset.prompt}</small></div></article>)}</div> : <div className="empty-state"><Library size={32} /><h3>还没有生成素材</h3><p>成功的视频会自动进入统一素材库。</p></div>}
    <div className="panel-card"><div className="panel-heading"><div><span className="eyebrow">TASKS</span><h3>任务记录</h3></div><div className="filter-tabs">{["all", "running", "succeeded", "failed"].map((item) => <button key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>{item === "all" ? "全部" : item === "running" ? "进行中" : item === "succeeded" ? "已完成" : "失败"}</button>)}</div></div>{shownJobs.map((job) => <div className="plugin-row" key={job.id}><div className="plugin-icon"><Film size={20} /></div><div className="plugin-copy"><strong>{modeLabels[job.mode] ?? job.mode}</strong><span>{job.prompt}</span><small>{job.id} · Seed {job.actualSeed ?? "待解析"}</small>{job.errorMessage && <small className="job-error">{job.errorMessage}</small>}</div><div className="plugin-actions"><span className={`job-state ${job.status}`}>{jobStatusLabels[job.status] ?? job.status}</span>{!["succeeded", "failed", "cancelled"].includes(job.status) && <button onClick={() => void cancel(job.id)}>取消</button>}</div></div>)}</div>
  </section>;
}

function PluginsPanel({ plugins, refresh, notify }: { plugins: PluginStatus[]; refresh: () => Promise<void>; notify: (text: string) => void }) {
  const [busy, setBusy] = useState("");
  const run = async (name: string, action: () => Promise<PluginStatus[]>) => { setBusy(name); try { await action(); await refresh(); notify("插件状态已更新"); } catch (error) { notify(error instanceof Error ? error.message : "插件操作失败"); } finally { setBusy(""); } };
  return <section className="stack"><div className="plugins-intro"><div><span className="eyebrow">BLENDER EXTENSIONS</span><h2>Blender 插件管理</h2><p>手动检查 GitHub Release。安装包必须同时通过 SHA256 与 Ed25519 签名验证；Blender 忙碌时更新会自动暂缓。</p></div><button className="primary" disabled={Boolean(busy)} onClick={() => void run("check", agentApi.checkPluginUpdates)}><RefreshCw className={busy === "check" ? "spin" : ""} size={16} />手动检测更新</button></div>
    <div className="panel-card">{plugins.map((plugin) => <div className="plugin-row" key={plugin.id}><div className="plugin-icon"><PlugZap size={22} /></div><div className="plugin-copy"><strong>{plugin.name}</strong><span>Blender {plugin.blenderVersion} · 已安装 {plugin.installedVersion ?? "未检测到"}</span><div className="version-line"><span className={plugin.updateAvailable ? "hot-update" : "installed"}>{plugin.stagedVersion ? `已暂存 ${plugin.stagedVersion}` : plugin.updateAvailable ? `可更新 ${plugin.availableVersion}` : "当前版本已就绪"}</span><small title={plugin.installedPath}>{plugin.installedPath || "未找到安装路径"}</small></div>{(!plugin.configured || plugin.error) && <small className="error">{plugin.error || "请配置 FLYNOTES_PLUGIN_REPOSITORY 与 FLYNOTES_PLUGIN_PUBLIC_KEY"}</small>}</div><div className="plugin-actions">{plugin.updateAvailable && !plugin.stagedVersion && <button disabled={!plugin.configured || Boolean(busy)} onClick={() => void run(`stage-${plugin.id}`, agentApi.stagePluginUpdate)}>验证并暂存</button>}{plugin.stagedVersion && <button className="primary" disabled={Boolean(busy)} onClick={() => void run(`apply-${plugin.id}`, () => agentApi.applyPluginUpdate(plugin.id))}>空闲时应用</button>}<button disabled={Boolean(busy)} onClick={() => void run(`rollback-${plugin.id}`, () => agentApi.rollbackPlugin(plugin.id))}>回滚</button></div></div>)}</div>
  </section>;
}
