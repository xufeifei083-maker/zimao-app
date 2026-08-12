from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import psutil

from .comfy import ComfyClient
from .config import AgentConfig
from .schemas import RuntimeState, RuntimeStatusResponse


class ComfyRuntimeError(RuntimeError):
    code = "COMFY_START_FAILED"


class ComfyPortConflict(ComfyRuntimeError):
    code = "COMFY_PORT_CONFLICT"


class ComfyNotManaged(ComfyRuntimeError):
    code = "COMFY_NOT_MANAGED"


class ComfyRuntimeManager:
    def __init__(
        self,
        config: AgentConfig,
        client: ComfyClient | None = None,
    ) -> None:
        self.config = config
        self.client = client or ComfyClient(config.comfy_base_url)
        self._lock = asyncio.Lock()

    @staticmethod
    def _listening_pid(port: int) -> int | None:
        try:
            for connection in psutil.net_connections(kind="tcp"):
                if (
                    connection.status == psutil.CONN_LISTEN
                    and connection.laddr
                    and connection.laddr.port == port
                ):
                    return connection.pid
        except (psutil.AccessDenied, psutil.Error):
            return None
        return None

    def _is_managed_process(self, pid: int | None) -> bool:
        if not pid:
            return False
        try:
            process = psutil.Process(pid)
            executable = Path(process.exe()).resolve()
            expected = self.config.comfy_python.resolve()
            command = " ".join(process.cmdline()).lower()
            return executable == expected and "main.py" in command and "start.py" not in command
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return False

    async def status(self) -> RuntimeStatusResponse:
        validation_errors = self.config.runtime_validation_errors()
        stats = await self.client.system_stats()
        pid = self._listening_pid(self.config.comfy_port)

        if stats is None:
            if pid:
                return RuntimeStatusResponse(
                    state=RuntimeState.CONFLICT,
                    baseUrl=self.config.comfy_base_url,
                    root=str(self.config.comfy_root),
                    pid=pid,
                    errors=["8188 已被占用，但该端口未返回有效 ComfyUI 状态"],
                    message="端口冲突",
                )
            state = RuntimeState.ERROR if validation_errors else RuntimeState.STOPPED
            return RuntimeStatusResponse(
                state=state,
                baseUrl=self.config.comfy_base_url,
                root=str(self.config.comfy_root),
                errors=validation_errors,
                message="运行时配置无效" if validation_errors else "ComfyUI 已停止",
            )

        queue = await self.client.queue()
        system = stats.get("system", {}) if isinstance(stats, dict) else {}
        managed = self._is_managed_process(pid)
        warnings: list[str] = []
        if pid and not managed:
            warnings.append("检测到兼容 ComfyUI，但它不是通过当前 main.py 管理方式启动")
        return RuntimeStatusResponse(
            state=RuntimeState.WARNING if warnings else RuntimeState.READY,
            baseUrl=self.config.comfy_base_url,
            root=str(self.config.comfy_root),
            pid=pid,
            managed=managed,
            comfyVersion=system.get("comfyui_version"),
            pythonVersion=system.get("python_version"),
            queueRunning=len(queue.get("queue_running", [])),
            queuePending=len(queue.get("queue_pending", [])),
            warnings=warnings,
            message="ComfyUI 运行中",
        )

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        root = self.config.comfy_root
        env.update(
            {
                "HF_HOME": str(root / "models"),
                "TORCH_HOME": str(root / "models"),
                "PYANNOTE_CACHE": str(root / "models" / "pyannote"),
                "KERAS_BACKEND": "torch",
            }
        )
        extra_path = [
            str(root / "ffmpeg" / "bin"),
        ]
        env["PATH"] = os.pathsep.join(extra_path + [env.get("PATH", "")])
        return env

    def _launch(self) -> int:
        self.config.ensure_directories()
        log_handle = self.config.comfy_log_path.open("ab", buffering=0)
        args = [
            str(self.config.comfy_python),
            "-s",
            "main.py",
            "--listen",
            self.config.comfy_host,
            "--port",
            str(self.config.comfy_port),
            "--disable-metadata",
            "--output-directory",
            str(self.config.generated_path),
            "--extra-model-paths-config",
            str(self.config.extra_model_paths_config_path),
        ]
        kwargs: dict[str, Any] = {
            "cwd": str(self.config.comfy_root),
            "env": self._environment(),
            "stdin": subprocess.DEVNULL,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(args, **kwargs)
        finally:
            log_handle.close()
        self.config.comfy_pid_path.write_text(str(process.pid), encoding="utf-8")
        return process.pid

    async def start(self) -> RuntimeStatusResponse:
        async with self._lock:
            current = await self.status()
            if current.state in {RuntimeState.READY, RuntimeState.WARNING}:
                return current
            if current.state == RuntimeState.CONFLICT:
                raise ComfyPortConflict(current.message)
            errors = self.config.runtime_validation_errors()
            if errors:
                raise ComfyRuntimeError("；".join(errors))

            pid = await asyncio.to_thread(self._launch)
            deadline = time.monotonic() + self.config.comfy_start_timeout_seconds
            while time.monotonic() < deadline:
                if await self.client.is_ready():
                    return await self.status()
                if not psutil.pid_exists(pid):
                    raise ComfyRuntimeError(
                        f"ComfyUI 进程提前退出，请查看日志：{self.config.comfy_log_path}"
                    )
                await asyncio.sleep(1)
            raise ComfyRuntimeError(
                f"ComfyUI 启动超时，请查看日志：{self.config.comfy_log_path}"
            )

    def _read_pid(self) -> int | None:
        try:
            return int(self.config.comfy_pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return self._listening_pid(self.config.comfy_port)

    @staticmethod
    def _terminate_tree(pid: int) -> None:
        process = psutil.Process(pid)
        children = process.children(recursive=True)
        for child in children:
            child.terminate()
        process.terminate()
        _, alive = psutil.wait_procs([*children, process], timeout=10)
        for item in alive:
            item.kill()

    async def stop(self) -> RuntimeStatusResponse:
        async with self._lock:
            current = await self.status()
            if current.state == RuntimeState.STOPPED:
                return current
            pid = self._read_pid()
            if not self._is_managed_process(pid):
                raise ComfyNotManaged(
                    "当前 8188 实例不是由 Local Agent 通过 main.py 启动，拒绝自动结束"
                )
            try:
                await asyncio.to_thread(self._terminate_tree, pid)
            except psutil.NoSuchProcess:
                pass
            self.config.comfy_pid_path.unlink(missing_ok=True)
            for _ in range(20):
                if not await self.client.is_ready():
                    break
                await asyncio.sleep(0.5)
            return await self.status()

    async def restart(self) -> RuntimeStatusResponse:
        await self.stop()
        return await self.start()
