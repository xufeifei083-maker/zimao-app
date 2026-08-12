from __future__ import annotations

from io import BytesIO

import pytest

from flynotes_agent.uploads import UploadNotFound, UploadStore


def test_upload_store_hashes_and_stages_safe_name(config) -> None:
    store = UploadStore(config.staging_path)
    upload = store.save(
        BytesIO(b"fake-png-data"),
        original_name="../角色图.PNG",
        content_type="image/png",
    )
    loaded, payload = store.get(upload.id)
    assert loaded == upload
    assert payload.name == "payload.png"

    relative = store.stage_for_comfy(
        upload_id=upload.id,
        comfy_input_root=config.comfy_root / "input",
        job_id="job_test",
        role="first_frame",
        index=0,
    )
    assert relative == "flynotes/job_test/first_frame_0.png"
    assert (config.comfy_root / "input" / relative).read_bytes() == b"fake-png-data"


def test_upload_store_rejects_unknown_id(config) -> None:
    with pytest.raises(UploadNotFound):
        UploadStore(config.staging_path).get("../../secret")
