"""Small real-Blender regression check for Local Agent task reconciliation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

import bpy


arguments = sys.argv[sys.argv.index("--") + 1 :]
parser = argparse.ArgumentParser()
parser.add_argument("--repo", type=Path, required=True)
parser.add_argument("--job", required=True)
args = parser.parse_args(arguments)

sys.path.insert(0, str((args.repo / "blender_addon").resolve()))
bpy.ops.preferences.addon_enable(module="flynotes_ai")

from flynotes_ai import background, operators, runtime

preference = bpy.context.preferences.addons["flynotes_ai"].preferences
preference.local_agent_api = "http://127.0.0.1:17980/api/v1"
preference.debug_logging = True
runtime.session_jobs.clear()
runtime.session_jobs.append(
    {
        "jobId": args.job,
        "status": "running",
        "modelId": operators.LOCAL_AGENT_MODEL_ID,
        "_provider": "local-agent",
        "_mediaType": "video",
        "_prompt": "poll regression",
    }
)

deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    background.pump()
    operators.poll_session_jobs()
    if runtime.session_jobs[0].get("status") == "done":
        print("FLYNOTES_COMPLETED_POLL_PASS", flush=True)
        break
    time.sleep(0.25)
else:
    raise RuntimeError(f"Stale Blender task state: {runtime.session_jobs!r}")

bpy.ops.preferences.addon_disable(module="flynotes_ai")
