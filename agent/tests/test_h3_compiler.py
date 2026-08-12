from __future__ import annotations

import pytest

from flynotes_agent.h3_compiler import H3Inputs, H3WorkflowCompiler, H3WorkflowError


@pytest.fixture
def compiler() -> H3WorkflowCompiler:
    return H3WorkflowCompiler()


def test_text_to_video_maps_all_public_parameters(compiler: H3WorkflowCompiler) -> None:
    compiled = compiler.compile(
        mode="text",
        prompt="cinematic city",
        parameters={"width": 608, "height": 352, "duration": 6, "steps": 24, "seed": 42},
        filename_prefix="video/job_1/result",
    )
    workflow = compiled.workflow
    assert len(workflow) == 19
    assert compiled.actual_seed == 42
    assert workflow["131"]["inputs"]["prompt"] == "cinematic city"
    assert workflow["135"]["inputs"]["value"] == 608
    assert workflow["136"]["inputs"]["value"] == 352
    assert workflow["133"]["inputs"]["value"] == 6.0
    assert workflow["124"]["inputs"]["steps"] == 24
    assert workflow["129"]["inputs"]["noise_seed"] == 42
    assert workflow["92"]["inputs"]["filename_prefix"] == "video/job_1/result"


def test_first_frame_prunes_last_frame_branch(compiler: H3WorkflowCompiler) -> None:
    workflow = compiler.compile(
        mode="first_frame",
        prompt="camera dolly in",
        inputs=H3Inputs(first_frame="first.png"),
    ).workflow
    assert workflow["114"]["inputs"]["image"] == "first.png"
    assert "last_frame" not in workflow["133"]["inputs"]
    assert "137" not in workflow
    assert "144" not in workflow


def test_first_last_keeps_both_frames(compiler: H3WorkflowCompiler) -> None:
    workflow = compiler.compile(
        mode="first_last",
        prompt="smooth transition",
        inputs=H3Inputs(first_frame="first.png", last_frame="last.png"),
    ).workflow
    assert workflow["114"]["inputs"]["image"] == "first.png"
    assert workflow["137"]["inputs"]["image"] == "last.png"
    assert workflow["133"]["inputs"]["last_frame"] == ["144", 0]


def test_reference_mode_prunes_unused_slots_and_preserves_slot_numbers(
    compiler: H3WorkflowCompiler,
) -> None:
    workflow = compiler.compile(
        mode="reference",
        prompt="use the supplied media",
        parameters={"refImageSize": "max"},
        inputs=H3Inputs(
            reference_images=[None, "style.png"],
            reference_videos=["motion.mp4"],
            reference_audios=[None, None, "voice.wav"],
        ),
    ).workflow
    inputs = workflow["136"]["inputs"]
    assert "137" not in workflow and "159" not in workflow
    assert workflow["139"]["inputs"]["image"] == "style.png"
    assert inputs["ref_images.ref_image_1"] == ["162", 0]
    assert workflow["148"]["inputs"]["video"] == "motion.mp4"
    assert inputs["ref_video_audios.ref_video_audio_0"] == ["148", 2]
    assert "149" not in workflow and "150" not in workflow
    assert workflow["153"]["inputs"]["audio"] == "voice.wav"
    assert inputs["ref_audios.ref_audio_2"] == ["153", 0]
    assert inputs["ref_image_size"] == "max"


@pytest.mark.parametrize("width", [31, 600, 641])
def test_dimensions_must_be_multiples_of_32(
    compiler: H3WorkflowCompiler, width: int
) -> None:
    with pytest.raises(H3WorkflowError, match="32 的倍数"):
        compiler.compile(mode="text", prompt="test", parameters={"width": width})


def test_first_last_requires_last_frame(compiler: H3WorkflowCompiler) -> None:
    with pytest.raises(H3WorkflowError, match="尾帧"):
        compiler.compile(
            mode="first_last",
            prompt="test",
            inputs=H3Inputs(first_frame="first.png"),
        )


def test_random_seed_is_resolved(compiler: H3WorkflowCompiler) -> None:
    compiled = compiler.compile(mode="text", prompt="test", parameters={"seed": -1})
    assert 0 <= compiled.actual_seed <= compiler.MAX_SEED
    assert compiled.workflow["129"]["inputs"]["noise_seed"] == compiled.actual_seed
