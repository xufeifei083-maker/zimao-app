from __future__ import annotations

import copy
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class H3WorkflowError(ValueError):
    """A user-supplied H3 parameter or input cannot be compiled."""


@dataclass(slots=True)
class H3Inputs:
    first_frame: str | None = None
    last_frame: str | None = None
    reference_images: list[str | None] = field(default_factory=list)
    reference_videos: list[str | None] = field(default_factory=list)
    reference_audios: list[str | None] = field(default_factory=list)


@dataclass(slots=True)
class CompiledWorkflow:
    workflow: dict[str, Any]
    actual_seed: int
    filename_prefix: str


class H3WorkflowCompiler:
    SUPPORTED_MODES = {"text", "first_frame", "first_last", "reference"}
    MAX_SEED = 1_125_899_906_842_624

    def __init__(self, package_dir: Path | None = None) -> None:
        self.package_dir = package_dir or (
            Path(__file__).parent
            / "workflow_packages"
            / "minimax-h3"
            / "260803"
        )
        self.manifest = self._load_json("manifest.json")
        self.mapping = self._load_json("node-mapping.json")

    def _load_json(self, filename: str) -> dict[str, Any]:
        path = self.package_dir / filename
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise H3WorkflowError(f"无法读取 H3 工作流包：{path}") from error
        if not isinstance(data, dict):
            raise H3WorkflowError(f"H3 工作流包格式无效：{path}")
        return data

    @staticmethod
    def _integer(
        value: Any,
        name: str,
        *,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise H3WorkflowError(f"{name} 必须是整数")
        if value < minimum or (maximum is not None and value > maximum):
            bound = f"{minimum}–{maximum}" if maximum is not None else f"不小于 {minimum}"
            raise H3WorkflowError(f"{name} 必须在 {bound} 范围内")
        return value

    @staticmethod
    def _dimension(value: Any, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise H3WorkflowError(f"{name} 必须是整数")
        result = value
        if result < 32 or result % 32:
            raise H3WorkflowError(f"{name} 必须是 32 的倍数")
        return result

    @staticmethod
    def _duration(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise H3WorkflowError("时长必须是数字")
        result = float(value)
        if not 2 <= result <= 15:
            raise H3WorkflowError("时长必须在 2–15 秒范围内")
        return result

    @staticmethod
    def _clean_slots(values: list[str | None], limit: int, label: str) -> list[str | None]:
        if len(values) > limit:
            raise H3WorkflowError(f"{label}最多支持 {limit} 个")
        cleaned: list[str | None] = []
        for value in values:
            if value is None:
                cleaned.append(None)
                continue
            normalized = value.strip()
            cleaned.append(normalized or None)
        return cleaned + [None] * (limit - len(cleaned))

    def compile(
        self,
        *,
        mode: str,
        prompt: str,
        parameters: dict[str, Any] | None = None,
        inputs: H3Inputs | None = None,
        filename_prefix: str = "video/Flynotes_H3",
    ) -> CompiledWorkflow:
        if mode not in self.SUPPORTED_MODES:
            raise H3WorkflowError(f"不支持的 H3 模式：{mode}")
        normalized_prompt = prompt.strip()
        if not normalized_prompt:
            raise H3WorkflowError("提示词不能为空")

        params = parameters or {}
        width = self._dimension(params.get("width", 480), "宽度")
        height = self._dimension(params.get("height", 832), "高度")
        duration = self._duration(params.get("duration", 5))
        steps = self._integer(params.get("steps", 20), "采样步数", minimum=1, maximum=50)
        requested_seed = self._integer(
            params.get("seed", -1), "随机种子", minimum=-1, maximum=self.MAX_SEED
        )
        actual_seed = (
            secrets.randbelow(self.MAX_SEED + 1) if requested_seed == -1 else requested_seed
        )
        prefix = filename_prefix.strip().replace("\\", "/").strip("/")
        if not prefix or ".." in prefix.split("/"):
            raise H3WorkflowError("输出文件前缀无效")

        template_name = self.manifest["modes"][mode]
        workflow = copy.deepcopy(self._load_json(template_name))
        mapping = self.mapping[mode]
        material = inputs or H3Inputs()

        workflow[mapping["output"]]["inputs"]["filename_prefix"] = prefix
        workflow[mapping["steps"]]["inputs"]["steps"] = steps
        workflow[mapping["seed"]]["inputs"]["noise_seed"] = actual_seed

        if mode == "text":
            workflow[mapping["prompt"]]["inputs"]["prompt"] = normalized_prompt
            workflow[mapping["duration"]]["inputs"]["value"] = duration
            workflow[mapping["width"]]["inputs"]["value"] = width
            workflow[mapping["height"]]["inputs"]["value"] = height
        elif mode in {"first_frame", "first_last"}:
            self._compile_image_mode(
                workflow, mapping, material, mode, normalized_prompt, width, height, duration
            )
        else:
            self._compile_reference_mode(
                workflow,
                mapping,
                material,
                normalized_prompt,
                width,
                height,
                duration,
                params.get("refImageSize", "match"),
            )

        return CompiledWorkflow(
            workflow=workflow,
            actual_seed=actual_seed,
            filename_prefix=prefix,
        )

    @staticmethod
    def _compile_image_mode(
        workflow: dict[str, Any],
        mapping: dict[str, Any],
        material: H3Inputs,
        mode: str,
        prompt: str,
        width: int,
        height: int,
        duration: float,
    ) -> None:
        first_frame = (material.first_frame or "").strip()
        if not first_frame:
            raise H3WorkflowError("首帧不能为空")
        workflow[mapping["firstFrame"]]["inputs"]["image"] = first_frame
        workflow[mapping["prompt"]]["inputs"]["prompt"] = prompt
        workflow[mapping["duration"]]["inputs"]["value"] = duration
        workflow[mapping["width"]]["inputs"]["value"] = width
        workflow[mapping["height"]]["inputs"]["value"] = height

        last_frame = (material.last_frame or "").strip()
        if mode == "first_last" and not last_frame:
            raise H3WorkflowError("首尾帧模式必须提供尾帧")
        if last_frame:
            workflow[mapping["lastFrame"]]["inputs"]["image"] = last_frame
            return

        conditioning = workflow[mapping["prompt"]]["inputs"]
        conditioning.pop("last_frame", None)
        last_loader = mapping["lastFrame"]
        workflow.pop(last_loader, None)
        for node_id, node in list(workflow.items()):
            if node.get("class_type") == "ImageResizeKJv2":
                image_input = node.get("inputs", {}).get("image")
                if image_input == [last_loader, 0]:
                    workflow.pop(node_id, None)

    def _compile_reference_mode(
        self,
        workflow: dict[str, Any],
        mapping: dict[str, Any],
        material: H3Inputs,
        prompt: str,
        width: int,
        height: int,
        duration: float,
        ref_image_size: Any,
    ) -> None:
        if ref_image_size not in {"match", "max"}:
            raise H3WorkflowError("参考图尺寸策略必须是 match 或 max")
        workflow[mapping["prompt"]]["inputs"]["value"] = prompt
        workflow[mapping["duration"]]["inputs"]["value"] = duration
        workflow[mapping["width"]]["inputs"]["value"] = width
        workflow[mapping["height"]]["inputs"]["value"] = height
        conditioning = workflow[mapping["conditioning"]]["inputs"]
        conditioning["ref_image_size"] = ref_image_size

        groups = (
            (
                self._clean_slots(material.reference_images, 9, "参考图片"),
                mapping["imageLoaders"],
                mapping["imageResize"],
                "image",
                ("ref_images.ref_image_",),
            ),
            (
                self._clean_slots(material.reference_videos, 3, "参考视频"),
                mapping["videoLoaders"],
                None,
                "video",
                ("ref_videos.ref_video_", "ref_video_audios.ref_video_audio_"),
            ),
            (
                self._clean_slots(material.reference_audios, 3, "参考音频"),
                mapping["audioLoaders"],
                None,
                "audio",
                ("ref_audios.ref_audio_",),
            ),
        )
        for values, loaders, resize_nodes, input_key, prefixes in groups:
            for index, (value, loader_id) in enumerate(zip(values, loaders, strict=True)):
                if value:
                    workflow[loader_id]["inputs"][input_key] = value
                    continue
                workflow.pop(loader_id, None)
                if resize_nodes:
                    workflow.pop(resize_nodes[index], None)
                for key_prefix in prefixes:
                    conditioning.pop(f"{key_prefix}{index}", None)
