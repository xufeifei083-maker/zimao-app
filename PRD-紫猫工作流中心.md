# 紫猫（Zimao）本地 AI 工作流中心 PRD

> 产品名称：紫猫（Zimao）本地 AI 工作流中心  
> 文档版本：1.0  
> 文档状态：实施基线  
> 目标平台：Windows 10/11  
> 桌面端：Tauri + React  
> 本地服务：Python Local Agent  
> 推理底座：固定版本 ComfyUI + Python  

---

## 1. 文档目的

本文档定义紫猫本地 AI 工作流中心的产品范围、用户流程、系统架构、远端资源组织、工作流包规范、安装与验证机制、测试体系及发布标准。

本产品不是开放式 ComfyUI 节点市场，也不允许软件自动分析和安装任意第三方依赖。所有可见工作流及其节点、模型、Python 依赖和版本均由紫猫维护、测试和发布。

产品目标可以概括为：

> 用户下载安装紫猫软件，在软件中选择工作流并点击“一键安装”；软件按照紫猫维护的清单自动检查、下载并安装缺少的运行环境、节点、模型和依赖，验证成功后用户即可直接使用。

---

## 2. 已确定的产品决策

| 项目 | 决策 |
|---|---|
| 品牌中文名 | 紫猫 |
| 品牌英文名及组织名 | Zimao |
| GitHub 仓库可见性 | 全部公开 |
| Hugging Face 模型策略 | 不重复上传模型，只引用现有官方或原作者模型仓库 |
| ComfyUI | 全部工作流共用一个固定版本 |
| Python | 全部工作流共用一个固定版本 |
| 自定义节点 | 共用一个 `custom_nodes` 目录 |
| 模型 | 共用一个模型目录，避免重复下载 |
| 工作流来源 | 仅允许紫猫审核并发布的工作流 |
| 依赖解析 | 不自动猜测；完全按照工作流 Manifest 执行 |
| 多运行时/多环境 | 首版不做 |
| 用户编辑节点图 | 首版不做 |
| 第三方工作流市场 | 首版不做 |

---

## 3. 产品背景

普通用户使用本地 ComfyUI 工作流时，常遇到以下问题：

- 不知道应该安装哪个版本的 ComfyUI 和 Python。
- 不知道工作流缺少哪些自定义节点。
- 不知道模型应该从哪里下载以及放入哪个目录。
- 节点或 Python 依赖版本不一致，导致启动失败。
- 模型体积巨大，下载中断后需要重新开始。
- 文件已存在但下载不完整，运行时才发现损坏。
- 工作流更新后，旧节点或旧模型无法继续使用。
- Blender 等外部软件需要单独配置生成服务。

紫猫通过“固定运行环境 + 受控工作流清单 + 一键安装 + 自动验证”解决上述问题。

---

## 4. 产品目标

### 4.1 核心目标

1. 用户安装紫猫后，可以在软件内浏览由紫猫发布的工作流。
2. 用户点击“一键安装”即可完成工作流所需资源的检查、下载、安装和验证。
3. 第一次安装本地工作流时，软件自动安装固定 ComfyUI/Python 运行环境。
4. 后续工作流复用已安装的运行环境、节点和模型，只下载缺少资源。
5. 用户无需打开 ComfyUI 或理解节点图即可完成生成。
6. 桌面端和 Blender 通过同一个 Local Agent 使用相同工作流、任务和素材。
7. 工作流资源损坏或被删除后，可以一键修复。
8. 工作流发布前必须通过干净环境安装和真实 GPU 生成测试。

### 4.2 成功指标

- 新用户从安装紫猫到完成首个工作流安装，不需要手工复制文件。
- 所有正式工作流在干净环境中的一键安装成功率达到 100%。
- 重复安装不会重复下载已经校验通过的模型和节点。
- 下载中断后可以继续，不把未完成文件识别为已安装。
- 工作流所声明节点在 ComfyUI `/object_info` 中的识别率达到 100%。
- 工作流每个正式模式至少有一条真实 GPU 端到端测试通过记录。
- 本地生成结果可以进入统一素材库，并可被 Blender 使用。

---

## 5. 非目标

首版不包含：

- 通用 ComfyUI 节点图编辑器。
- 用户导入任意第三方工作流。
- 用户手工填写 Git 仓库或模型下载地址。
- 自动分析未知工作流依赖。
- 自动解决节点或 Python 包冲突。
- 同时维护和运行多套 ComfyUI/Python 环境。
- 未经紫猫验证的节点或模型市场。
- 多机 GPU 调度。
- macOS 和 Linux 客户端。
- 自动评价生成内容的主观质量。

---

## 6. 目标用户

- 希望使用本地 AI 生成能力但不了解 ComfyUI 的创作者。
- 使用 Blender 制作 AI 视频、动画或素材的用户。
- 希望统一管理本地工作流、模型、任务和输出素材的用户。
- 不希望手工安装节点、Python 包和模型的用户。

### 6.1 最低硬件要求

紫猫首版产品最低硬件门槛为：

| 项目 | 最低要求 |
|---|---|
| 操作系统 | Windows 10/11 64 位 |
| GPU | 支持当前固定 CUDA Runtime 的 NVIDIA GPU |
| 显存 | 8 GB |
| 系统内存 | 16 GB |
| NVIDIA 驱动 | 与固定 CUDA Runtime 兼容；首版 CUDA 13 Runtime 要求 580 系列或更高 |
| 磁盘空间 | 由工作流安装计划按实际资源大小计算 |

上述数值是紫猫软件和基础 Runtime 的产品最低配置。每个工作流仍可在 Manifest 中声明自己的最低显存、最低内存和推荐配置；软件必须依据用户硬件与具体工作流要求决定是否允许安装和运行。

MiniMax H3 如果对外标记为支持 8 GB 显存、16 GB 内存，必须提供经过验证的低显存执行模式，并在真实最低配置电脑上完成全部正式模式测试。未经最低配置实测，不得仅根据开发机结果宣称兼容。

---

## 7. 核心用户流程

### 7.1 首次安装工作流

```text
下载安装紫猫
→ 打开“工作流中心”
→ 选择一个工作流
→ 查看功能、下载大小和磁盘需求
→ 点击“一键安装”
→ 检查固定运行环境
→ 下载缺少的运行环境、节点、模型和工作流包
→ 校验签名、文件大小和 SHA256
→ 安装到正式目录
→ 启动 ComfyUI
→ 检查节点和模型
→ 工作流状态变为“可以使用”
→ 用户点击“立即使用”
```

### 7.2 后续安装其他工作流

```text
选择新工作流
→ 检查已有资源
→ 复用相同 Runtime
→ 复用已经存在的节点和模型
→ 仅下载缺失资源
→ 安装并验证
```

### 7.3 生成流程

```text
选择工作流和模式
→ 根据参数 Schema 展示表单
→ 用户填写提示词、参数并选择素材
→ Local Agent 校验和暂存输入
→ 注入工作流 API JSON
→ 提交到 ComfyUI
→ 监听进度
→ 收集输出文件
→ 写入统一素材库
→ 桌面端或 Blender 使用结果
```

### 7.4 一键修复

```text
发现节点、模型或工作流缺失/损坏
→ 状态显示“需要修复”
→ 用户点击“一键修复”
→ 重新读取原 Manifest
→ 只下载缺失或校验失败的资源
→ 重新安装和验证
→ 恢复“可以使用”
```

---

## 8. 总体架构

```text
紫猫 Tauri + React 桌面端
        │
        │ HTTP / WebSocket
        ▼
Python Local Agent（唯一业务控制中心）
        ├── 工作流目录客户端
        ├── Manifest 解析器
        ├── 资源检查器
        ├── 断点下载器
        ├── Runtime 安装器
        ├── 节点/模型/依赖安装器
        ├── 签名与 SHA256 校验器
        ├── 工作流注册表
        ├── 任务调度器
        ├── ComfyUI 进程管理器
        ├── 素材库
        └── SQLite / 日志
                 │
                 ▼
固定 ComfyUI + Python Runtime
        ├── custom_nodes
        ├── extra_model_paths.yaml
        └── API 工作流执行

Blender 紫猫插件
        └── 只连接 Local Agent
```

### 8.1 架构原则

- Local Agent 是工作流、安装状态、任务和素材的唯一真实来源。
- 桌面端和 Blender 不直接连接 ComfyUI。
- 工作流只使用紫猫发布的 Manifest。
- ComfyUI/Python Runtime 在同一产品版本中固定。
- 模型集中存储，跨工作流复用。
- 下载、解压和安装必须经过暂存目录，不能直接污染正式目录。
- 任务提交时绑定工作流 ID 和版本。

---

## 9. 远端资源组织

### 9.1 GitHub 组织

计划创建公开组织：

```text
github.com/Zimao
```

组织显示名称：

```text
紫猫 Zimao
```

### 9.2 GitHub 公开仓库

#### `xufeifei083-maker/zimao-app`

包含：

- Tauri + React 桌面端。
- Python Local Agent。
- Blender 插件。
- 安装、下载、任务和素材系统。
- 自动化测试和构建脚本。

#### `xufeifei083-maker/zimao-workflows`

包含：

- 工作流目录。
- Catalog 和 Manifest Schema。
- 工作流 JSON、参数 Schema、节点映射和测试样例。
- 工作流发布、校验、哈希计算和签名工具。
- GitHub Release 中的工作流包、节点 ZIP 和必要 wheel。

#### `xufeifei083-maker/zimao-runtime`

包含：

- Runtime 构建脚本。
- ComfyUI/Python/PyTorch/FFmpeg 版本锁定清单。
- Runtime Manifest。
- GitHub Release 中的 Runtime 压缩分卷。

### 9.3 Hugging Face 策略

紫猫首版不重新上传第三方模型，也不创建模型副本。

工作流 Manifest 直接引用：

- 模型官方 Hugging Face 仓库；或
- 模型原作者维护的 Hugging Face 仓库。

每个模型引用必须记录：

- `repo`：仓库 ID。
- `revision`：完整 commit hash，禁止使用 `main`。
- `file`：仓库内文件路径。
- `installTo`：本地模型目录相对路径。
- `size`：文件大小。
- `sha256`：目标文件哈希。
- `licenseUrl`：许可证地址。
- `gated`：是否需要用户同意模型条款并登录 Hugging Face。

如果某个模型需要访问授权，软件必须明确提示用户在 Hugging Face 完成授权；紫猫不得绕过模型许可或分发限制。

---

## 10. 远端目录结构

### 10.1 `zimao-workflows`

```text
zimao-workflows/
├── catalog/
│   ├── staging.json
│   └── production.json
├── schemas/
│   ├── catalog.schema.json
│   └── workflow-manifest.schema.json
├── workflows/
│   └── minimax-h3/
│       ├── manifest.json
│       ├── parameter-schema.json
│       ├── node-mapping.json
│       ├── text-to-video.api.json
│       ├── image-to-video.api.json
│       ├── reference-to-video.api.json
│       ├── preview.png
│       └── tests/
│           ├── cases.json
│           └── inputs/
└── tools/
    ├── validate_manifest.py
    ├── calculate_hashes.py
    ├── sign_manifest.py
    └── build_workflow_package.py
```

### 10.2 `zimao-runtime`

```text
zimao-runtime/
├── runtime-manifest.json
├── runtime-lock.json
├── requirements-lock.txt
├── build/
└── tools/
```

### 10.3 Release 命名

```text
工作流 Release：minimax-h3-v1.0.0
Runtime Release：win-nvidia-2026.08.1
应用 Release：v0.2.0
```

工作流 Release Assets：

```text
minimax-h3-v1.0.0.zip
comfyui-minimax-h3-v1.0.0.zip
manifest.json
manifest.sig
checksums.sha256
```

---

## 11. Catalog 规范

软件通过 Catalog 获取可见工作流。生产环境和测试环境分开：

```text
staging.json     内部及发布前测试
production.json  正式用户
```

示例：

```json
{
  "schemaVersion": 1,
  "catalogVersion": "2026.08.1",
  "runtime": {
    "id": "win-nvidia",
    "version": "2026.08.1",
    "manifestUrl": "https://github.com/xufeifei083-maker/zimao-runtime/releases/download/win-nvidia-2026.08.1/runtime-manifest.json",
    "signatureUrl": "https://github.com/xufeifei083-maker/zimao-runtime/releases/download/win-nvidia-2026.08.1/runtime-manifest.sig"
  },
  "workflows": [
    {
      "id": "minimax-h3",
      "version": "1.0.0",
      "name": "MiniMax H3 视频生成",
      "description": "支持文生、首帧、首尾帧和全能参考生成",
      "manifestUrl": "https://github.com/xufeifei083-maker/zimao-workflows/releases/download/minimax-h3-v1.0.0/manifest.json",
      "signatureUrl": "https://github.com/xufeifei083-maker/zimao-workflows/releases/download/minimax-h3-v1.0.0/manifest.sig"
    }
  ]
}
```

Catalog 自身也必须签名。客户端安装包内置紫猫发布公钥。

---

## 12. 工作流 Manifest 规范

Manifest 是工作流安装和验证的唯一权威清单。

```json
{
  "schemaVersion": 1,
  "id": "minimax-h3",
  "version": "1.0.0",
  "name": "MiniMax H3 视频生成",
  "runtimeVersion": "2026.08.1",
  "package": {
    "url": "https://github.com/xufeifei083-maker/zimao-workflows/releases/download/minimax-h3-v1.0.0/minimax-h3-v1.0.0.zip",
    "size": 1200000,
    "sha256": "完整SHA256"
  },
  "modes": {
    "text": "text-to-video.api.json",
    "first_frame": "image-to-video.api.json",
    "first_last": "image-to-video.api.json",
    "reference": "reference-to-video.api.json"
  },
  "nodes": [
    {
      "id": "comfyui-minimax-h3",
      "version": "1.0.0",
      "url": "https://github.com/xufeifei083-maker/zimao-workflows/releases/download/minimax-h3-v1.0.0/comfyui-minimax-h3-v1.0.0.zip",
      "installTo": "custom_nodes/ComfyUI-MiniMax-H3",
      "size": 125000000,
      "sha256": "完整SHA256"
    }
  ],
  "pythonWheels": [],
  "models": [
    {
      "id": "minimax-h3-video-vae",
      "source": "huggingface",
      "repo": "模型官方或原作者仓库",
      "revision": "完整Hugging-Face-commit-hash",
      "file": "vae/minimax_h3_video_vae_fp16.safetensors",
      "installTo": "vae/minimax_h3_video_vae_fp16.safetensors",
      "size": 1234567890,
      "sha256": "完整SHA256",
      "licenseUrl": "模型许可证地址",
      "gated": false
    }
  ],
  "hardware": {
    "minimumVramGB": 8,
    "minimumRamGB": 16,
    "recommendedVramGB": 24,
    "recommendedRamGB": 32,
    "lowMemoryMode": true
  },
  "requiredNodeClasses": [
    "MiniMaxH3ImageToVideo",
    "MiniMaxH3ReferenceToVideo",
    "SamplerCustomAdvanced",
    "SaveVideo"
  ],
  "parameters": "parameter-schema.json",
  "bindings": "node-mapping.json"
}
```

### 12.1 强制约束

- GitHub 资源必须使用固定 Release 版本。
- Hugging Face 必须使用完整 commit hash。
- 正式资源不得引用 `main`。
- 实际资源不得引用 GitHub `latest`。
- 每个文件必须声明大小和 SHA256。
- 安装路径必须为允许目录内的相对路径。
- 禁止 `..`、绝对路径和路径穿越。
- Manifest 必须通过 JSON Schema 校验和签名校验。
- 每个本地工作流必须声明最低显存和最低内存。
- 宣称支持低显存模式的工作流必须具有对应的真实硬件测试记录。

---

## 13. 固定 Runtime

固定 Runtime 包含：

- Python 3.12 的具体补丁版本。
- ComfyUI 的固定 commit。
- PyTorch、torchvision、torchaudio 固定版本。
- 对应 CUDA Runtime。
- xformers 等基础加速依赖。
- FFmpeg/ffprobe 固定版本。
- 基础自定义节点和 Python 包。
- 固定启动参数。

Runtime ID 示例：

```text
win-nvidia-2026.08.1
```

Runtime 压缩包超过 GitHub Release 单文件限制时，发布为分卷：

```text
runtime-2026.08.1.part01
runtime-2026.08.1.part02
runtime-2026.08.1.part03
runtime-manifest.json
runtime-manifest.sig
checksums.sha256
```

下载完成并校验所有分卷后才能合并和解压。

首版只有一个活动 Runtime。升级时可以安装到新目录并在验证成功后切换 `current.json`，但不会同时运行多套 ComfyUI。

---

## 14. 本地目录结构

```text
%LOCALAPPDATA%\ZimaoAI\
├── bin/
│   └── zimao-local-agent.exe
├── runtime/
│   ├── 2026.08.1/
│   │   ├── python/
│   │   ├── comfyui/
│   │   │   └── custom_nodes/
│   │   └── ffmpeg/
│   └── current.json
├── models/
│   ├── checkpoints/
│   ├── diffusion_models/
│   ├── vae/
│   ├── text_encoders/
│   ├── clip_vision/
│   └── loras/
├── workflows/
│   └── minimax-h3/
│       └── 1.0.0/
├── downloads/
├── staging/
├── generated/
├── thumbnails/
├── logs/
└── database/
```

ComfyUI 使用 `extra_model_paths.yaml` 指向 `%LOCALAPPDATA%\ZimaoAI\models`。

---

## 15. 下载与安装机制

### 15.1 安装计划

Local Agent 解析 Manifest 后生成安装计划：

```json
{
  "workflowId": "minimax-h3",
  "runtimeRequired": true,
  "missingNodes": 1,
  "missingModels": 5,
  "missingWheels": 0,
  "downloadBytes": 37200000000,
  "requiredDiskBytes": 45000000000
}
```

桌面端必须在用户点击安装前展示下载量和磁盘需求。

生成安装计划前还必须检查：

- GPU 厂商和型号。
- 可用显存及总显存。
- 系统内存。
- NVIDIA 驱动版本。
- 当前硬件是否满足工作流 Manifest 的最低要求。

如果电脑满足紫猫基础要求但不满足某个工作流要求，紫猫仍可正常打开，但该工作流必须显示明确的不兼容原因。

### 15.2 下载要求

- 支持 HTTP Range 断点续传。
- 支持暂停、继续和取消。
- 支持网络中断后的自动重试。
- 显示当前文件、总进度、速度和预计剩余时间。
- 下载前检查磁盘空间。
- Hugging Face 下载必须正确处理 CDN 重定向。
- 下载中的文件统一使用 `.partial` 后缀。
- 下载完成后先验证大小和 SHA256，再进入 staging。
- SHA256 不一致时删除或隔离错误文件，不得进入正式目录。

### 15.3 安装顺序

```text
检查当前任务和 ComfyUI 状态
→ 下载并验证 Runtime（如需要）
→ 下载并验证工作流包
→ 下载并验证节点包
→ 下载并验证 Python wheels
→ 下载并验证模型
→ 停止 ComfyUI
→ 安装到 staging
→ 原子移动到正式目录
→ 写入安装记录
→ 启动 ComfyUI
→ 执行可用性验证
```

### 15.4 Python 依赖

工作流特殊 Python 依赖优先发布固定 wheel，并使用离线方式安装：

```text
python -m pip install --no-index <wheel文件>
```

禁止安装时直接执行未固定版本的：

```text
pip install package-name
```

---

## 16. 安装后验证

安装完成后必须执行：

1. 启动 ComfyUI。
2. 等待 ComfyUI 健康接口可用。
3. 请求 `/object_info`。
4. 检查全部 `requiredNodeClasses`。
5. 检查模型文件位置、大小和 SHA256。
6. 检查工作流 JSON、参数 Schema 和节点映射可解析。
7. 检查工作流映射中引用的节点 ID 存在。
8. 将工作流状态更新为“可以使用”或“需要修复”。

仅检查目录存在不能视为安装成功。

---

## 17. 工作流状态机

用户可见状态：

```text
未安装
→ 正在检查
→ 等待下载
→ 正在下载
→ 正在安装
→ 正在验证
→ 可以使用
```

异常和补充状态：

```text
需要修复
安装失败
有更新
等待模型授权
```

错误码至少包含：

| 错误码 | 含义 |
|---|---|
| `CATALOG_INVALID` | Catalog 无效或验签失败 |
| `MANIFEST_INVALID` | Manifest 无效或验签失败 |
| `DISK_SPACE_INSUFFICIENT` | 磁盘空间不足 |
| `DOWNLOAD_FAILED` | 下载失败 |
| `HASH_MISMATCH` | SHA256 不一致 |
| `MODEL_ACCESS_REQUIRED` | 模型需要 Hugging Face 授权 |
| `RUNTIME_INSTALL_FAILED` | Runtime 安装失败 |
| `NODE_INSTALL_FAILED` | 节点安装失败 |
| `PYTHON_DEPENDENCY_FAILED` | Python wheel 安装失败 |
| `COMFY_START_FAILED` | ComfyUI 启动失败 |
| `MISSING_NODE` | ComfyUI 未识别必需节点 |
| `MISSING_MODEL` | 模型缺失或损坏 |
| `WORKFLOW_INVALID` | 工作流文件或映射无效 |

---

## 18. 桌面端界面

### 18.1 工作流中心

工作流卡片展示：

- 封面。
- 名称和版本。
- 简介和支持模式。
- 本地/云端标签。
- 安装状态。
- 下载大小。
- “一键安装”“立即使用”“修复”“更新”按钮。

未安装详情示例：

```text
MiniMax H3 视频生成

支持：文生 / 首帧 / 首尾帧 / 全能参考

运行环境：4.2 GB
自定义节点：180 MB
模型：32.6 GB
工作流：2 MB
合计：约 37 GB

[一键安装]
```

安装完成示例：

```text
✓ 运行环境正常
✓ 节点安装完成
✓ 模型安装完成
✓ 工作流检测通过

[立即使用]
```

### 18.2 下载管理

展示：

- 当前下载文件。
- 单文件与总体进度。
- 下载速度。
- 已下载/总大小。
- 预计剩余时间。
- 暂停、继续、取消和重试。

### 18.3 工作流生成页

根据 `parameter-schema.json` 动态展示：

- 模式选择。
- 提示词。
- 宽度、高度、时长、步数和 Seed。
- 图片、视频和音频素材输入。
- 高级参数。
- 预计显存或资源提示。
- 开始生成按钮。

### 18.4 存储管理

展示：

- Runtime 占用。
- 模型占用。
- 节点占用。
- 工作流占用。
- 下载缓存。
- 未被已安装工作流引用的资源。

默认卸载工作流时不删除公共模型和节点。用户可以主动执行“清理未使用资源”。

---

## 19. Local Agent API

建议新增：

```text
GET    /api/v1/catalog
POST   /api/v1/catalog/refresh

GET    /api/v1/workflows
GET    /api/v1/workflows/{workflowId}
POST   /api/v1/workflows/{workflowId}/plan
POST   /api/v1/workflows/{workflowId}/install
POST   /api/v1/workflows/{workflowId}/repair
POST   /api/v1/workflows/{workflowId}/update
DELETE /api/v1/workflows/{workflowId}
POST   /api/v1/workflows/{workflowId}/verify

GET    /api/v1/downloads
POST   /api/v1/downloads/{downloadId}/pause
POST   /api/v1/downloads/{downloadId}/resume
POST   /api/v1/downloads/{downloadId}/retry
DELETE /api/v1/downloads/{downloadId}

GET    /api/v1/storage
POST   /api/v1/storage/cleanup-plan
POST   /api/v1/storage/cleanup
```

下载和安装进度通过 WebSocket 或 Server-Sent Events 推送。

---

## 20. 数据模型

### 20.1 已安装工作流

- `workflow_id`
- `version`
- `runtime_version`
- `status`
- `manifest_json`
- `installed_at`
- `verified_at`
- `last_error_code`
- `last_error_message`

### 20.2 资源记录

- `resource_id`
- `resource_type`：runtime/node/model/wheel/workflow
- `version`
- `source_url` 或 Hugging Face 定位信息
- `install_path`
- `size`
- `sha256`
- `status`
- `installed_at`
- `verified_at`

### 20.3 工作流资源引用

- `workflow_id`
- `workflow_version`
- `resource_id`
- `required`

该表用于判断模型和节点是否仍被其他工作流使用。

### 20.4 下载任务

- `download_id`
- `resource_id`
- `source`
- `total_bytes`
- `downloaded_bytes`
- `status`
- `partial_path`
- `retry_count`
- `error_message`

---

## 21. 更新与回滚

### 21.1 工作流更新

```text
检测到 Catalog 新版本
→ 比较已安装 Manifest
→ 计算新增和变化资源
→ 展示更新内容与下载大小
→ 下载到 staging
→ 等待本地 GPU 任务完成
→ 停止 ComfyUI
→ 应用更新
→ 重启并验证
→ 成功后切换到新版本
```

没有变化的模型和节点不得重复下载。

### 21.2 更新失败

- 保留旧工作流目录和安装记录。
- 新版本未验证成功前不得成为活动版本。
- 更新失败后恢复旧工作流版本。
- 保存错误日志和失败资源信息。

### 21.3 Runtime 更新

- 新 Runtime 安装到新的版本目录。
- 旧 Runtime 在新版本验证前保留。
- 新 Runtime 验证成功后原子更新 `current.json`。
- 如果启动或工作流冒烟测试失败，继续使用旧 Runtime。

---

## 22. 安全与许可

### 22.1 发布签名

```text
应用内置紫猫 Ed25519 公钥
→ 验证 Catalog 签名
→ Catalog 指向固定 Manifest
→ 验证 Manifest 签名
→ Manifest 中的 SHA256 验证每个下载文件
```

生产签名私钥仅存储在安全发布环境或 GitHub Actions Secret 中，不得提交到代码仓库。

建议 Secrets：

```text
ZIMAO_CATALOG_SIGNING_KEY
ZIMAO_RELEASE_TOKEN
```

由于首版仅引用公开 Hugging Face 模型，客户端默认不需要紫猫持有 HF Token。若模型属于 gated 模型，应由用户自行登录和授权。

### 22.2 路径安全

- 解压前检查 ZIP 条目路径。
- 禁止绝对路径、盘符和 `..`。
- 所有安装目标必须位于 Runtime、models 或 workflows 允许目录。
- 不执行 Manifest 提供的任意命令。
- Python 依赖只允许安装 Manifest 明确声明且校验通过的 wheel。

### 22.3 模型许可证

- 每个模型必须记录官方来源和许可证链接。
- 紫猫不重新上传第三方模型。
- 不绕过 Hugging Face gated 模型授权。
- 工作流页面应显示模型来源和许可证入口。

---

## 23. 测试方案

### 23.1 小型测试工作流

准备专用的轻量测试工作流：

- 小模型，目标体积几十 MB。
- 一个可验证安装的测试节点。
- 一个固定 wheel 或无需额外依赖。
- 输出一张简单图片。

它与正式工作流走相同流程，用于快速验证：

- Catalog 和 Manifest。
- 下载和断点续传。
- SHA256。
- 节点和模型安装。
- ComfyUI 启动。
- `/object_info` 检查。
- 工作流执行和结果入库。

### 23.2 自动化测试

每次提交运行：

- Catalog JSON Schema 校验。
- Manifest JSON Schema 校验。
- Catalog/Manifest 签名验证。
- 重复 ID 检查。
- 版本固定检查。
- 禁止 `main` 和实际资源 `latest`。
- SHA256 格式检查。
- 安装路径安全检查。
- ZIP 路径穿越测试。
- 工作流 JSON 可解析检查。
- 参数映射目标节点存在检查。
- 下载中断和续传测试。
- SHA256 不一致测试。
- 重复安装不重复下载测试。
- 缺失资源一键修复测试。
- 多工作流共享资源测试。

### 23.3 干净环境测试

使用全新的 `%LOCALAPPDATA%\ZimaoAI` 目录：

```text
安装紫猫
→ 获取 production 或 staging Catalog
→ 一键安装工作流
→ 自动下载 Runtime、节点和模型
→ 自动验证
→ 实际生成
```

不得依赖开发电脑已有的节点、模型或 Python 包。

除发布验收机外，首版还必须使用一台 8 GB 显存、16 GB 内存的干净电脑执行最低配置测试。该测试用于证明 Runtime、下载、安装、验证和低显存执行路径在产品最低配置上有效。

### 23.4 异常测试

| 场景 | 预期结果 |
|---|---|
| 下载时断网 | 保留 `.partial` 并支持恢复 |
| 关闭桌面端 | Local Agent 保留可恢复下载状态 |
| 磁盘不足 | 下载前阻止并提示所需空间 |
| SHA256 错误 | 拒绝安装并允许重试 |
| 节点 ZIP 损坏 | 不污染正式节点目录 |
| 模型被删除 | 状态变为“需要修复” |
| 模型被修改 | 校验失败并只重新下载该模型 |
| GitHub 不可访问 | 明确提示资源来源并允许重试 |
| Hugging Face 不可访问 | 保留进度并允许重试 |
| gated 模型未授权 | 显示“等待模型授权” |
| 更新验证失败 | 保持旧版本可用 |

### 23.5 H3 真实 GPU 验收

MiniMax H3 必须分别跑通：

- 文生视频。
- 首帧生视频。
- 首尾帧生视频。
- 全能参考生成。

每项检查：

- 工作流安装和验证成功。
- 用户参数正确注入。
- 输入素材来自本次任务暂存目录。
- ComfyUI 成功返回 `promptId`。
- 输出视频可播放。
- 分辨率和时长符合参数。
- 需要音频时存在音频流。
- 结果进入紫猫素材库。
- Blender 可以加入 VSE。
- 任务记录包含工作流版本、实际 Seed 和解析参数。

H3 验收分为两档：

- 最低配置档：8 GB 显存、16 GB 内存，启用低显存模式，验证能完成生成且不会因内存不足崩溃。
- 推荐配置档：24 GB 显存、32 GB 或更高内存，验证正常性能和完整功能。

最低配置档允许速度明显慢于推荐配置档，但四种正式模式必须能够完成，且软件需要提示低显存模式会增加生成时间和内存/磁盘交换压力。

---

## 24. 工作流发布门禁

一个工作流只有满足以下条件才能加入 `production.json`：

- Manifest 通过 Schema 校验。
- Catalog 和 Manifest 签名有效。
- 所有资源使用固定版本和 SHA256。
- Hugging Face 模型引用为完整 commit hash。
- 模型来源与许可证已记录。
- 在干净环境中完成一键安装。
- 下载中断后可以恢复。
- 重复安装不会重复下载。
- 所有必需节点均被 ComfyUI 识别。
- 所有正式模式至少实际生成成功一次。
- 缺少或损坏文件可以一键修复。
- 与所有现有正式工作流共同安装后仍能运行。
- 桌面端和 Blender 端到端验收通过。
- Manifest 中声明的最低硬件配置已经在对应真实硬件上通过测试。

发布流程：

```text
开发工作流
→ 生成并校验 Manifest
→ 发布固定 GitHub Release
→ 更新 staging.json
→ 干净环境安装测试
→ 真实 GPU 生成测试
→ 保存测试证据
→ 更新 production.json
```

---

## 25. 新工作流制作流程

```text
1. 在固定紫猫 Runtime 中跑通原始 ComfyUI 工作流
2. 导出 API 工作流 JSON
3. 定义参数 Schema
4. 定义参数与节点映射
5. 列出所有节点、wheel 和模型
6. 固定节点版本和 Python wheel
7. 为每个模型选择官方/原作者 Hugging Face 来源
8. 固定 Hugging Face 完整 commit hash
9. 计算全部文件大小和 SHA256
10. 打包工作流和节点 ZIP
11. 生成并签名 Manifest
12. 创建 GitHub Release
13. 加入 staging Catalog
14. 执行干净安装和真实 GPU 测试
15. 加入 production Catalog
```

---

## 26. 实施阶段

### 阶段一：工作流安装基础

- 定义 Catalog 和 Manifest Schema。
- 扩展现有 MiniMax H3 Manifest。
- 将硬编码模型注册表改为读取已安装工作流。
- 实现远程 Catalog 获取和本地缓存。
- 实现资源检查和安装计划。
- 实现断点下载、大小检查和 SHA256。
- 实现节点、模型和工作流安装。
- 实现 ComfyUI 节点验证。

### 阶段二：桌面端产品化

- 新增工作流中心。
- 新增工作流详情和一键安装。
- 新增下载管理。
- 新增修复、更新和卸载。
- 新增存储管理。
- 将生成页面改为已安装工作流驱动。

### 阶段三：发布体系

- 创建 `Zimao` GitHub 组织和公开仓库。
- 建立 `staging` 和 `production` Catalog。
- 建立 GitHub Release 打包流程。
- 建立 Ed25519 签名流程。
- 建立 Runtime 发布流程。
- 建立自动化 Schema、哈希和安全检查。

### 阶段四：验收

- 制作轻量测试工作流。
- 执行下载异常和修复测试。
- 执行多工作流共享资源测试。
- 执行 MiniMax H3 干净环境安装。
- 执行 H3 四模式 GPU 端到端测试。
- 执行 Blender 端到端测试。

---

## 27. 首版验收标准

- 用户可以从公开 Catalog 看到 MiniMax H3 工作流。
- 没有 Runtime 时能够自动下载安装固定 Runtime。
- 能准确计算 H3 缺少的节点和模型。
- 能从 GitHub 下载固定工作流包和节点包。
- 能从官方/原作者 Hugging Face 仓库下载固定模型文件。
- 下载支持进度、暂停、继续、重试和断点续传。
- 所有资源通过签名、大小和 SHA256 校验。
- 安装失败不会破坏已有可用环境。
- 安装后 ComfyUI 能识别所有必需节点。
- H3 状态能够变为“可以使用”。
- H3 四种模式可以实际生成结果。
- 生成结果进入统一素材库。
- Blender 可以查询工作流、提交任务并使用结果。
- 删除一个模型后能够检测并一键修复。
- 第二次安装不会重复下载已有模型。
- 工作流更新失败时旧版本仍可使用。
- 紫猫软件和基础 Runtime 可以在 8 GB 显存、16 GB 内存电脑上正常安装和启动。
- 硬件检查能够准确识别显存、内存和驱动是否满足工作流要求。
- H3 如果在正式页面声明最低 8 GB 显存、16 GB 内存，则必须在该配置上跑通四种正式模式。

---

## 28. 当前项目迁移说明

当前代码已经具备：

- MiniMax H3 固定 API 工作流。
- 参数 Schema 和节点映射。
- 工作流编译器。
- Local Agent 和 ComfyUI 进程管理。
- SQLite 任务系统和素材库。
- 桌面端与 Blender 插件。
- H3 GPU 端到端测试基础。

本项目不需要推倒重写。建议按以下顺序演进：

```text
现有 H3 Manifest 扩展
→ 通用工作流包加载器
→ Catalog 客户端
→ 资源检查器
→ 下载器
→ 安装器
→ 安装状态数据库
→ 工作流中心 UI
→ 签名与发布工具
→ 干净环境安装测试
→ 正式 GitHub Release 和 production Catalog
```

---

## 29. 最终产品定义

紫猫是一套面向普通创作者的本地 AI 工作流中心：

> GitHub 负责公开发布紫猫软件、固定 Runtime、工作流清单、工作流包和节点包；Hugging Face 使用模型官方或原作者已有仓库；紫猫根据经过签名的 Manifest 自动检查、下载、安装、验证、修复和更新。用户只需要选择工作流、点击“一键安装”，然后“立即使用”。
