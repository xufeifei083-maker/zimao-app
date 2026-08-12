from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".installation_id"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1.4.0")
    parser.add_argument("--base-url", default="https://github.com/OWNER/REPOSITORY/releases/download/v1.4.0")
    parser.add_argument("--private-key", help="Base64 raw Ed25519 private key")
    parser.add_argument("--generate-test-key", action="store_true")
    args = parser.parse_args()
    if not args.private_key and not args.generate_test_key:
        raise SystemExit("Provide --private-key for a release or --generate-test-key for local verification")

    repo = Path(__file__).resolve().parents[1]
    dist = repo / "dist" / "blender-plugin"
    dist.mkdir(parents=True, exist_ok=True)
    package_name = f"flynotes-ai-blender-{args.version}.zip"
    package_path = dist / package_name
    installer_path = dist / f"flynotes-ai-blender-installer-{args.version}.zip"
    version_folder = f"v{args.version.replace('.', '_')}"

    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        update_root = temporary_root / "update" / "flynotes_ai"
        copy_tree(repo / "blender_addon" / "flynotes_ai", update_root)
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for source in sorted(update_root.rglob("*")):
                if source.is_file():
                    bundle.write(source, source.relative_to(update_root.parent).as_posix())

        root = temporary_root / "installer" / "flynotes_ai"
        root.mkdir(parents=True)
        shutil.copy2(
            repo / "agent" / "flynotes_agent" / "plugin_loader" / "flynotes_ai" / "__init__.py",
            root / "__init__.py",
        )
        (root / "current.json").write_text(
            json.dumps({"version": args.version}, indent=2), encoding="utf-8"
        )
        copy_tree(repo / "blender_addon" / "flynotes_ai", root / "versions" / version_folder)
        with zipfile.ZipFile(installer_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for source in sorted(root.rglob("*")):
                if source.is_file():
                    bundle.write(source, source.relative_to(root.parent).as_posix())

    payload = package_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    private_key = (
        Ed25519PrivateKey.from_private_bytes(base64.b64decode(args.private_key))
        if args.private_key
        else Ed25519PrivateKey.generate()
    )
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    signature = private_key.sign(digest.encode("ascii"))
    manifest = {
        "schemaVersion": 1,
        "pluginId": "flynotes-ai-blender",
        "version": args.version,
        "minBlenderVersion": "4.0.0",
        "package": {
            "url": f"{args.base_url.rstrip('/')}/{package_name}",
            "sha256": digest,
            "signature": base64.b64encode(signature).decode("ascii"),
        },
    }
    (dist / "flynotes-plugin-release.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (dist / "test-public-key.txt").write_text(
        base64.b64encode(public_key).decode("ascii"), encoding="ascii"
    )
    print(json.dumps({"package": str(package_path), "installer": str(installer_path), "sha256": digest, "publicKey": base64.b64encode(public_key).decode("ascii")}, indent=2))


if __name__ == "__main__":
    main()
