from __future__ import annotations

from .schemas import ModelSpec, ParameterField


def _h3_fields() -> list[ParameterField]:
    return [
        ParameterField(
            key="width",
            label="视频宽度",
            type="integer",
            default=480,
            required=True,
            minimum=32,
            maximum=4096,
            step=32,
        ),
        ParameterField(
            key="height",
            label="视频高度",
            type="integer",
            default=832,
            required=True,
            minimum=32,
            maximum=4096,
            step=32,
        ),
        ParameterField(
            key="duration",
            label="视频时长（秒）",
            type="number",
            default=5,
            required=True,
            minimum=2,
            maximum=15,
            step=1,
        ),
        ParameterField(
            key="steps",
            label="采样步数",
            type="integer",
            default=20,
            required=True,
            minimum=1,
            maximum=50,
            step=1,
            advanced=True,
        ),
        ParameterField(
            key="seed",
            label="Seed",
            type="integer",
            default=-1,
            required=True,
            minimum=-1,
            advanced=True,
        ),
        ParameterField(
            key="refImageSize",
            label="参考图处理尺寸",
            type="enum",
            default="match",
            options=["match", "max"],
            advanced=True,
        ),
    ]


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        id="minimax-h3-local",
        displayName="MiniMax H3（本地）",
        provider="comfyui",
        workflowId="minimax-h3",
        workflowVersion="260803",
        modes=["text", "first_frame", "first_last", "reference"],
        fields=_h3_fields(),
    ),
    ModelSpec(
        id="seedance-2",
        displayName="Seedance 2",
        provider="flynotes",
        modes=["text", "first_frame", "first_last", "reference"],
        available=False,
        requiresCloudAuth=True,
        statusMessage="Flynotes Provider 将在云端阶段接入",
    ),
    ModelSpec(
        id="seedance-2-fast",
        displayName="Seedance 2 Fast",
        provider="flynotes",
        modes=["text", "first_frame", "first_last", "reference"],
        available=False,
        requiresCloudAuth=True,
        statusMessage="Flynotes Provider 将在云端阶段接入",
    ),
    ModelSpec(
        id="seedance-2-mini",
        displayName="Seedance 2 Mini",
        provider="flynotes",
        modes=["text", "reference"],
        available=False,
        requiresCloudAuth=True,
        statusMessage="Flynotes Provider 将在云端阶段接入",
    ),
    ModelSpec(
        id="grok-video-1.5-preview",
        displayName="Grok Video 1.5",
        provider="flynotes",
        modes=["text"],
        available=False,
        requiresCloudAuth=True,
        statusMessage="Flynotes Provider 将在云端阶段接入",
    ),
)


class ModelRegistry:
    def __init__(self, models: tuple[ModelSpec, ...] = MODELS) -> None:
        self._models = {model.id: model for model in models}

    def list(self) -> list[ModelSpec]:
        return list(self._models.values())

    def get(self, model_id: str) -> ModelSpec | None:
        return self._models.get(model_id)

