"""Leitura de RAM/disco e métricas NVIDIA para a interface local."""

from __future__ import annotations

import subprocess
import math
from pathlib import Path
import shutil
from typing import Optional

import psutil


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


def get_hardware_info(disk_path=None) -> dict:
    """Mede RAM/disco em GiB e GPUs NVIDIA disponíveis; chamar fora da UI.

    Sensores ausentes ficam nulos. ``gpus=[]`` significa não detectado, e não
    comprova ausência de AMD/Intel. O disco é o do destino informado (ou cwd).
    """
    info = {"ram_total_gb": None, "ram_available_gb": None,
            "disk_free_gb": None, "gpus": []}
    try:
        memory = psutil.virtual_memory()
        info.update(ram_total_gb=round(memory.total / 1024**3, 2),
                    ram_available_gb=round(memory.available / 1024**3, 2))
    except (OSError, AttributeError, NotImplementedError):
        pass  # A interface recebe explicitamente os sensores nulos.
    try:
        info["disk_free_gb"] = round(shutil.disk_usage(disk_path or Path.cwd()).free / 1024**3, 2)
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2, check=True,
        )
        for line in result.stdout.splitlines():
            values = [part.strip() for part in line.split(",")]
            if len(values) != 3 or not values[0]:
                continue
            gpu = {"name": values[0], "total_gb": None, "free_gb": None}
            for key, value in zip(("total_gb", "free_gb"), values[1:]):
                try:
                    number = float(value)
                    if math.isfinite(number) and number >= 0:
                        gpu[key] = round(number / 1024, 2)
                except ValueError:
                    pass
            info["gpus"].append(gpu)
    except (OSError, subprocess.SubprocessError):
        pass
    return info
