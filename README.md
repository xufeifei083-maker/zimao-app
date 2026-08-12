# Flynotes Local AI Control Center

本仓库实现《本地 AI 控制中心 PRD 与开发验收文档》中定义的桌面控制中心、Python Local Agent、H3 工作流适配和 Blender 插件集成。

## 仓库结构

```text
agent/       Python Local Agent、任务系统和工作流编译器
desktop/     Tauri + React 桌面端
tools/       工作流导出和开发辅助工具
PRD-本地AI控制中心.md
```

## 当前状态

PRD 0.1.0 开发范围已经完成，并形成可安装、可验收的 Windows 发布候选：

- Local Agent 健康接口及 ComfyUI 8188 启动、停止、重启、外部进程保护
- MiniMax H3（本地）模型注册和三套冻结 API 工作流
- 文生、首帧/首尾帧、全能参考参数编译及未使用素材节点裁剪
- 素材上传、SHA256、安全暂存、SQLite 持久化任务与后台 ComfyUI 提交
- ComfyUI 队列/历史恢复、实际 Seed、promptId 和本地结果路径记录
- `/api/v1/blender/*` 兼容接口，为现有 Blender 插件迁移提供稳定契约
- ComfyUI 服务、视频生成、素材库、插件列表四 Tab React 桌面端
- Blender 插件 1.4.0 稳定加载器、忙碌心跳、安全延期、SHA256 + Ed25519 验签、版本切换和回滚点
- 素材索引、缩略图、视频预览、统一任务记录和真实日志
- Blender 所有云端请求经 Local Agent 流式转发 Flynotes，不再直连云端 API
- Tauri 原生 EXE 与 NSIS x64 安装包，内置独立 Agent 并在首次运行自动部署
- Blender 5.0 + RTX 3090 三项 H3 GPU 端到端发布门禁全部通过
- 紫猫工作流中心：固定运行时、8 GB 显存 / 16 GB 内存门槛、签名公开目录与 Hugging Face 固定版本模型引用
- 后台断点下载：一键安装、实时进度、暂停、继续、重试、取消，并在安装后自动启动 ComfyUI 验证

完整验收结论见 [发布报告](test-results/0.1.0/release-report.md)，机器可读制品哈希见 [发布清单](test-results/0.1.0/release-manifest.json)。

## Python 开发

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m flynotes_agent
```

默认 Local Agent 地址：`http://127.0.0.1:17980`。

Local Agent 不启动 Gradio，也不访问 7860；它直接连接 `http://127.0.0.1:8188`。如果 8188 当前由旧 `start.py` 启动，状态会显示为 `warning` 且禁止误停该外部进程。

工作流模型统一保存到 `%LOCALAPPDATA%\FlynotesAI\models`，Agent 会生成 ComfyUI `extra_model_paths` 配置，不会复制同一份大模型。公开目录发布后配置：

```powershell
$env:ZIMAO_WORKFLOW_CATALOG_URL="https://raw.githubusercontent.com/xufeifei083-maker/zimao-workflows/main/catalog/catalog.json"
$env:ZIMAO_WORKFLOW_CATALOG_PUBLIC_KEY="<BASE64_ED25519_PUBLIC_KEY>"
```

目录文件必须带同地址的 `.sig` 签名；目录内的模型资源必须使用 Hugging Face 完整 commit hash、文件大小和 SHA256。

## Desktop 开发

```powershell
pnpm --dir desktop install
pnpm --dir desktop build
pnpm --dir desktop dev
```

Windows 原生构建可使用 Rust MSVC，或使用用户级 Rust GNU + MinGW：

```powershell
pnpm --dir desktop tauri build --target x86_64-pc-windows-gnu
```

当前安装包位于 `desktop/src-tauri/target/x86_64-pc-windows-gnu/release/bundle/nsis/`。启动桌面程序时，如 17980 未监听，会把内置 Agent 部署到 `%LOCALAPPDATA%\FlynotesAI\bin\0.1.0` 后独立启动；关闭桌面程序不会结束 Agent 或 Blender 任务。

## 发布构建

```powershell
# 独立 Local Agent
.\.venv\Scripts\python.exe tools\build_agent.py

# Blender 插件正式签名包
.\.venv\Scripts\python.exe tools\build_blender_plugin.py `
  --version 1.4.0 `
  --base-url https://github.com/OWNER/REPOSITORY/releases/download/v1.4.0 `
  --private-key <BASE64_ED25519_PRIVATE_KEY>
```

仓库中的 `dist/blender-plugin/test-public-key.txt` 仅用于本地验签验收。正式发布时必须使用生产私钥构建，并在 Agent 环境中配置 `FLYNOTES_PLUGIN_REPOSITORY` 与对应的 `FLYNOTES_PLUGIN_PUBLIC_KEY`。

## 验收命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q agent blender_addon tools
pnpm --dir desktop build
```

Blender GPU 证据位于 `test-results/0.1.0/blender-h3/`，每项均包含 `summary.json`、`agent-job.json`、`asset.json`、`compiled-workflow.json`、`ffprobe.json` 和可复核的 `.blend` 文件。
