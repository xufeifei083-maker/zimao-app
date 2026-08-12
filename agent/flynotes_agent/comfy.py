from __future__ import annotations

from typing import Any

import httpx


class ComfyClient:
    def __init__(self, base_url: str, timeout: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def system_stats(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/system_stats")
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def queue(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/queue")
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {}
        except (httpx.HTTPError, ValueError):
            return {}

    async def is_ready(self) -> bool:
        return await self.system_stats() is not None

    async def object_info(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=max(self.timeout, 15)) as client:
            response = await client.get(f"{self.base_url}/object_info")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("ComfyUI object_info 返回格式无效")
            return data

    async def submit_prompt(
        self, workflow: dict[str, Any], *, client_id: str
    ) -> str:
        async with httpx.AsyncClient(timeout=max(self.timeout, 30)) as client:
            response = await client.post(
                f"{self.base_url}/prompt",
                json={"prompt": workflow, "client_id": client_id},
            )
            response.raise_for_status()
            data = response.json()
        prompt_id = data.get("prompt_id") if isinstance(data, dict) else None
        if not isinstance(prompt_id, str) or not prompt_id:
            node_errors = data.get("node_errors") if isinstance(data, dict) else None
            raise ValueError(f"ComfyUI 未返回 prompt_id：{node_errors or data}")
        return prompt_id

    async def history(self, prompt_id: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=max(self.timeout, 15)) as client:
            response = await client.get(f"{self.base_url}/history/{prompt_id}")
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            return None
        entry = data.get(prompt_id)
        return entry if isinstance(entry, dict) else None

    async def cancel(self, prompt_id: str, *, interrupt: bool = False) -> None:
        async with httpx.AsyncClient(timeout=max(self.timeout, 15)) as client:
            await client.post(
                f"{self.base_url}/queue", json={"delete": [prompt_id]}
            )
            if interrupt:
                await client.post(f"{self.base_url}/interrupt")
