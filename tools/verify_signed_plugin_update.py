"""Exercise the production plugin verifier against a release manifest.

This utility is intended for release engineering and local acceptance tests.
It uses the same PluginManager code and Blender installation discovery as the
Local Agent, so a successful run proves download, SHA256, Ed25519, staging,
backup and activation rather than merely inspecting the archive.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "agent"))

from flynotes_agent.config import AgentConfig  # noqa: E402
from flynotes_agent.plugins import PluginManager  # noqa: E402


async def run(manifest_path: Path, public_key: str, blender_version: str) -> None:
    config = replace(AgentConfig.from_env(), plugin_public_key=public_key.strip())
    manager = PluginManager(config)
    manager.initialize()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    staged = await manager.stage(manifest)
    plugin_id = f"flynotes-ai-blender:{blender_version}"
    applied = manager.apply(plugin_id)
    result = next(item for item in applied if item.id == plugin_id)
    print(
        json.dumps(
            {
                "staged": [item.model_dump(mode="json") for item in staged],
                "applied": result.model_dump(mode="json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--public-key-file", type=Path, required=True)
    parser.add_argument("--blender-version", default="5.0")
    args = parser.parse_args()
    asyncio.run(
        run(
            args.manifest.resolve(),
            args.public_key_file.read_text(encoding="ascii"),
            args.blender_version,
        )
    )


if __name__ == "__main__":
    main()
