# 本地 AI 控制中心 PRD 与开发验收文档

> 产品暂定名：Flynotes Local AI Control Center  
> 文档版本：1.0  
> 文档状态：开发基线  
> 编写日期：2026-08-10  
> 目标平台：Windows 10/11、Blender 4.0+（首发验收 Blender 5.0）

---

## 1. 文档目的

本文档同时作为以下工作的统一依据：

- 产品需求说明（PRD）
- 桌面端、后台服务和 Blender 插件的技术设计基线
- MiniMax H3 工作流迁移要求
- API、任务、素材及更新机制约定
- 开发排期和发布范围约定
- 测试计划、验收标准和发布门禁

任何实现与本文档冲突时，应先修改并评审本文档，再修改代码。不得以临时实现反向改变已经确认的产品边界。

---

## 2. 执行摘要

产品是一套运行在 Windows 桌面的“本地 AI 控制中心”。它以现有 MiniMax H3 整合包中的 ComfyUI 为通用本地推理底座，通过独立 Python Local Agent 统一管理 ComfyUI、工作流、任务、素材、Flynotes 云端模型及 Blender 插件。

系统最终只运行两个本地服务：

| 服务 | 默认地址 | 生命周期 |
|---|---|---|
| Python Local Agent | `127.0.0.1:17980` | 当前用户登录后常驻 |
| ComfyUI | `127.0.0.1:8188` | 由 Local Agent 按需启停 |

以下内容明确不进入最终运行架构：

- 不启动 Gradio
- 不监听 `7860`
- 不让桌面端直接连接 ComfyUI
- 不让 Blender 直接连接 ComfyUI 或 Flynotes
- 不修改 H3 原始工作流节点结构

视频生成页面只提供一个“模型”下拉框。本地执行的模型在名称后标记“（本地）”，例如：

```text
MiniMax H3（本地）
Seedance 2
Seedance 2 Fast
Seedance 2 Mini
Grok Video 1.5
```

发布的强制门禁是：必须在实际 Blender 5.0 中，通过 Flynotes AI 插件分别成功完成以下三个 MiniMax H3 本地工作流，并获得可播放、可加入 VSE 的视频结果：

1. 文生视频
2. 图生视频（首帧/可选尾帧，验收使用首尾帧）
3. 全能参考生成视频（验收同时包含图片、视频和音频参考）

任意一个工作流未在 Blender 中跑通，版本不得发布。

---

## 3. 已验证的技术基线

### 3.1 当前 ComfyUI 运行时

```text
E:\comfyui\最强AI视频生成-Minimax-H3整合包\
└── MinimaxH3-v260803.7z\
    └── MinimaxH3-v260803\
```

已确认：

- 该路径实际是已解压目录，不是待解压的 7z 文件。
- 内含完整 ComfyUI、Python 3.12、FFmpeg、Git、模型和自定义节点。
- 当前 ComfyUI 版本为 `0.30.0`。
- 当前 GPU 为 NVIDIA GeForce RTX 3090 24GB。
- 直接运行 `main.py` 可以完成 ComfyUI 核心和自定义节点初始化。
- `main.py` 不依赖 Gradio；Gradio 只由 `start.py` 引入和启动。
- 同时启动多个 ComfyUI 会争用同一数据库，因此产品必须实施单实例管理。

### 3.2 H3 工作流

已从现有模块验证三套工作流：

| 工作流 | API 节点数量 | 当前节点可用性 | 当前模型可用性 |
|---|---:|---|---|
| 文生视频 | 19 | 通过 | 通过 |
| 图生视频 | 23 | 通过 | 通过 |
| 全能参考生成视频 | 43 | 通过 | 通过 |

已确认存在并可被当前 ComfyUI 识别的核心资源包括：

- `minimax_h3_video_vae_fp16.safetensors`
- `minimax_h3_audio_vae_fp32.safetensors`
- `minimax_h3_fl2va_pruned_int8_convrot.safetensors`
- `minimax_h3_ref2va_pruned_int8_convrot.safetensors`
- `qwen3vl_32b_minimax_h3_int8_convrot.safetensors`

### 3.3 Blender 插件

已安装路径：

```text
C:\Users\23122\AppData\Roaming\Blender Foundation\
Blender\5.0\scripts\addons\flynotes_ai
```

当前版本：`1.3.3`。

已确认：

- 插件支持 Blender 4.0+。
- 已有模型、模式、任务、素材、摄像机输入、Workbench 视频及 VSE 能力。
- 已有自定义 API 地址配置。
- 已有动态模型配置机制。
- 在 Blender 5.0 独立测试中成功完成“注册 → 注销 → 重新加载 → 再注册”。
- 当前代码为纯 Python，具备热更新改造基础。

---

## 4. 产品目标

### 4.1 核心目标

1. 用户可以从桌面端启动、停止、重启和监控当前通用 ComfyUI。
2. 用户可以从桌面端直接使用 MiniMax H3 生成视频。
3. Blender 在桌面端关闭后仍能通过 Local Agent 生成视频。
4. MiniMax H3 在本地执行，Seedance、Grok 等通过 Local Agent 转发 Flynotes 云端。
5. 桌面端和 Blender 共用模型配置、任务、参数、日志和素材结果。
6. 后续本地工作流可以继续复用同一个 ComfyUI 运行时。
7. Blender 插件可以从桌面控制中心检查、安装、热更新和回滚。
8. H3 三套工作流必须在 Blender 中通过实际端到端验收。

### 4.2 成功指标

首发版本满足以下指标：

- 桌面端关闭后，本地或云端任务不中断。
- Local Agent 重启后能够恢复已提交任务。
- 本地 H3 提交不依赖 Flynotes 登录。
- 三个 H3 Blender 端到端测试通过率 100%。
- 生成结果 100% 进入统一素材库或被可靠索引。
- 插件纯 Python 小版本更新可以在 Blender 空闲时热加载。
- 热更新失败时能够自动恢复上一版本。
- 未知程序占用 8188 时，不误杀其他进程。

---

## 5. 非目标与首发边界

首发版本不包含：

- 通用 ComfyUI 节点图编辑器
- 任意第三方工作流市场
- 自动更新 ComfyUI 核心和全部自定义节点
- 自动下载所有模型
- 多台计算机分布式 GPU 调度
- 多用户局域网服务
- macOS/Linux 客户端
- 在桌面端嵌入原 Gradio 页面
- 对生成内容进行主观质量评分

首发期间锁定当前 ComfyUI 运行时快照。新增工作流必须经过依赖检查，不得自动升级当前依赖来解决兼容问题。

---

## 6. 目标用户与使用场景

### 6.1 目标用户

- 使用 Blender 制作 AI 视频或动画的个人创作者
- 需要本地 H3 和 Flynotes 云端模型统一入口的用户
- 需要管理 ComfyUI 但不希望直接操作节点图的用户
- 需要持续接收 Blender 插件更新的用户

### 6.2 核心场景

#### 场景 A：桌面端本地生成

用户打开桌面端，选择“MiniMax H3（本地）”，填写参数并提交。如果 ComfyUI 未运行，Local Agent 自动启动 8188。任务完成后视频进入素材库。

#### 场景 B：桌面端关闭后 Blender 本地生成

用户关闭桌面端，在 Blender 中选择“MiniMax H3（本地）”并提交。插件只连接 Local Agent。Local Agent 必要时启动 ComfyUI，任务继续执行并返回结果。

#### 场景 C：Blender 云端生成

用户在 Blender 选择 Seedance 或 Grok。Local Agent 检查 Flynotes 登录状态、上传素材、提交云端任务、下载结果并登记素材。

#### 场景 D：并发提交

桌面端和 Blender 同时提交本地 H3。两个任务进入同一个本地队列，按顺序执行；云端任务可并行。

#### 场景 E：插件更新

桌面端发现 GitHub 新版本。若 Blender 空闲，执行热更新；若正在渲染或编码，暂存更新并在空闲时应用；失败时自动回滚。

---

## 7. 总体架构

```text
Tauri + React 桌面端
        │
        │ HTTP / WebSocket
        ▼
Python Local Agent（唯一业务控制中心）
        ├── 进程管理器
        ├── 模型与工作流注册表
        ├── H3 工作流编译器
        ├── 任务调度器
        ├── ComfyUI Provider
        ├── Flynotes Provider
        ├── 素材库
        ├── Blender 兼容 API
        ├── 插件更新器
        └── SQLite / 日志 / 密钥存储
                  │
          ┌───────┴────────┐
          ▼                ▼
ComfyUI 8188         Flynotes Cloud
MiniMax H3           Seedance / Grok

Blender Flynotes AI 插件
        │
        └── 只连接 Local Agent
```

### 7.1 技术选型

| 组件 | 推荐技术 |
|---|---|
| 桌面壳 | Tauri 2 |
| 桌面 UI | React + TypeScript |
| 状态与请求 | TanStack Query + 轻量本地状态库 |
| 后台服务 | Python 3.12 + FastAPI + Uvicorn |
| 本地数据库 | SQLite WAL + Alembic |
| HTTP 客户端 | httpx |
| ComfyUI 事件 | WebSocket |
| 系统监控 | psutil + nvidia-ml-py |
| 视频信息与缩略图 | FFmpeg / ffprobe |
| 后台服务打包 | PyInstaller 或等价独立打包方案 |
| 插件更新 | GitHub Releases + SHA256 + Ed25519 签名 |

### 7.2 关键架构原则

- Local Agent 是唯一真相源。
- UI 不保存权威任务状态。
- Blender 不保存云端密钥。
- 工作流版本必须和任务绑定。
- 运行时目录与用户数据目录分离。
- 更新不得覆盖当前正在加载的插件代码。
- 本地服务只监听 `127.0.0.1`。

---

## 8. 运行时与生命周期设计

### 8.1 Local Agent

Local Agent 采用当前用户后台代理，而不是传统 Windows Service：

- 用户登录 Windows 后启动。
- 使用单实例命名锁。
- 桌面端启动时发现服务不存在，可拉起后台服务。
- 桌面端退出不结束 Local Agent。
- Local Agent 重启不应主动结束已存在的可信 ComfyUI 进程。

### 8.2 ComfyUI 启动命令

Local Agent 直接启动：

```text
walkingwithai\python.exe -s main.py
  --listen 127.0.0.1
  --port 8188
  --disable-metadata
  --output-directory <DataRoot>\generated
```

不得执行 `start.py` 或 `启动程序.bat`，因为二者属于原整合包启动逻辑，并会引入 Gradio。

### 8.3 进程识别

Local Agent 保存：

- PID
- 可执行文件绝对路径
- 工作目录
- 命令行摘要
- 启动时间
- 端口
- 运行时指纹

重连时必须同时校验 PID、路径和 8188 健康接口，不能只凭端口判断归属。

### 8.4 停止策略

ComfyUI 空闲时可以正常停止。

存在运行任务时提供：

- 等待当前任务完成后停止
- 取消任务并停止
- 放弃停止

强制结束仅放在高级故障处理入口。

### 8.5 7860 门禁

正式运行期间必须满足：

- Local Agent 不启动 7860。
- 桌面端不访问 7860。
- Blender 不访问 7860。
- 自动化验收检查 7860 没有被本产品进程监听。

---

## 9. 模型与工作流注册表

### 9.1 模型结构

```json
{
  "id": "minimax-h3-local",
  "displayName": "MiniMax H3（本地）",
  "provider": "comfyui",
  "mediaType": "video",
  "workflowId": "minimax-h3",
  "workflowVersion": "260803",
  "modes": ["text", "first_frame", "first_last", "reference"],
  "available": true,
  "requiresCloudAuth": false
}
```

### 9.2 工作流包

```text
workflows/
└── minimax-h3/
    └── 260803/
        ├── manifest.json
        ├── text-to-video.api.json
        ├── image-to-video.api.json
        ├── reference-to-video.api.json
        ├── parameter-schema.json
        ├── node-mapping.json
        ├── preview.png
        └── golden-fixtures/
```

### 9.3 工作流版本约束

- 提交任务时固定 `workflowVersion`。
- 配置更新不得修改已提交任务。
- 工作流升级必须新增版本目录。
- 旧版本至少保留到所有关联任务完成。
- 工作流包必须声明节点、模型和 ComfyUI 版本要求。

### 9.4 后续本地工作流

新工作流通过相同注册机制加入模型下拉框，名称后增加“（本地）”。

如果依赖与当前 ComfyUI 兼容，继续使用 8188；只有明确存在依赖冲突时，后续版本才引入多个运行配置。首发不实现多运行时。

---

## 10. H3 工作流编译器

### 10.1 输入参数

通用参数：

- `mode`
- `prompt`
- `width`
- `height`
- `duration`
- `steps`
- `seed`
- `refImageSize`
- `firstFrame`
- `lastFrame`
- `referenceImages[]`
- `referenceVideos[]`
- `referenceAudios[]`

### 10.2 校验规则

- 宽高必须为 32 的倍数。
- Seed 为 `-1` 时解析为实际随机 Seed。
- 实际 Seed 必须写回任务记录。
- 图生视频必须存在首帧。
- 尾帧可选。
- 参考图最多 9 张。
- 参考视频最多 3 个。
- 独立参考音频最多 3 个。
- 所有素材必须先复制或链接到安全的任务暂存目录。
- 禁止把用户路径直接拼入工作流。
- 文件名必须进行路径穿越和非法字符校验。

### 10.3 编译职责

- 复制原始 API 工作流模板。
- 注入参数。
- 设置唯一输出前缀。
- 连接实际素材节点。
- 断开并裁剪未使用的可选节点。
- 返回可直接提交到 `/prompt` 的 JSON。
- 返回最终 Seed、输出节点和编译摘要。

### 10.4 等价性测试

编译器必须通过与原工作流构建函数的金标准对比：

- 固定 Seed
- 随机 Seed
- 首帧
- 首尾帧
- 1/9 张图片
- 1/3 个视频
- 1/3 个音频
- 混合参考素材
- 不同尺寸、时长和步数

对比时规范化随机 Seed、输出前缀和任务 ID，其他 JSON 内容必须一致。

---

## 11. 任务系统

### 11.1 状态机

```text
created
→ validating
→ staging_inputs
→ queued
→ running
→ succeeded | failed | cancelled
```

补充状态：

- `waiting_runtime`：等待 ComfyUI 启动
- `waiting_auth`：等待 Flynotes 登录
- `recovering`：Local Agent 重启后恢复中
- `downloading`：云端结果下载中

### 11.2 任务标识

每个任务具有：

- Local Agent `jobId`
- 客户端 `clientRequestId`
- 本地任务的 ComfyUI `promptId`
- 云端任务的 Flynotes `remoteJobId`

`clientRequestId` 用于避免网络重试导致重复提交。

### 11.3 本地队列

- 默认本地 GPU 并发数为 1。
- 桌面端和 Blender 共用同一个队列。
- 云端任务不占用本地 GPU 队列。
- 原生 ComfyUI 手动任务显示为“外部任务”，Local Agent 不将其冒充为自己的任务。

### 11.4 进度

Local Agent 监听 ComfyUI WebSocket：

- `executing`
- `progress`
- `executed`
- `execution_error`

统一推送给桌面端和 Blender：

```json
{
  "jobId": "job_xxx",
  "status": "running",
  "progress": 42,
  "currentNode": "SamplerCustomAdvanced",
  "message": "正在采样"
}
```

### 11.5 恢复

Local Agent 重启后：

1. 查询数据库中的未终态任务。
2. 查询 ComfyUI `/queue`。
3. 查询 `/history/{promptId}`。
4. 已完成则补录结果。
5. 仍在运行或排队则恢复监听。
6. 无任何记录且进程已中断则标记失败，并保留诊断原因。

---

## 12. 素材库

### 12.1 目录

用户数据不得默认放在可替换的整合包版本目录中。

```text
<DataRoot>/
├── generated/
│   ├── local/
│   └── cloud/
├── thumbnails/
├── staging/
├── imports/
├── logs/
└── database/
```

### 12.2 素材元数据

- 素材 ID
- 任务 ID
- 本地绝对路径
- 来源：桌面端/Blender/导入
- Provider：ComfyUI/Flynotes
- 模型 ID
- 工作流版本
- 模式
- 提示词
- 输入素材引用
- 用户参数
- 解析后参数
- 实际 Seed
- 宽度、高度、帧率、时长
- 音视频流信息
- 文件大小
- SHA256
- 创建时间
- 缩略图路径

### 12.3 结果处理

- 本地结果直接登记，不重复下载。
- 云端结果完成后立即下载到统一目录。
- Blender 在同机环境优先使用 `localPath` 加入 VSE。
- 现有 H3 `output` 和 Flynotes Assets 以“导入索引”方式接入，不强制搬迁。

---

## 13. 桌面端需求

### 13.1 全局区域

顶部显示：

- Local Agent 状态
- ComfyUI 状态
- GPU/显存
- 当前任务数量
- 全局通知
- 设置入口

### 13.2 Tab 1：ComfyUI 服务

功能需求：

- 发现并配置当前整合包路径
- 启动、停止和重启 ComfyUI
- 显示 PID、路径、端口、版本和启动时间
- GPU、显存、CPU、内存
- 当前任务和队列
- H3 必需模型和节点检查
- 实时日志
- 打开原生 ComfyUI
- 导出诊断包
- 端口冲突提示
- 非本系统进程保护

健康状态：

- `Stopped`
- `Starting`
- `Ready`
- `Warning`
- `Error`
- `Stopping`

与 H3 无关的自定义节点失败只产生 Warning，不阻止 H3 生成。

### 13.3 Tab 2：视频生成

页面顶部只提供一个模型下拉框。

H3 参数面板：

- 模型：MiniMax H3（本地）
- 模式：文生、首帧、首尾帧、全能参考
- 提示词
- 首帧和尾帧
- 参考图片、视频和音频
- 宽度、高度
- 时长
- 采样步数
- Seed
- 参考图处理尺寸
- 开始生成
- 取消任务
- 进度、当前节点和日志
- 视频结果预览

如果 ComfyUI 未运行，默认在提交时自动启动；该行为可以在设置中关闭。

### 13.4 Tab 3：素材库

- 网格和列表视图
- 视频播放
- 模型、来源、状态和日期筛选
- 搜索提示词和任务编号
- 查看完整参数
- 使用相同参数重新生成
- 打开文件位置
- 加入 Blender VSE
- 收藏、标签
- 导入现有目录
- 安全删除

### 13.5 Tab 4：插件列表

- 检测 Blender 安装版本
- 检测插件目录和版本
- 显示活动 Blender 实例
- 手动检查 GitHub 更新
- 查看发布说明
- 下载和校验更新
- 热更新
- 下次启动更新
- 回滚
- 打开插件目录

### 13.6 设置

设置不作为第五个 Tab，通过右上角进入：

- 数据目录
- ComfyUI 路径
- 开机启动
- 自动启动 ComfyUI
- Flynotes 账号
- 网络代理
- 更新渠道
- 日志级别
- 高级诊断

---

## 14. Blender 插件需求

### 14.1 保留功能

- 当前视频生成界面
- 模型和生成方式
- 提示词
- 本地素材
- 摄像机输入
- Workbench 视频
- 任务中心
- 下载/使用结果
- 自动加入 VSE

### 14.2 API 设置

API 地址放入插件高级设置：

```text
高级设置 ▼

本地控制中心 API
http://127.0.0.1:17980/api/v1

[测试连接] [恢复默认]

请求超时
调试日志
```

普通用户不需要修改 API。插件不得在 Local Agent 不可用时偷偷直连 Flynotes。

### 14.3 登录规则

- MiniMax H3（本地）不要求 Flynotes 登录。
- 云端模型需要 Flynotes 登录。
- Flynotes Token 和设备密钥由 Local Agent 保存。
- 插件收到 `AUTH_REQUIRED` 后再显示登录操作。

### 14.4 模型配置

插件通过 Local Agent 获取模型配置。H3 显示名必须为：

```text
MiniMax H3（本地）
```

插件当前支持的 `aspectRatio`、`resolution`、`duration` 继续保留。Local Agent 将其映射为 H3 的实际宽高和时长。

插件未展示的 H3 高级参数由同一模型配置提供默认值，不能在插件代码里另写一套默认值。

### 14.5 任务恢复

- 插件加载时从 Local Agent 拉取当前 Blender 客户端关联任务。
- 插件重新加载后恢复任务列表。
- Blender 关闭不取消任务。
- Blender 重新打开后可以继续查看和使用结果。

---

## 15. Blender 插件热更新

### 15.1 目标结构

```text
flynotes_ai/
├── __init__.py
├── bootstrap.py
├── current.json
└── versions/
    ├── 1.3.3/
    └── 1.3.4/
```

稳定加载器尽量不更新；业务代码放入版本目录。

### 15.2 Release 清单

```json
{
  "version": "1.3.4",
  "minBlender": "4.0",
  "maxBlender": "5.x",
  "minAgentVersion": "1.0.0",
  "hotReload": true,
  "restartRequired": false,
  "sha256": "...",
  "signature": "..."
}
```

### 15.3 更新流程

1. Local Agent 查询 GitHub Releases。
2. 下载到暂存目录。
3. 校验 SHA256 和 Ed25519 签名。
4. 解压到新版本目录，不覆盖旧版。
5. Blender 插件通过心跳上报实例状态。
6. 空闲实例在 Blender 主线程执行旧版 `unregister()`。
7. 加载并注册新版。
8. 成功后原子更新 `current.json`。
9. 失败则注销不完整新版并恢复旧版。

### 15.4 禁止热更新条件

- Workbench 正在渲染
- 视频编码中
- Modal Operator 运行中
- 正在提交或下载
- 更新包含 `.pyd` 或 DLL
- Blender API 不兼容
- Release 标记必须重启

这些情况改为“等待空闲”或“下次启动更新”。

### 15.5 首次迁移

当前 1.3.3 不是稳定加载器结构。首次迁移到新版加载器允许要求 Blender 重启一次；后续纯 Python 小版本更新支持热加载。

---

## 16. API 设计

### 16.1 桌面端核心接口

```text
GET  /v1/health
GET  /v1/models
GET  /v1/jobs
POST /v1/jobs
GET  /v1/jobs/{jobId}
POST /v1/jobs/{jobId}/cancel
GET  /v1/assets
GET  /v1/assets/{assetId}
GET  /v1/runtime/comfyui
POST /v1/runtime/comfyui/start
POST /v1/runtime/comfyui/stop
POST /v1/runtime/comfyui/restart
GET  /v1/plugins
POST /v1/plugins/check-updates
POST /v1/plugins/{pluginId}/stage-update
POST /v1/plugins/{pluginId}/apply-update
POST /v1/plugins/{pluginId}/rollback
WS   /v1/events
```

### 16.2 Blender 兼容接口

```text
GET  /api/v1/blender/config/manifest
GET  /api/v1/blender/config/{version}
POST /api/v1/blender/uploads
POST /api/v1/blender/jobs
GET  /api/v1/blender/jobs
GET  /api/v1/blender/jobs/{jobId}
GET  /api/v1/blender/jobs/{jobId}/outputs/{index}
```

### 16.3 提交任务示例

```json
{
  "clientRequestId": "uuid",
  "client": {
    "type": "blender",
    "version": "1.4.0",
    "instanceId": "blender-instance-uuid"
  },
  "modelId": "minimax-h3-local",
  "mode": "first_last",
  "prompt": "...",
  "parameters": {
    "width": 480,
    "height": 832,
    "duration": 5,
    "steps": 20,
    "seed": -1,
    "refImageSize": "match"
  },
  "inputs": [
    {"uploadId": "upload_1", "role": "first_frame"},
    {"uploadId": "upload_2", "role": "last_frame"}
  ]
}
```

### 16.4 错误码

| 错误码 | 含义 |
|---|---|
| `AGENT_NOT_READY` | Local Agent 尚未准备完成 |
| `COMFY_NOT_RUNNING` | ComfyUI 未运行且自动启动关闭 |
| `COMFY_START_FAILED` | ComfyUI 启动失败 |
| `COMFY_PORT_CONFLICT` | 8188 被未知程序占用 |
| `WORKFLOW_UNAVAILABLE` | 工作流不可用 |
| `MISSING_NODE` | 必需节点缺失 |
| `MISSING_MODEL` | 必需模型缺失 |
| `INVALID_PARAMETER` | 参数不符合模型约束 |
| `INVALID_INPUT` | 输入素材无效 |
| `AUTH_REQUIRED` | 云端模型需要登录 |
| `REMOTE_PROVIDER_ERROR` | Flynotes 云端错误 |
| `JOB_NOT_CANCELLABLE` | 当前任务状态不允许取消 |
| `PLUGIN_BUSY` | Blender 插件当前不能热更新 |
| `PLUGIN_UPDATE_FAILED` | 插件更新失败并已回滚 |

---

## 17. 数据模型

### 17.1 主要表

#### `jobs`

- `id`
- `client_request_id`
- `client_type`
- `client_instance_id`
- `model_id`
- `provider`
- `workflow_id`
- `workflow_version`
- `mode`
- `status`
- `progress`
- `prompt_id`
- `remote_job_id`
- `user_parameters_json`
- `resolved_parameters_json`
- `actual_seed`
- `error_code`
- `error_message`
- `created_at`
- `started_at`
- `finished_at`

#### `job_inputs`

- `id`
- `job_id`
- `role`
- `original_path`
- `staged_path`
- `sha256`
- `media_info_json`

#### `assets`

- `id`
- `job_id`
- `path`
- `thumbnail_path`
- `media_type`
- `width`
- `height`
- `duration`
- `fps`
- `has_audio`
- `size_bytes`
- `sha256`
- `metadata_json`
- `created_at`

#### `plugin_installations`

- `id`
- `blender_version`
- `addon_path`
- `installed_version`
- `staged_version`
- `status`
- `last_check_at`

#### `blender_instances`

- `instance_id`
- `blender_version`
- `plugin_version`
- `state`
- `active_job_id`
- `last_heartbeat_at`

### 17.2 数据库要求

- SQLite 使用 WAL。
- 数据库归 Local Agent 独占管理。
- 不复用 ComfyUI 的 `comfyui.db`。
- 数据库迁移使用 Alembic。
- 云端密钥不得明文存入 SQLite。

---

## 18. 安全要求

- Local Agent 和 ComfyUI 只监听 `127.0.0.1`。
- Local Agent 使用本机配对令牌。
- 配对令牌保存到仅当前用户可读的位置。
- Flynotes 凭据使用 Windows Credential Manager 或 DPAPI。
- 日志自动脱敏 Token、设备密钥和授权头。
- 上传文件限制类型、大小和路径。
- 所有暂存文件使用服务生成的安全文件名。
- GitHub 插件包必须校验签名。
- 未知 8188 进程不得被自动结束。
- CORS 只允许桌面端预期来源；Blender 使用 Token 请求。

---

## 19. 日志与可观测性

日志分为：

- Local Agent 日志
- ComfyUI 启动日志
- ComfyUI 任务事件
- Flynotes 请求日志
- Blender 插件日志
- 插件更新日志

每条任务日志至少包含：

- `jobId`
- `clientRequestId`
- `provider`
- `modelId`
- `workflowVersion`
- 时间
- 事件类型

桌面端支持按任务过滤日志。诊断包应包括配置摘要、版本、节点检查、最近日志和任务状态，但不得包含云端密钥及用户未授权的完整素材。

---

## 20. 非功能需求

### 20.1 可靠性

- Local Agent 崩溃恢复后能够重建任务状态。
- 桌面端崩溃不影响任务。
- Blender 崩溃不影响已提交任务。
- 插件更新失败自动回滚。

### 20.2 性能

- Local Agent 健康接口 P95 小于 200ms。
- 模型列表 P95 小于 300ms。
- 普通任务提交在不含大文件复制时 P95 小于 1s。
- 大文件上传和暂存显示进度。
- 桌面端日志流不得造成明显 UI 卡顿。

### 20.3 兼容性

- 首发 Windows 10/11。
- Blender 4.0+。
- 强制验收 Blender 5.0.0。
- 当前 RTX 3090 24GB 作为首发 GPU 验收环境。

### 20.4 可维护性

- 桌面端和 Blender 共用模型 schema。
- OpenAPI 生成桌面端 TypeScript 客户端。
- Provider、WorkflowCompiler、AssetStore 和 Updater 之间保持接口隔离。
- 任务状态迁移必须有单元测试。

---

## 21. 测试策略

### 21.1 测试层级

| 层级 | 运行频率 | 是否需要 GPU |
|---|---|---|
| 单元测试 | 每次提交 | 否 |
| API 契约测试 | 每次提交 | 否 |
| 工作流金标准测试 | 每次提交 | 否 |
| Fake ComfyUI/Flynotes 集成测试 | 每次提交 | 否 |
| ComfyUI 节点和模型预检 | 每个构建/环境 | 否或低 |
| Blender 插件注册/重载测试 | 每个插件构建 | 否 |
| Blender H3 GPU 端到端测试 | 发布候选版本 | 是 |
| 云端 Provider 冒烟测试 | 发布候选版本 | 否，本身使用云端 |
| 恢复、更新和故障注入 | 发布候选版本 | 部分需要 |

### 21.2 单元测试

必须覆盖：

- 参数校验
- 宽高倍数校验
- Seed 解析和持久化
- H3 三模式编译
- 可选素材节点裁剪
- 文件名安全处理
- 状态机合法迁移
- 幂等提交
- ComfyUI 事件映射
- 任务恢复判定
- 云端错误映射
- 插件更新版本比较
- Release 签名校验
- 回滚逻辑

### 21.3 工作流金标准测试

每次修改 H3 编译器时运行。除允许变化的任务 ID、输出前缀和随机 Seed 外，编译 JSON 必须和冻结基线一致。

### 21.4 API 契约测试

- 桌面端 OpenAPI 客户端与服务端一致。
- Blender 兼容接口保持当前插件需要的字段。
- 旧版插件访问不支持的新服务时返回明确升级提示。
- 同一 `clientRequestId` 重试不会创建重复任务。

### 21.5 Blender 插件重载测试

在 Blender 后台模式执行：

1. 导入插件。
2. `register()`。
3. `unregister()`。
4. 重新加载模块。
5. 再次 `register()`。
6. 再次 `unregister()`。

不得出现重复类、残留 timer、残留 handler 或未释放预览资源。

---

## 22. Blender 三工作流强制端到端测试

### 22.1 测试环境

| 项目 | 要求 |
|---|---|
| OS | Windows 10/11 |
| Blender | 5.0.0，必须使用真实 Blender 进程 |
| 插件 | 当前发布候选版本 |
| Local Agent | 当前发布候选版本 |
| ComfyUI | 当前冻结的 H3 整合包运行时 |
| GPU | RTX 3090 24GB 首发基线 |
| 本地端口 | Agent 17980，ComfyUI 8188，7860 不得监听 |
| Flynotes 登录 | H3 测试不得依赖 Flynotes 登录 |

### 22.2 测试夹具

仓库需提供稳定测试素材：

```text
tests/fixtures/h3/
├── first_frame.png
├── last_frame.png
├── reference_1.png
├── reference_2.png
├── reference_video.mp4
├── reference_audio.wav
└── expected/
```

要求：

- 图片可以公开分发，不包含隐私内容。
- 参考视频短小、可解码、包含或不包含音轨均需在元数据中明确。
- 独立音频为标准 WAV。
- 测试素材使用 SHA256 固定版本。

### 22.3 成功定义

“在 Blender 中成功跑通”必须同时满足：

1. 在 Blender Flynotes AI 面板中选择 `MiniMax H3（本地）`。
2. 从 Blender 提交任务，而不是桌面端代为提交。
3. 插件收到 Local Agent 返回的任务 ID。
4. 任务进入 ComfyUI 8188 队列。
5. 插件能够显示排队、运行和完成状态。
6. 任务最终状态为 `succeeded`。
7. 输出 MP4 存在且 `ffprobe` 可解析。
8. 输出宽高与请求一致。
9. 输出时长在目标值允许误差内。
10. 视频流可解码；H3 工作流预期存在音频时，音频流必须存在。
11. 任务记录包含实际 Seed、工作流版本和完整解析参数。
12. 视频登记到统一素材库。
13. Blender 能将结果加入 VSE。
14. VSE Movie Strip 路径指向有效本地文件。
15. Blender 中可以正常播放或定位视频帧。
16. 测试过程中没有启动或访问 7860。

### 22.4 E2E-BL-H3-001：文生视频

**目的**：验证 Blender → Local Agent → H3 文生 API 工作流 → ComfyUI → 素材库 → Blender VSE 全链路。

**参数建议**：

```text
模型：MiniMax H3（本地）
模式：文生视频
宽度：480
高度：832
时长：5 秒
步数：20
Seed：固定测试 Seed
```

**步骤**：

1. 确认 Local Agent 运行。
2. 关闭桌面端，证明 Blender 不依赖桌面 UI。
3. 保证 Flynotes 未登录或云端网络不可用。
4. 打开 Blender 5.0 和 Flynotes AI 面板。
5. 选择 `MiniMax H3（本地）`。
6. 选择文生视频。
7. 输入固定测试提示词。
8. 提交任务。
9. 观察插件任务状态。
10. 等待完成并将结果加入 VSE。
11. 使用 ffprobe 验证输出。

**预期结果**：满足 22.3 全部成功条件。本地 H3 不触发 Flynotes 登录。

### 22.5 E2E-BL-H3-002：首尾帧视频

**目的**：验证首帧、尾帧上传、角色映射、H3 图生工作流及 Blender 结果使用。

**参数建议**：

```text
模型：MiniMax H3（本地）
模式：首尾帧生成
首帧：first_frame.png
尾帧：last_frame.png
宽度：480
高度：832
时长：5 秒
步数：20
Seed：固定测试 Seed
```

**步骤**：

1. 在 Blender 中选择 H3 本地模型。
2. 选择首尾帧模式。
3. 从插件选择测试首帧和尾帧。
4. 输入固定提示词。
5. 提交任务。
6. 验证 Local Agent 中两个输入角色分别为 `first_frame` 和 `last_frame`。
7. 验证最终工作流的两个 LoadImage 节点使用本次任务暂存文件。
8. 等待完成。
9. 在 Blender 素材面板中选中结果并加入 VSE。
10. 使用 ffprobe 验证输出。

**预期结果**：满足 22.3 全部成功条件；工作流不得继续引用原整合包模板中的示例图片。

### 22.6 E2E-BL-H3-003：全能参考生成视频

**目的**：验证图片、视频、音频混合参考输入及动态节点裁剪。

**输入**：

- `reference_1.png`
- `reference_2.png`
- `reference_video.mp4`
- `reference_audio.wav`

**提示词要求**：明确包含对应标签，例如：

```text
<Picture 1>、<Picture 2>、<Video 1>、<Audio 1>
```

**参数建议**：

```text
模型：MiniMax H3（本地）
模式：全能参考
参考图处理：match
宽度：480
高度：832
时长：5 秒
步数：20
Seed：固定测试 Seed
```

**步骤**：

1. 在 Blender 中选择全能参考模式。
2. 添加两张参考图片。
3. 添加一个参考视频。
4. 添加一个独立参考音频。
5. 输入带 Picture/Video/Audio 标签的提示词。
6. 提交任务。
7. 验证四个输入全部上传并绑定到正确角色。
8. 验证未使用的其余图片、视频和音频节点已断开或裁剪。
9. 等待完成。
10. 将结果加入 Blender VSE。
11. 验证输出视频和音频流。

**预期结果**：满足 22.3 全部成功条件；任务不得因为未使用的空参考槽而读取模板示例素材。

### 22.7 端到端证据包

每个测试必须保留：

- Blender 模型和模式选择截图
- Blender 任务运行状态截图
- Blender VSE 结果截图
- Local Agent 任务 JSON
- 最终 ComfyUI API 工作流 JSON
- ComfyUI `promptId`
- Local Agent 和 ComfyUI 相关日志
- ffprobe JSON
- 输出文件 SHA256
- 测试人、时间、软件版本和硬件信息

证据目录：

```text
test-results/<release-version>/blender-h3/
├── text-to-video/
├── first-last/
└── reference/
```

### 22.8 发布门禁

三个测试均为 `BLOCKER`：

- 全部通过：允许发布。
- 任意失败：禁止发布。
- 只在桌面端通过、未在 Blender 通过：视为失败。
- 只生成文件、未能加入 Blender VSE：视为失败。
- 通过 7860 或 Gradio 完成：视为失败。
- 依赖 Flynotes 登录才能运行本地 H3：视为失败。

### 22.9 发布候选测试记录

以下记录已在 0.1.0 发布候选、真实 Blender 5.0.0 与 RTX 3090 环境中执行；三个任务均由 Blender 插件提交并获得可播放、可加入 VSE 的本地结果。

| 测试 ID | 工作流 | 状态 | 执行人 | 执行时间 | Blender/插件/Agent 版本 | 证据目录 | 缺陷编号 |
|---|---|---|---|---|---|---|---|
| E2E-BL-H3-001 | 文生视频 | PASS | Codex 自动验收 | 2026-08-10 09:58 +08:00 | 5.0.0 / 1.4.0 / 0.1.0 | `test-results/0.1.0/blender-h3/text-to-video-full/` | 无 |
| E2E-BL-H3-002 | 首尾帧视频 | PASS | Codex 自动验收 | 2026-08-10 08:39 +08:00 | 5.0.0 / 1.4.0 / 0.1.0 | `test-results/0.1.0/blender-h3/first-last/` | 无 |
| E2E-BL-H3-003 | 全能参考视频 | PASS | Codex 自动验收 | 2026-08-10 08:46 +08:00 | 5.0.0 / 1.4.0 / 0.1.0 | `test-results/0.1.0/blender-h3/reference/` | 无 |

修改测试状态时必须遵守：

- `PASS`：22.3 的全部成功条件均满足，并存在完整证据包。
- `FAIL`：任务失败、结果无效、未进入 VSE 或任一强制条件不满足。
- `BLOCKED`：环境或依赖阻止执行；`BLOCKED` 不等同于通过，仍禁止发布。
- `NOT_RUN`：尚未执行；仍禁止发布。
- 不允许只填写人工结论而缺少日志、任务 JSON、ffprobe 和 Blender VSE 证据。

---

## 23. 其他关键测试

### 23.1 生命周期

- 桌面端关闭后任务继续。
- Blender 关闭后任务继续。
- Local Agent 重启后恢复任务。
- ComfyUI 已运行时 Local Agent 不重复启动。
- 8188 被未知进程占用时不误杀。

### 23.2 队列与取消

- 桌面端和 Blender 同时提交本地任务。
- 待执行任务取消。
- 当前任务中断。
- 云端和本地任务并行。
- 原生 ComfyUI 外部任务不被错误归属。

### 23.3 素材库

- 本地输出只登记一次。
- 云端结果下载并登记。
- 旧输出目录扫描。
- 缩略图生成失败不影响原视频。
- 文件缺失时显示清晰状态。
- Blender 使用本地路径，不重复复制大文件。

### 23.4 热更新

- Blender 空闲时热更新成功。
- Blender 渲染中暂缓更新。
- Modal Operator 运行时暂缓。
- 新版 `register()` 失败时回滚。
- 多个 Blender 实例分别更新。
- 旧版本目录在仍被使用时不删除。
- 包签名失败时拒绝安装。

### 23.5 安全

- 服务不监听外部网卡。
- 非法文件名不能穿越目录。
- 超大文件被限制。
- Token 不出现在日志。
- 未配对客户端访问受保护接口被拒绝。

---

## 24. 开发阶段与交付物

### 阶段 0：基线冻结

交付物：

- H3 三套 API 工作流
- 模型和节点清单
- 工作流金标准样本
- 当前运行时指纹
- 测试夹具

### 阶段 1：Local Agent 核心

交付物：

- 后台常驻和单实例
- ComfyUI 进程管理
- SQLite 数据库
- 日志和 WebSocket
- 健康检查
- 任务状态机

### 阶段 2：H3 本地引擎

交付物：

- H3WorkflowCompiler
- 三模式编译
- 输入暂存
- ComfyUI Provider
- 结果解析
- 工作流金标准测试

### 阶段 3：桌面端

交付物：

- 四个 Tab
- 模型驱动参数表单
- 任务和日志 UI
- 素材库
- 设置

### 阶段 4：Blender 接入

交付物：

- 本地 Agent API 默认配置
- 高级 API 设置
- H3 本地模型
- 本地 H3 无登录运行
- 任务恢复
- 本地素材加入 VSE

### 阶段 5：插件更新

交付物：

- 稳定加载器
- GitHub Release 检查
- 签名校验
- 热更新状态门禁
- 自动回滚

### 阶段 6：发布验收

交付物：

- 三个 Blender H3 端到端测试证据包
- 生命周期和恢复测试报告
- 插件热更新报告
- 已知问题列表
- 发布版本清单

---

## 25. Definition of Done

产品首发必须同时满足：

- [x] Local Agent 可以独立后台运行。
- [x] 桌面端关闭后 Blender 可以继续使用。
- [x] ComfyUI 只由 Local Agent 管理并监听 8188。
- [x] 产品不启动、不访问 7860。
- [x] H3 三套工作流使用冻结 API JSON 直接提交。
- [x] 桌面端模型下拉显示 `MiniMax H3（本地）`。
- [x] Blender 模型下拉显示 `MiniMax H3（本地）`。
- [x] Blender API 地址位于高级设置。
- [x] 本地 H3 不要求 Flynotes 登录。
- [x] 云端模型通过 Flynotes Provider 路由。
- [x] 桌面端和 Blender 共用任务数据库。
- [x] 所有新生成视频进入统一素材库。
- [x] Local Agent 重启能够恢复任务。
- [x] 插件支持安全热更新或安全延期更新。
- [x] 插件更新失败自动回滚。
- [x] 文生视频在 Blender 中端到端通过。
- [x] 首尾帧视频在 Blender 中端到端通过。
- [x] 全能参考视频在 Blender 中端到端通过。
- [x] 三项测试均保存完整证据包。
- [x] 无发布阻断级缺陷。

---

## 26. 风险与控制

| 风险 | 等级 | 控制措施 |
|---|---|---|
| H3 动态参考节点迁移偏差 | 高 | 金标准编译对比 + Blender 实际 E2E |
| 自定义节点更新破坏工作流 | 高 | 首发冻结运行时 + 启动前依赖检查 |
| 多实例争用 ComfyUI 数据库 | 高 | 单实例锁 + PID/端口/路径联合校验 |
| Local Agent 重启丢失任务 | 高 | 持久化 promptId + queue/history 恢复 |
| 热更新残留 Blender 类或 timer | 高 | 稳定加载器 + 主线程更新 + 空闲门禁 + 回滚 |
| 本地 H3 被云端登录阻塞 | 中 | Provider 级鉴权，H3 明确 `requiresCloudAuth=false` |
| 大视频重复复制 | 中 | 统一素材根目录 + Blender 使用 localPath |
| 原生 ComfyUI 外部任务干扰 | 中 | 标记外部任务 + 取消前核验 promptId |
| GitHub 更新包被替换 | 高 | SHA256 + Ed25519 签名 |
| 非 H3 自定义节点启动失败 | 低/中 | H3 依赖单独分级，非关键故障只 Warning |

---

## 27. 待确认项

以下内容不阻塞核心架构，但开发前需确定：

1. 产品正式名称和图标。
2. 默认用户数据目录位置。
3. Blender 插件 GitHub 仓库及 Release 命名规范。
4. 插件签名私钥保管方式。
5. Flynotes 云端 API 的正式服务账号与测试账号。
6. H3 Blender 端到端测试使用的固定提示词和素材版权确认。
7. 是否默认开机启动 Local Agent。
8. 是否默认在提交 H3 时自动启动 ComfyUI。

这些配置必须通过配置文件或模型注册表管理，不得散落硬编码在桌面端和 Blender 插件中。
