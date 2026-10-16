"""Leitura leve das métricas NVIDIA para a interface local."""

from __future__ import annotations

import subprocess
from typing import Optional


def get_nvidia_metrics() -> Optional[dict]:
    """Retorna métricas da primeira GPU NVIDIA ou ``None`` se indisponível."""
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=2, check=True)
        line = next((item.strip() for item in result.stdout.splitlines() if item.strip()), "")
        values = [item.strip() for item in line.split(",")]
        if len(values) != 5:
            return None
        name, used, total, temperature, utilization = values
        return {
            "name": name,
            "memory_used_mb": int(float(used)),
            "memory_total_mb": int(float(total)),
            "temperature_c": int(float(temperature)) if temperature != "N/A" else None,
            "utilization_percent": int(float(utilization)) if utilization != "N/A" else None,
        }
    except (FileNotFoundError, subprocess.SubprocessError, ValueError):
        return None
