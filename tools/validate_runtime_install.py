from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from flynotes_agent.config import AgentConfig  # noqa: E402
from flynotes_agent.runtime_package import RuntimePackageManager  # noqa: E402


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return


def private_key(path: Path) -> Ed25519PrivateKey:
    raw = base64.b64decode(path.read_bytes().strip(), validate=True)
    return Ed25519PrivateKey.from_private_bytes(raw)


def run(args: argparse.Namespace) -> None:
    release = args.release.resolve()
    original_manifest = json.loads((release / "runtime-manifest.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(dir=args.temporary_root) as server_name:
        server_root = Path(server_name)
        for part in original_manifest["parts"]:
            os.link(release / part["name"], server_root / part["name"])
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(QuietHandler, directory=str(server_root))
        )
        port = server.server_address[1]
        manifest = dict(original_manifest)
        manifest["parts"] = [
            {**part, "url": f"http://127.0.0.1:{port}/{part['name']}"}
            for part in original_manifest["parts"]
        ]
        payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
        (server_root / "runtime-manifest.json").write_bytes(payload)
        signature = private_key(args.private_key).sign(payload)
        (server_root / "runtime-manifest.json.sig").write_bytes(base64.b64encode(signature) + b"\n")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(dir=args.temporary_root) as data_name:
                data_root = Path(data_name)
                config = AgentConfig(
                    comfy_root=data_root / "missing-runtime",
                    data_root=data_root,
                    runtime_id=manifest["runtimeId"],
                    runtime_manifest_url=f"http://127.0.0.1:{port}/runtime-manifest.json",
                    runtime_public_key=args.public_key,
                )
                manager = RuntimePackageManager(config)
                last_percent = -10

                def progress(current: int, total: int) -> None:
                    nonlocal last_percent
                    percent = int(current / total * 100) if total else 0
                    if percent >= last_percent + 10 or percent == 100:
                        last_percent = percent
                        print(f"DOWNLOAD_PROGRESS {percent}%", flush=True)

                result = asyncio.run(manager.install(progress=progress))
                installed = Path(result.installPath)
                python_result = subprocess.run(
                    [str(installed / "python_runtime" / "python.exe"), "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                ffmpeg_result = subprocess.run(
                    [str(installed / "ffmpeg" / "bin" / "ffmpeg.exe"), "-version"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                print(f"INSTALLED_RUNTIME {installed}")
                print(f"INSTALLED_PYTHON {python_result.stdout.strip()}")
                print(f"INSTALLED_FFMPEG {ffmpeg_result.stdout.splitlines()[0]}")
                print("FULL_CLEAN_RUNTIME_INSTALL_OK")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description="完整验证已签名 Runtime 的下载和安装流程")
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--temporary-root", type=Path, required=True)
    args = parser.parse_args()
    args.temporary_root.mkdir(parents=True, exist_ok=True)
    run(args)


if __name__ == "__main__":
    main()
