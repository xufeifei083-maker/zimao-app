from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path


FORBIDDEN_MARKERS = {
    "与ai同行": "旧整合包作者品牌",
    "walkingwithai": "旧整合包目录或品牌",
    "gradio_minimax_h3": "旧整合包自定义 Gradio 模块",
    "t.zsxq.com": "知识星球推广链接",
    "ai.feishu.cn/wiki/ohmewjkhbinj4aksaoccyfbznob": "旧整合包飞书链接",
    "最强ai视频": "旧整合包名称",
    "minimaxh3-v260803": "旧整合包构建路径",
    "users\\23122": "发布机用户路径",
    "users/23122": "发布机用户路径",
}

FORBIDDEN_FILENAMES = {
    "启动程序.bat",
    "与ai同行-ai解决方案使用注意事项.txt",
    "start.py",
    "gradio_minimax_h3.cp312-win_amd64.pyd",
}

SKIPPED_DIRS = {".git", "models", "input", "output", "temp", "user", "__pycache__"}
SCANNED_SUFFIXES = {
    ".bat", ".cmd", ".css", ".html", ".ini", ".js", ".json", ".md", ".ps1",
    ".py", ".toml", ".ts", ".tsx", ".txt", ".yaml", ".yml",
}


@dataclass(frozen=True)
class Finding:
    path: str
    reason: str
    marker: str


def audit(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any(part.casefold() in SKIPPED_DIRS for part in relative.parts):
            continue
        if len(relative.parts) > 1 and relative.parts[0].casefold() == "walkingwithai":
            continue
        relative_text = relative.as_posix().casefold()
        if path.name.casefold() in FORBIDDEN_FILENAMES:
            findings.append(Finding(relative.as_posix(), "禁止发布的旧整合包文件", path.name))
        for marker, reason in FORBIDDEN_MARKERS.items():
            if marker in relative_text:
                findings.append(Finding(relative.as_posix(), reason, marker))
        if not path.is_file():
            continue
        if path.suffix.casefold() not in SCANNED_SUFFIXES or path.stat().st_size > 10 * 1024 * 1024:
            continue
        try:
            payload = path.read_bytes()
        except OSError:
            continue
        lowered = payload.lower()
        for marker, reason in FORBIDDEN_MARKERS.items():
            encodings = {marker.encode("utf-8"), marker.encode("utf-16le")}
            if any(encoded.lower() in lowered for encoded in encodings):
                findings.append(Finding(relative.as_posix(), reason, marker))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="阻止旧整合包品牌、推广链接和本机路径进入 Runtime")
    parser.add_argument("root", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"Runtime 目录不存在：{root}")
    findings = audit(root)
    if args.json:
        print(json.dumps([finding.__dict__ for finding in findings], ensure_ascii=False, indent=2))
    elif findings:
        for finding in findings:
            print(f"FAIL {finding.path}: {finding.reason} ({finding.marker})")
    else:
        print(f"RUNTIME_BRAND_AUDIT_OK root={root}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
