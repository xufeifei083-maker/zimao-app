from __future__ import annotations

from io import BytesIO

from flynotes_agent.registry import ModelRegistry
from flynotes_agent.repository import JobRepository
from flynotes_agent.schemas import JobClient, JobCreateRequest, JobInput
from flynotes_agent.schemas import JobStatus, RuntimeState, RuntimeStatusResponse
from flynotes_agent.uploads import UploadStore
from flynotes_agent.worker import JobWorker


class UnusedRuntime:
    pass


class ReadyRuntime:
    async def status(self) -> RuntimeStatusResponse:
        return RuntimeStatusResponse(
            state=RuntimeState.READY,
            baseUrl="http://127.0.0.1:8188",
            root="test",
            managed=True,
        )


class SuccessfulComfy:
    def __init__(self) -> None:
        self.workflow = None

    async def submit_prompt(self, workflow, *, client_id):
        self.workflow = workflow
        return "prompt-test"

    async def history(self, prompt_id):
        return {
            "status": {"completed": True, "status_str": "success"},
            "outputs": {
                "92": {
                    "gifs": [
                        {
                            "filename": "result.mp4",
                            "subfolder": "",
                            "type": "output",
                        }
                    ]
                }
            },
        }

    async def queue(self):
        return {"queue_running": [], "queue_pending": []}


def test_worker_stages_roles_without_exposing_original_paths(config) -> None:
    repository = JobRepository(config.database_path, ModelRegistry())
    repository.initialize()
    uploads = UploadStore(config.staging_path)
    first = uploads.save(BytesIO(b"first"), original_name="../../first.png")
    last = uploads.save(BytesIO(b"last"), original_name="last.png")
    job = repository.create(
        JobCreateRequest(
            clientRequestId="worker-test",
            client=JobClient(type="blender"),
            modelId="minimax-h3-local",
            mode="first_last",
            prompt="test",
            inputs=[
                JobInput(uploadId=first.id, role="first_frame"),
                JobInput(uploadId=last.id, role="last_frame"),
            ],
        )
    )
    worker = JobWorker(
        config,
        repository,
        UnusedRuntime(),  # type: ignore[arg-type]
        uploads,
    )

    material = worker._stage_inputs(job)

    assert material.first_frame == f"flynotes/{job.id}/first_frame_0.png"
    assert material.last_frame == f"flynotes/{job.id}/last_frame_0.png"


async def test_worker_submits_and_records_successful_text_job(config) -> None:
    repository = JobRepository(config.database_path, ModelRegistry())
    repository.initialize()
    uploads = UploadStore(config.staging_path)
    comfy = SuccessfulComfy()
    output = config.comfy_root / "output" / "result.mp4"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"video")
    job = repository.create(
        JobCreateRequest(
            clientRequestId="worker-success",
            client=JobClient(type="desktop"),
            modelId="minimax-h3-local",
            mode="text",
            prompt="cinematic test",
            parameters={"seed": 42},
        )
    )
    worker = JobWorker(
        config,
        repository,
        ReadyRuntime(),  # type: ignore[arg-type]
        uploads,
        comfy=comfy,  # type: ignore[arg-type]
    )

    await worker._submit(job)

    finished = repository.get(job.id)
    assert finished is not None
    assert finished.status == JobStatus.SUCCEEDED
    assert finished.promptId == "prompt-test"
    assert finished.actualSeed == 42
    assert finished.resultPath == str(output.resolve())
    assert comfy.workflow["131"]["inputs"]["prompt"] == "cinematic test"
