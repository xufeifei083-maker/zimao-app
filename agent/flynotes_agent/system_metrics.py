from __future__ import annotations

import csv
import io
import subprocess
from datetime import datetime, timezone
from typing import Any

import psutil


def _gpu_stats() -> list[dict[str, Any]]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if completed.returncode != 0:
        return []

    result: list[dict[str, Any]] = []
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) < 6:
            continue
        try:
            result.append(
                {
                    "index": int(row[0].strip()),
                    "name": row[1].strip(),
                    "utilizationPercent": float(row[2].strip()),
                    "memoryUsedBytes": int(float(row[3].strip()) * 1024 * 1024),
                    "memoryTotalBytes": int(float(row[4].strip()) * 1024 * 1024),
                    "temperatureC": float(row[5].strip()),
                }
            )
        except (TypeError, ValueError):
            continue
    return result


def read_system_metrics() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    return {
        "cpuPercent": psutil.cpu_percent(interval=None),
        "memoryUsedBytes": memory.used,
        "memoryTotalBytes": memory.total,
        "memoryPercent": memory.percent,
        "gpus": _gpu_stats(),
        "updatedAt": datetime.now(timezone.utc),
    }
