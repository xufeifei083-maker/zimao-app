from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _private_key(path: Path) -> Ed25519PrivateKey:
    raw = path.read_bytes().strip()
    try:
        decoded = base64.b64decode(raw, validate=True)
    except ValueError:
        decoded = raw
    if len(decoded) != 32:
        raise ValueError("Ed25519 private key must contain exactly 32 raw bytes")
    return Ed25519PrivateKey.from_private_bytes(decoded)


def build(packages: Path, output: Path, base_url: str, key_path: Path) -> None:
    workflows: list[dict] = []
    public_root = output.parent / "workflows"
    for manifest_path in sorted(packages.glob("*/*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        workflow_id = manifest["id"]
        version = manifest["version"]
        files: dict[str, dict] = {}
        for relative in manifest["modes"].values():
            source = manifest_path.parent / relative
            payload = source.read_bytes()
            destination = public_root / workflow_id / version / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            url_path = "/".join(("workflows", workflow_id, version, *Path(relative).parts))
            files[relative] = {
                "url": f"{base_url.rstrip('/')}/{url_path}",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        workflows.append({"manifest": manifest, "workflowFiles": files})

    catalog = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "workflows": workflows,
    }
    payload = json.dumps(
        catalog, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8") + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    signature = _private_key(key_path).sign(payload)
    output.with_name(f"{output.name}.sig").write_bytes(base64.b64encode(signature) + b"\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and sign the Zimao workflow catalog")
    parser.add_argument("--packages", type=Path, default=Path("agent/flynotes_agent/workflow_packages"))
    parser.add_argument("--output", type=Path, default=Path("catalog/catalog.json"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    build(args.packages, args.output, args.base_url, args.private_key)


if __name__ == "__main__":
    main()
