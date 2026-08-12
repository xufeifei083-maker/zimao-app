from __future__ import annotations

import pytest

from flynotes_agent.registry import ModelRegistry
from flynotes_agent.repository import DuplicateClientRequest, JobRepository
from flynotes_agent.schemas import JobClient, JobCreateRequest, JobInput, JobStatus


def _request(request_id: str = "request-1") -> JobCreateRequest:
    return JobCreateRequest(
        clientRequestId=request_id,
        client=JobClient(type="blender", version="test", instanceId="instance-1"),
        modelId="minimax-h3-local",
        mode="text",
        prompt="测试提示词",
        parameters={"width": 480, "height": 832},
    )


def test_repository_creates_and_reads_job(config) -> None:
    repository = JobRepository(config.database_path, ModelRegistry())
    repository.initialize()

    created = repository.create(_request())

    assert created.id.startswith("job_")
    assert created.status == JobStatus.CREATED
    assert repository.get(created.id) == created
    assert repository.list() == [created]


def test_repository_rejects_duplicate_client_request(config) -> None:
    repository = JobRepository(config.database_path, ModelRegistry())
    repository.initialize()
    repository.create(_request())

    with pytest.raises(DuplicateClientRequest):
        repository.create(_request())


def test_repository_cancels_non_terminal_job(config) -> None:
    repository = JobRepository(config.database_path, ModelRegistry())
    repository.initialize()
    created = repository.create(_request())

    cancelled = repository.cancel(created.id)

    assert cancelled is not None
    assert cancelled.status == JobStatus.CANCELLED


def test_repository_persists_inputs_and_execution_fields(config) -> None:
    repository = JobRepository(config.database_path, ModelRegistry())
    repository.initialize()
    request = _request()
    request.inputs = [JobInput(uploadId="upload_123", role="first_frame")]
    created = repository.create(request)

    updated = repository.update(
        created.id,
        status=JobStatus.QUEUED,
        prompt_id="prompt-1",
        actual_seed=99,
    )

    assert updated is not None
    assert updated.inputs[0].uploadId == "upload_123"
    assert updated.promptId == "prompt-1"
    assert updated.actualSeed == 99
    assert repository.next_with_statuses({JobStatus.QUEUED}) == updated
