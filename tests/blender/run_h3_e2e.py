"""Run one MiniMax H3 E2E case from a real Blender process.

Invoke with Blender 5.0, for example:

    blender.exe --background --factory-startup --python run_h3_e2e.py -- \
      --case text --repo C:\\path\\to\\repo --evidence C:\\path\\to\\evidence

The script deliberately submits through ``bpy.ops.flynotes.generate`` and adds
the returned movie through ``bpy.ops.flynotes.job_action``. It therefore tests
the same add-on boundary used by an interactive Blender session.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import bpy


CASES = {
    "text": {
        "mode": "text",
        "seed": 260803001,
        "prompt": (
            "A small blue paper boat travels across a calm reflective lake, "
            "soft sunrise, locked camera, clean background."
        ),
        "inputs": [],
    },
    "first-last": {
        "mode": "first_last",
        "seed": 260803002,
        "prompt": (
            "Smoothly transition from the blue opening frame to the pink "
            "closing frame, locked camera, gentle light."
        ),
        "inputs": [
            ("first_frame.png", "first_frame"),
            ("last_frame.png", "last_frame"),
        ],
    },
    "reference": {
        "mode": "reference",
        "seed": 260803003,
        "prompt": (
            "Use <Picture 1> for the main blue subject, <Picture 2> for the "
            "green and amber palette, follow the motion of <Video 1>, and "
            "synchronize the scene rhythm with <Audio 1>."
        ),
        "inputs": [
            ("reference_1.png", "reference_image"),
            ("reference_2.png", "reference_image"),
            ("reference_video.mp4", "reference_video"),
            ("reference_audio.wav", "reference_audio"),
        ],
    },
}


def parse_args() -> argparse.Namespace:
    arguments = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=sorted(CASES), required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--agent", default="http://127.0.0.1:17980")
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument(
        "--resume-job",
        default="",
        help="Reuse an already submitted Blender job to debug evidence/VSE handling.",
    )
    return parser.parse_args(arguments)


def request_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.25)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def pump_until(predicate, *, timeout: int, poll=None, label: str) -> None:
    deadline = time.monotonic() + timeout
    heartbeat = 0.0
    while time.monotonic() < deadline:
        from flynotes_ai import background

        background.pump()
        if predicate():
            return
        if poll:
            poll()
        if time.monotonic() >= heartbeat:
            print(f"FLYNOTES_E2E_WAIT {label}", flush=True)
            heartbeat = time.monotonic() + 5
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {label}")


def ffprobe(ffprobe_path: Path, video: Path) -> dict:
    completed = subprocess.run(
        [
            str(ffprobe_path),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def main() -> None:
    args = parse_args()
    case = CASES[args.case]
    repo = args.repo.resolve()
    evidence = args.evidence.resolve()
    fixtures = repo / "tests" / "fixtures" / "h3"
    evidence.mkdir(parents=True, exist_ok=True)
    os.environ["FLYNOTES_E2E_CASE"] = args.case

    if port_is_open(7860):
        raise RuntimeError("Release gate failed: TCP 7860 is listening before submission")
    health = request_json(f"{args.agent}/v1/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"Local Agent is not healthy: {health}")

    addon_root = repo / "blender_addon"
    sys.path.insert(0, str(addon_root))
    bpy.ops.preferences.addon_enable(module="flynotes_ai")
    import flynotes_ai
    from flynotes_ai import background, operators, runtime
    from flynotes_ai.compat import sequence_collection

    preference = bpy.context.preferences.addons["flynotes_ai"].preferences
    preference.local_agent_api = f"{args.agent}/api/v1"
    preference.local_agent_timeout = 120
    preference.auto_add_vse = True
    preference.debug_logging = True
    preference.assets_root = str(evidence / "assets")

    runtime.session_jobs.clear()
    scene = bpy.context.scene
    scene.flynotes_generation_tab = "video"
    scene.flynotes_video_model = operators.LOCAL_AGENT_MODEL_ID
    scene.flynotes_video_mode = case["mode"]
    scene.flynotes_video_prompt = case["prompt"]
    scene.flynotes_video_duration = "5"
    scene.flynotes_h3_width = 480
    scene.flynotes_h3_height = 832
    scene.flynotes_h3_steps = 20
    scene.flynotes_h3_seed = case["seed"]
    scene.flynotes_h3_ref_image_size = "match"
    scene.flynotes_video_use_workbench = False
    scene.flynotes_video_inputs.clear()
    for relative_path, role in case["inputs"]:
        source_path = (fixtures / relative_path).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        item = scene.flynotes_video_inputs.add()
        item.path = str(source_path)
        item.role = role
        item.source = "fixture"

    started_at = time.time()
    if args.resume_job:
        recovered = request_json(f"{args.agent}/api/v1/blender/jobs/{args.resume_job}")
        recovered["_mediaType"] = "video"
        recovered["_provider"] = "local-agent"
        recovered["_prompt"] = recovered.get("prompt", "")[:160]
        runtime.session_jobs.insert(0, recovered)
        runtime.last_submitted_jobs["video"] = args.resume_job
        job_id = args.resume_job
    else:
        operator_result = bpy.ops.flynotes.generate(media_type="video")
        if "FINISHED" not in operator_result:
            raise RuntimeError(f"Generate operator did not finish: {operator_result}")

        pump_until(
            lambda: bool(runtime.last_submitted_jobs.get("video")),
            timeout=180,
            label="Blender add-on submission",
        )
        job_id = runtime.last_submitted_jobs["video"]

    def current_job():
        return next((job for job in runtime.session_jobs if job.get("jobId") == job_id), None)

    last_status = None

    def poll_job():
        nonlocal last_status
        job = current_job()
        if job and job.get("status") != last_status:
            last_status = job.get("status")
            print(f"FLYNOTES_E2E_STATUS {args.case} {job_id} {last_status}", flush=True)
        operators.poll_session_jobs()

    pump_until(
        lambda: bool(current_job()) and current_job().get("status") in {"done", "failed", "cancelled"},
        timeout=args.timeout,
        poll=poll_job,
        label="H3 generation",
    )
    job = current_job()
    if not job or job.get("status") != "done":
        raise RuntimeError(f"H3 job failed: {json.dumps(job, ensure_ascii=False)}")

    action_result = bpy.ops.flynotes.job_action(job_id=job_id, action="download")
    print(f"FLYNOTES_E2E_ACTION {job_id} {action_result}", flush=True)
    if "FINISHED" not in action_result:
        raise RuntimeError(f"Download/VSE operator did not finish: {action_result}")

    def movie_strips():
        collection = sequence_collection(scene.sequence_editor)
        return [strip for strip in collection or [] if getattr(strip, "type", "") == "MOVIE"]

    pump_until(
        lambda: bool(movie_strips()),
        timeout=180,
        label="Blender VSE insertion",
    )
    strip = movie_strips()[-1]
    print(f"FLYNOTES_E2E_VSE {strip.name}", flush=True)
    output_path = Path(bpy.path.abspath(strip.filepath)).resolve()
    if not output_path.is_file():
        raise FileNotFoundError(f"VSE movie strip points to a missing file: {output_path}")

    probe = ffprobe(args.ffprobe.resolve(), output_path)
    video_streams = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"]
    if not video_streams:
        raise RuntimeError("ffprobe found no decodable video stream")
    video_stream = video_streams[0]
    if int(video_stream.get("width", 0)) != 480 or int(video_stream.get("height", 0)) != 832:
        raise RuntimeError(f"Unexpected output dimensions: {video_stream}")

    agent_job = request_json(f"{args.agent}/v1/jobs/{job_id}")
    if agent_job.get("status") != "succeeded":
        raise RuntimeError(f"Agent job is not succeeded: {agent_job}")
    assets = request_json(f"{args.agent}/v1/assets?limit=500")
    asset = next((item for item in assets if item.get("jobId") == job_id), None)
    if not asset:
        raise RuntimeError("Generated output was not registered in the Agent asset library")

    staging_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "FlynotesAI" / "staging" / "jobs" / job_id
    compiled_source = staging_root / "compiled-workflow.json"
    if not compiled_source.is_file():
        raise FileNotFoundError(f"Compiled workflow evidence is missing: {compiled_source}")

    blend_path = evidence / f"{args.case}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    shutil.copy2(compiled_source, evidence / "compiled-workflow.json")
    (evidence / "agent-job.json").write_text(
        json.dumps(agent_job, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (evidence / "asset.json").write_text(
        json.dumps(asset, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (evidence / "ffprobe.json").write_text(
        json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "testCase": args.case,
        "status": "PASS",
        "startedAtEpoch": started_at,
        "finishedAtEpoch": time.time(),
        "blenderVersion": bpy.app.version_string,
        "pluginVersion": ".".join(map(str, flynotes_ai.bl_info["version"])),
        "agentVersion": health.get("version"),
        "jobId": job_id,
        "promptId": agent_job.get("promptId"),
        "actualSeed": agent_job.get("actualSeed"),
        "workflowVersion": agent_job.get("workflowVersion"),
        "outputPath": str(output_path),
        "outputSha256": sha256(output_path),
        "blendPath": str(blend_path),
        "vseStripPath": str(output_path),
        "port7860ListeningBefore": False,
        "port7860ListeningAfter": port_is_open(7860),
    }
    if summary["port7860ListeningAfter"]:
        raise RuntimeError("Release gate failed: TCP 7860 started listening during generation")
    (evidence / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"FLYNOTES_E2E_PASS {json.dumps(summary, ensure_ascii=False)}", flush=True)
    bpy.ops.preferences.addon_disable(module="flynotes_ai")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"FLYNOTES_E2E_FAIL {type(error).__name__}: {error}", flush=True)
        raise
