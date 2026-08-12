from __future__ import annotations

import hashlib
import json
from typing import Any

from .registry import ModelRegistry


CONFIG_VERSION = "2026.08.10.1"


def build_blender_config(registry: ModelRegistry) -> dict[str, Any]:
    models: list[dict[str, Any]] = []
    for model in registry.list():
        entry: dict[str, Any] = {
            "modelId": model.id,
            "displayName": model.displayName,
            "provider": "local-agent",
            "mediaType": model.mediaType,
            "modes": model.modes,
            "enabled": model.available,
            "fields": [field.model_dump() for field in model.fields],
        }
        if model.id == "minimax-h3-local":
            entry.update(
                {
                    "inputSlots": {"maxImages": 9, "maxVideos": 3, "maxAudios": 3},
                    "ratios": ["9:16", "16:9", "1:1"],
                    "resolutions": ["480P"],
                    "durations": list(range(2, 16)),
                }
            )
        models.append(entry)
    return {
        "schemaVersion": 1,
        "configVersion": CONFIG_VERSION,
        "models": models,
    }


def config_sha256(config: dict[str, Any]) -> str:
    raw = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
