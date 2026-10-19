"""Recomendação local: estimativas, sensores opcionais e limites de memória."""

from copy import deepcopy
from types import SimpleNamespace
import subprocess

import pytest

from agent.actions import gpu_monitor
from agent.core.local_catalog import load_catalog, model_recommendations


def hardware(ram=16, disk=100, gpus=None):
    return {"ram_total_gb": ram, "ram_available_gb": ram, "disk_free_gb": disk,
            "gpus": gpus or []}


def model(**overrides):
    item = {"id": "test:4b", "download_gb": 3, "weights_memory_gb": 3,
            "runtime_overhead_gb": 1, "auxiliary_memory_gb": 0,
            "kv_cache_gb_per_1k_tokens": 0.25, "context_tokens": 4096,
            "max_context_tokens": 32768}
    return item | overrides


def recommend(hw=None, **overrides):
    return model_recommendations(hw or hardware(), [model(**overrides)])[0]


def test_cpu_remains_usable_and_does_not_claim_gpu_speed():
    result = recommend()
    assert result["fit"] == "comfortable"
    assert result["execution_mode"] == "cpu"
    assert "CPU" in result["rationale"] and "estimativa" in result["rationale"]
    assert result["estimated_memory_gb"] > result["download_gb"]


def test_unknown_gpu_falls_back_to_available_ram():
    result = recommend(hardware(gpus=[{"name": "AMD", "total_gb": None, "free_gb": None}]))
    assert result["fit"] == "comfortable"
    assert result["execution_mode"] == "cpu"


def test_insufficient_ram_and_tight_memory_are_distinct():
    assert recommend(hardware(ram=2))["fit"] == "not_recommended"
    assert recommend(hardware(ram=7))["fit"] == "tight"


def test_gpu_uses_free_memory_not_total_or_sum_of_cards():
    result = recommend(hardware(gpus=[{"name": "A", "total_gb": 24, "free_gb": 2},
                                      {"name": "B", "total_gb": 24, "free_gb": 3}]))
    assert result["execution_mode"] == "cpu"
    result = recommend(hardware(gpus=[{"name": "A", "total_gb": 24, "free_gb": 10}]))
    assert result["execution_mode"] == "gpu"


def test_context_and_vision_auxiliaries_increase_estimate():
    base = recommend(hardware(ram=9))
    long_context = recommend(hardware(ram=9), context_tokens=32768)
    vision = recommend(hardware(ram=9), auxiliary_memory_gb=4)
    assert base["fit"] == "comfortable"
    assert long_context["fit"] == vision["fit"] == "not_recommended"
    assert long_context["estimated_memory_gb"] > base["estimated_memory_gb"]


def test_missing_metadata_or_sensors_never_get_positive_badge():
    assert model_recommendations(hardware(), [{"id": "unknown"}])[0]["fit"] == "unknown"
    assert recommend(hardware(ram=None))["fit"] == "unknown"
    assert recommend(hardware(disk=None))["fit"] == "unknown"
    assert recommend(hardware(disk=1))["fit"] == "not_recommended"


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "8", True])
def test_invalid_memory_is_unknown(value):
    assert recommend(hardware(ram=value))["fit"] == "unknown"


def test_context_outside_supported_range_is_not_recommended():
    assert recommend(context_tokens=100000)["fit"] == "not_recommended"


def test_input_catalog_is_not_mutated_and_empty_is_respected():
    catalog = [model()]
    before = deepcopy(catalog)
    model_recommendations(hardware(), catalog)
    assert catalog == before
    assert model_recommendations(hardware(), []) == []


def test_catalog_has_provenance_license_and_honest_validation_status():
    catalog = load_catalog()
    assert 2 <= len(catalog) <= 6
    assert any("vision" in item["capabilities"] for item in catalog)
    assert any("tools" in item["capabilities"] for item in catalog)
    for item in catalog:
        assert item["source_url"].startswith("https://ollama.com/library/")
        assert item["license_url"].startswith("https://")
        assert item["license"] and item["source_revision"] and item["sources_checked_on"]
        assert item["pt_br_validation"] == "not_tested"
        assert item["quantization"] and item["download_gb"] > 0
        assert recommend(**{key: item[key] for key in model() if key in item})["fit"] != "unknown"


def test_hardware_collects_ram_disk_and_each_nvidia_gpu(monkeypatch, tmp_path):
    monkeypatch.setattr(gpu_monitor.psutil, "virtual_memory",
                        lambda: SimpleNamespace(total=16 * 1024**3, available=8 * 1024**3))
    monkeypatch.setattr(gpu_monitor.shutil, "disk_usage",
                        lambda path: SimpleNamespace(free=100 * 1024**3))
    def run(command, **kwargs):
        assert kwargs["timeout"] <= 2
        return SimpleNamespace(stdout="RTX A, 12288, 8192\nRTX B, 8192, N/A\n")
    monkeypatch.setattr(gpu_monitor.subprocess, "run", run)
    result = gpu_monitor.get_hardware_info(tmp_path)
    assert result["ram_total_gb"] == 16 and result["ram_available_gb"] == 8
    assert result["disk_free_gb"] == 100
    assert result["gpus"] == [{"name": "RTX A", "total_gb": 12, "free_gb": 8},
                               {"name": "RTX B", "total_gb": 8, "free_gb": None}]


def test_unavailable_sensors_are_reported_without_blocking(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("sensor indisponível")
    monkeypatch.setattr(gpu_monitor.psutil, "virtual_memory", unavailable)
    monkeypatch.setattr(gpu_monitor.shutil, "disk_usage", unavailable)
    monkeypatch.setattr(gpu_monitor.subprocess, "run", unavailable)
    result = gpu_monitor.get_hardware_info()
    assert result == {"ram_total_gb": None, "ram_available_gb": None,
                      "disk_free_gb": None, "gpus": []}


def test_nvidia_timeout_does_not_block_cpu_detection(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 2)
    monkeypatch.setattr(gpu_monitor.subprocess, "run", timeout)
    assert gpu_monitor.get_hardware_info()["gpus"] == []


def test_sensor_junk_does_not_discard_valid_gpu_rows(monkeypatch):
    monkeypatch.setattr(gpu_monitor.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(stdout="not a csv row\nGPU, nan, -2\nGPU2, 8192, 4096\n"))
    result = gpu_monitor.get_hardware_info()
    assert result["gpus"] == [{"name": "GPU", "total_gb": None, "free_gb": None},
                              {"name": "GPU2", "total_gb": 8, "free_gb": 4}]
