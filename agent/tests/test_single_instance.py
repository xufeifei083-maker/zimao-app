from __future__ import annotations

import os
import uuid

import pytest

from flynotes_agent.single_instance import AlreadyRunning, SingleInstance


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex")
def test_single_instance_rejects_second_owner() -> None:
    name = f"Local\\FlynotesAgentTest-{uuid.uuid4()}"
    with SingleInstance(name):
        with pytest.raises(AlreadyRunning):
            with SingleInstance(name):
                pass
