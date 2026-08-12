from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


EXCLUDED_ROOTS = {
    ".git",
    "models",
    "input",
    "output",
    "temp",
    "user",
    "custom_nodes",
}
INCLUDED_CUSTOM_NODES = {"comfyui-kjnodes", "comfyui-videohelpersuite"}
EXCLUDED_NAMES = {"__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".partial"}


def _private_key(path: Path) -> Ed25519PrivateKey:
    raw = base64.b64decode(path.read_bytes().strip(), validate=True)
    if len(raw) != 32:
        raise ValueError("Ed25519 private key must contain 32 raw bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _included_files(source: Path) -> list[Path]:
    selected: list[Path] = []
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.suffix.casefold() in EXCLUDED_SUFFIXES:
            continue
        root = relative.parts[0]
        if root in EXCLUDED_ROOTS:
            if root != "custom_nodes" or len(relative.parts) < 2:
                continue
            if relative.parts[1] not in INCLUDED_CUSTOM_NODES:
                continue
            if ".git" in relative.parts:
                continue
        selected.append(path)
    return sorted(selected, key=lambda item: item.relative_to(source).as_posix())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(args: argparse.Namespace) -> None:
    source = args.source.resolve()
    files = _included_files(source)
    source_bytes = sum(path.stat().st_size for path in files)
    inventory = {
        "runtimeId": args.runtime_id,
        "source": str(source),
        "fileCount": len(files),
        "uncompressedBytes": source_bytes,
        "includedCustomNodes": sorted(INCLUDED_CUSTOM_NODES),
        "excludedRoots": sorted(EXCLUDED_ROOTS - {"custom_nodes"}),
    }
    print(json.dumps(inventory, ensure_ascii=False, indent=2))
    if args.dry_run:
        return

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        archive = Path(temporary) / f"{args.runtime_id}.zip"
        with zipfile.ZipFile(
            archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
        ) as bundle:
            for index, path in enumerate(files, start=1):
                bundle.write(path, path.relative_to(source).as_posix())
                if index % 1000 == 0:
                    print(f"packed {index}/{len(files)}")
        archive_size = archive.stat().st_size
        archive_sha256 = _sha256(archive)
        parts: list[dict[str, object]] = []
        with archive.open("rb") as stream:
            index = 1
            while True:
                content = stream.read(args.part_size)
                if not content:
                    break
                name = f"runtime-{args.runtime_id}.part{index:02d}"
                destination = output / name
                destination.write_bytes(content)
                parts.append(
                    {
                        "name": name,
                        "url": f"{args.base_url.rstrip('/')}/{name}",
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
                index += 1

    manifest = {
        "schemaVersion": 1,
        "runtimeId": args.runtime_id,
        "pythonVersion": args.python_version,
        "comfyuiCommit": args.comfyui_commit,
        "pytorchVersion": args.pytorch_version,
        "cudaVersion": args.cuda_version,
        "ffmpegVersion": args.ffmpeg_version,
        "minimumDriver": args.minimum_driver,
        "archiveSize": archive_size,
        "archiveSha256": archive_sha256,
        "requiredFiles": ["main.py", "walkingwithai/python.exe"],
        "parts": parts,
    }
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    manifest_path = output / "runtime-manifest.json"
    manifest_path.write_bytes(payload)
    signature = _private_key(args.private_key).sign(payload)
    manifest_path.with_suffix(".json.sig").write_bytes(base64.b64encode(signature) + b"\n")
    (output / "checksums.sha256").write_text(
        "".join(f"{item['sha256']}  {item['name']}\n" for item in parts), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the fixed Zimao Windows NVIDIA runtime")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("dist/runtime"))
    parser.add_argument("--runtime-id", default="win-nvidia-h3-2026.08.1")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--private-key", type=Path)
    parser.add_argument("--part-size", type=int, default=1900 * 1024 * 1024)
    parser.add_argument("--python-version", default="3.12.12")
    parser.add_argument("--comfyui-commit", default="14b05228cef127ce529bc0c08660770d4af3e9a8")
    parser.add_argument("--pytorch-version", default="2.12.1+cu130")
    parser.add_argument("--cuda-version", default="13.0")
    parser.add_argument("--ffmpeg-version", default="2025-06-26-git-09cd38e9d5")
    parser.add_argument("--minimum-driver", default="580.00")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and (not args.base_url or not args.private_key):
        parser.error("--base-url and --private-key are required unless --dry-run is used")
    build(args)


if __name__ == "__main__":
    main()
