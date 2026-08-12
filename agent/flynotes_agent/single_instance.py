from __future__ import annotations

import ctypes
import os
from types import TracebackType
from typing import Self


class AlreadyRunning(RuntimeError):
    pass


class SingleInstance:
    """Current-user named mutex used by the packaged and development Agent."""

    ERROR_ALREADY_EXISTS = 183

    def __init__(self, name: str = "Local\\FlynotesLocalAgent") -> None:
        self.name = name
        self._handle: int | None = None

    def __enter__(self) -> Self:
        if os.name != "nt":
            return self
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, self.name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "无法创建 Local Agent 单实例锁")
        self._handle = int(handle)
        if ctypes.get_last_error() == self.ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            self._handle = None
            raise AlreadyRunning("Flynotes Local Agent 已经在运行")
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if self._handle and os.name == "nt":
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(self._handle)
            self._handle = None
