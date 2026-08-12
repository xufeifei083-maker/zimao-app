from __future__ import annotations

import os
import json
from dataclasses import dataclass
from pathlib import Path


DEFAULT_WORKFLOW_CATALOG_URL = (
    "https://raw.githubusercontent.com/xufeifei083-maker/"
    "zimao-workflows/catalog-260803-1/catalog/catalog.json"
)
DEFAULT_WORKFLOW_CATALOG_PUBLIC_KEY = "r+yYk1hKvlN+mlhdxR8SzjvuvSHQ/Rtg6I7kScKj1GA="
DEFAULT_RUNTIME_ID = "win-nvidia-h3-2026.08.2"
DEFAULT_RUNTIME_MANIFEST_URL = (
    "https://github.com/xufeifei083-maker/zimao-runtime/releases/download/"
    "win-nvidia-h3-2026.08.2/runtime-manifest.json"
)
DEFAULT_RUNTIME_PUBLIC_KEY = "9JQPS+MURxHKkpRM05IC+98YgaXCzRd0W7efBCnRYrA="


def _default_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "FlynotesAI"
    return Path.home() / ".flynotes-ai"


DEFAULT_COMFY_ROOT = _default_data_root() / "runtimes" / DEFAULT_RUNTIME_ID


def _resolved_comfy_root(data_root: Path) -> Path:
    explicit = os.environ.get("FLYNOTES_COMFY_ROOT")
    if explicit:
        return Path(explicit)
    pointer = data_root / "runtimes" / "current.json"
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
        candidate = Path(value["path"])
        if candidate.is_dir():
            return candidate
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return data_root / "runtimes" / DEFAULT_RUNTIME_ID


@dataclass(slots=True)
class AgentConfig:
    host: str = "127.0.0.1"
    port: int = 17980
    comfy_host: str = "127.0.0.1"
    comfy_port: int = 8188
    comfy_root: Path = DEFAULT_COMFY_ROOT
    data_root: Path = _default_data_root()
    comfy_start_timeout_seconds: float = 90.0
    auto_start_comfy_on_job: bool = True
    flynotes_base_url: str = "https://flynotes.top/api/v1"
    plugin_repository: str = ""
    plugin_public_key: str = ""
    workflow_catalog_url: str = DEFAULT_WORKFLOW_CATALOG_URL
    workflow_catalog_public_key: str = DEFAULT_WORKFLOW_CATALOG_PUBLIC_KEY
    runtime_id: str = DEFAULT_RUNTIME_ID
    runtime_manifest_url: str = DEFAULT_RUNTIME_MANIFEST_URL
    runtime_public_key: str = DEFAULT_RUNTIME_PUBLIC_KEY

    @classmethod
    def from_env(cls) -> "AgentConfig":
        data_root = Path(
            os.environ.get("FLYNOTES_DATA_ROOT", str(_default_data_root()))
        )
        return cls(
            host=os.environ.get("FLYNOTES_AGENT_HOST", "127.0.0.1"),
            port=int(os.environ.get("FLYNOTES_AGENT_PORT", "17980")),
            comfy_host=os.environ.get("FLYNOTES_COMFY_HOST", "127.0.0.1"),
            comfy_port=int(os.environ.get("FLYNOTES_COMFY_PORT", "8188")),
            comfy_root=_resolved_comfy_root(data_root),
            data_root=data_root,
            comfy_start_timeout_seconds=float(
                os.environ.get("FLYNOTES_COMFY_START_TIMEOUT", "90")
            ),
            auto_start_comfy_on_job=os.environ.get(
                "FLYNOTES_AUTO_START_COMFY", "1"
            ).lower()
            not in {"0", "false", "no"},
            flynotes_base_url=os.environ.get(
                "FLYNOTES_CLOUD_BASE_URL", "https://flynotes.top/api/v1"
            ).rstrip("/"),
            plugin_repository=os.environ.get("FLYNOTES_PLUGIN_REPOSITORY", ""),
            plugin_public_key=os.environ.get("FLYNOTES_PLUGIN_PUBLIC_KEY", ""),
            workflow_catalog_url=os.environ.get(
                "ZIMAO_WORKFLOW_CATALOG_URL", DEFAULT_WORKFLOW_CATALOG_URL
            ),
            workflow_catalog_public_key=os.environ.get(
                "ZIMAO_WORKFLOW_CATALOG_PUBLIC_KEY",
                DEFAULT_WORKFLOW_CATALOG_PUBLIC_KEY,
            ),
            runtime_id=os.environ.get("ZIMAO_RUNTIME_ID", DEFAULT_RUNTIME_ID),
            runtime_manifest_url=os.environ.get(
                "ZIMAO_RUNTIME_MANIFEST_URL", DEFAULT_RUNTIME_MANIFEST_URL
            ),
            runtime_public_key=os.environ.get(
                "ZIMAO_RUNTIME_PUBLIC_KEY", DEFAULT_RUNTIME_PUBLIC_KEY
            ),
        )

    @property
    def agent_base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def comfy_base_url(self) -> str:
        return f"http://{self.comfy_host}:{self.comfy_port}"

    @property
    def comfy_python(self) -> Path:
        return self.comfy_root / "python_runtime" / "python.exe"

    @property
    def comfy_main(self) -> Path:
        return self.comfy_root / "main.py"

    @property
    def database_path(self) -> Path:
        return self.data_root / "database" / "agent.sqlite3"

    @property
    def runtime_state_dir(self) -> Path:
        return self.data_root / "runtime"

    @property
    def comfy_pid_path(self) -> Path:
        return self.runtime_state_dir / "comfyui.pid"

    @property
    def comfy_log_path(self) -> Path:
        return self.data_root / "logs" / "comfyui.log"

    @property
    def agent_log_path(self) -> Path:
        return self.data_root / "logs" / "agent.log"

    @property
    def plugin_path(self) -> Path:
        return self.data_root / "plugins"

    @property
    def plugin_state_path(self) -> Path:
        return self.plugin_path / "state.json"

    @property
    def generated_path(self) -> Path:
        return self.data_root / "generated"

    @property
    def staging_path(self) -> Path:
        return self.data_root / "staging"

    @property
    def workflows_path(self) -> Path:
        return self.data_root / "workflows"

    @property
    def models_path(self) -> Path:
        return self.data_root / "models"

    @property
    def catalog_cache_path(self) -> Path:
        return self.data_root / "catalog" / "catalog.json"

    @property
    def runtimes_path(self) -> Path:
        return self.data_root / "runtimes"

    @property
    def runtime_downloads_path(self) -> Path:
        return self.data_root / "downloads" / "runtime"

    @property
    def runtime_pointer_path(self) -> Path:
        return self.runtimes_path / "current.json"

    def activate_runtime(self, runtime_id: str, path: Path) -> None:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.runtimes_path.resolve())
        except ValueError as error:
            raise ValueError("Runtime path must stay inside the managed runtimes directory") from error
        temporary = self.runtime_pointer_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"runtimeId": runtime_id, "path": str(resolved)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.runtime_pointer_path)
        self.comfy_root = resolved

    @property
    def workflow_install_state_path(self) -> Path:
        return self.data_root / "downloads" / "workflow-installations.json"

    @property
    def extra_model_paths_config_path(self) -> Path:
        return self.data_root / "runtime" / "zimao-model-paths.yaml"

    def write_extra_model_paths_config(self) -> None:
        base_path = str(self.models_path.resolve()).replace("\\", "/")
        content = (
            "zimao:\n"
            f"  base_path: \"{base_path}\"\n"
            "  is_default: true\n"
            "  checkpoints: checkpoints\n"
            "  diffusion_models: diffusion_models\n"
            "  vae: vae\n"
            "  text_encoders: text_encoders\n"
            "  clip_vision: clip_vision\n"
            "  loras: loras\n"
            "  upscale_models: upscale_models\n"
            "  audio_encoders: audio_encoders\n"
        )
        temporary = self.extra_model_paths_config_path.with_suffix(".tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, self.extra_model_paths_config_path)

    def ensure_directories(self) -> None:
        for path in (
            self.database_path.parent,
            self.runtime_state_dir,
            self.comfy_log_path.parent,
            self.generated_path,
            self.staging_path,
            self.plugin_path,
            self.workflows_path,
            self.models_path,
            self.catalog_cache_path.parent,
            self.workflow_install_state_path.parent,
            self.runtimes_path,
            self.runtime_downloads_path,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.write_extra_model_paths_config()

    def runtime_validation_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.comfy_root.is_dir():
            errors.append(f"ComfyUI 目录不存在：{self.comfy_root}")
        if not self.comfy_python.is_file():
            errors.append(f"ComfyUI Python 不存在：{self.comfy_python}")
        if not self.comfy_main.is_file():
            errors.append(f"ComfyUI main.py 不存在：{self.comfy_main}")
        return errors
