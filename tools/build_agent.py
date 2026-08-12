"""Build the standalone Windows Local Agent executable."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import PyInstaller.__main__


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    dist = root / "dist" / "agent"
    work = root / "build" / "agent"
    PyInstaller.__main__.run(
        [
            str(root / "tools" / "agent_entry.py"),
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name=flynotes-local-agent",
            f"--paths={root / 'agent'}",
            "--hidden-import=flynotes_agent.api",
            "--collect-data=flynotes_agent",
            f"--distpath={dist}",
            f"--workpath={work}",
            f"--specpath={work}",
        ]
    )
    executable = dist / "flynotes-local-agent.exe"
    bundled_resource = (
        root
        / "desktop"
        / "src-tauri"
        / "resources"
        / "agent"
        / "flynotes-local-agent.exe"
    )
    bundled_resource.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(executable, bundled_resource)
    print(
        json.dumps(
            {
                "path": str(executable),
                "bundledResource": str(bundled_resource),
                "size": executable.stat().st_size,
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
