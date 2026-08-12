from flynotes_agent.registry import ModelRegistry


def test_h3_is_local_and_available() -> None:
    model = ModelRegistry().get("minimax-h3-local")

    assert model is not None
    assert model.displayName == "MiniMax H3（本地）"
    assert model.provider == "comfyui"
    assert model.available is True
    assert model.requiresCloudAuth is False
    assert set(model.modes) == {"text", "first_frame", "first_last", "reference"}


def test_cloud_models_are_visible_but_not_enabled_in_first_slice() -> None:
    models = ModelRegistry().list()
    cloud = [model for model in models if model.provider == "flynotes"]

    assert {model.id for model in cloud} >= {
        "seedance-2",
        "seedance-2-fast",
        "grok-video-1.5-preview",
    }
    assert all(not model.available for model in cloud)
    assert all(model.requiresCloudAuth for model in cloud)

