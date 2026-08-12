from __future__ import annotations

from flynotes_agent.assets import AssetStore
from flynotes_agent.registry import ModelRegistry
from flynotes_agent.repository import JobRepository
from flynotes_agent.schemas import JobClient, JobCreateRequest


def test_asset_store_registers_once_and_preserves_job_metadata(config) -> None:
    repository = JobRepository(config.database_path, ModelRegistry())
    repository.initialize()
    job = repository.create(
        JobCreateRequest(
            clientRequestId="asset-test",
            client=JobClient(type="blender"),
            modelId="minimax-h3-local",
            mode="text",
            prompt="asset prompt",
            parameters={"width": 480, "height": 832},
        )
    )
    job = repository.update(job.id, actual_seed=42)
    assert job is not None
    video = config.comfy_root / "output" / "asset-test.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"fake-video")
    store = AssetStore(config)
    store.initialize()

    created = store.register(job, video)
    duplicate = store.register(job, video)

    assert duplicate.id == created.id
    assert created.jobId == job.id
    assert created.actualSeed == 42
    assert created.parameters["width"] == 480
    assert store.list() == [created]
