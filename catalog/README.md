# 紫猫工作流公开目录

这个目录是软件读取的公开发布物，不存放大模型。模型继续引用 Hugging Face 的固定仓库、固定 commit 和 SHA256。

发布时运行：

```powershell
python tools/build_workflow_catalog.py `
  --base-url https://raw.githubusercontent.com/xufeifei083-maker/zimao-workflows/main/catalog `
  --private-key C:\secure\zimao-catalog.ed25519-private
```

生成内容包括：

- `catalog.json`：工作流清单、硬件要求、模型固定引用；
- `catalog.json.sig`：对 `catalog.json` 原始字节的 Ed25519 签名；
- `workflows/<id>/<version>/`：体积很小的 ComfyUI API 工作流 JSON。

私钥只保存在离线位置或 GitHub Actions Secret 中。桌面软件只内置公钥，并通过 `ZIMAO_WORKFLOW_CATALOG_URL` 与 `ZIMAO_WORKFLOW_CATALOG_PUBLIC_KEY` 连接公开目录。
