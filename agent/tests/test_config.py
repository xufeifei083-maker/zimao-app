from pathlib import Path


def test_config_builds_expected_runtime_paths(config) -> None:
    assert config.comfy_python == config.comfy_root / "walkingwithai" / "python.exe"
    assert config.comfy_main == config.comfy_root / "main.py"
    assert config.comfy_base_url == "http://127.0.0.1:8188"
    assert config.runtime_validation_errors() == []


def test_config_reports_missing_runtime(config) -> None:
    broken = type(config)(
        comfy_root=Path("Z:/definitely-missing-comfy"),
        data_root=config.data_root,
    )

    errors = broken.runtime_validation_errors()

    assert len(errors) == 3


def test_config_writes_comfyui_extra_model_paths(config) -> None:
    config.ensure_directories()

    contents = config.extra_model_paths_config_path.read_text(encoding="utf-8")

    assert str(config.models_path).replace("\\", "/") in contents
    assert "checkpoints: checkpoints" in contents
    assert "text_encoders: text_encoders" in contents


def test_config_can_activate_managed_runtime(config) -> None:
    config.ensure_directories()
    runtime = config.runtimes_path / "win-nvidia-test"
    runtime.mkdir()

    config.activate_runtime("win-nvidia-test", runtime)

    assert config.comfy_root == runtime.resolve()
    assert config.runtime_pointer_path.is_file()
