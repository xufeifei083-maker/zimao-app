"""Export the bundled MiniMax H3 API workflows without starting Gradio.

Run this script with the Python interpreter bundled by the H3 ComfyUI runtime.
The compiled module prints its own startup banner when imported; that output is
expected and is unrelated to the exported JSON files.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path


SLUGS = {
    "文生视频": "text-to-video.api.json",
    "图生视频（首帧/可选尾帧）": "image-to-video.api.json",
    "全能参考生成视频": "reference-to-video.api.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--comfy-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    comfy_root = args.comfy_root.resolve()
    output = args.output.resolve()
    sys.path.insert(0, str(comfy_root))
    module = importlib.import_module("gradio_minimax_h3")

    output.mkdir(parents=True, exist_ok=True)
    exported: dict[str, dict[str, object]] = {}
    for display_name, filename in SLUGS.items():
        workflow = module.load_workflow(display_name)
        if not isinstance(workflow, dict):
            raise TypeError(f"{display_name} did not export a dict workflow")
        write_json(output / filename, workflow)
        exported[display_name] = {
            "filename": filename,
            "nodeCount": len(workflow),
            "nodeMap": module.WORKFLOW_NODE_MAP[display_name],
        }

    write_json(output / "export-metadata.json", exported)
    print(f"Exported {len(exported)} workflows to {output}")


if __name__ == "__main__":
    main()

