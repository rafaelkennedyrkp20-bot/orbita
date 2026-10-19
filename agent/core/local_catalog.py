"""Catálogo local e estimativas conservadoras; não baixa nem inicia modelos."""

from copy import deepcopy
import json
import math
from pathlib import Path


def load_catalog() -> list[dict]:
    """Lê a cópia versionada; nenhuma consulta externa durante a recomendação."""
    return json.loads(Path(__file__).with_name("local_models.json").read_text(encoding="utf-8"))


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value) and value >= 0:
            return float(value)
    return None


def model_recommendations(hardware: dict, catalog=None) -> list[dict]:
    """Classifica capacidade de memória, não qualidade nem velocidade.

    Campos de memória usam GiB, incluindo as estimativas do catálogo; download_gb
    é o tamanho decimal publicado. Contexto total inclui entrada e saída, com KV
    estimado linearmente e auxiliares contados à parte. Não soma GPUs ou RAM à
    VRAM; offload parcial não é garantido. RAM reserva 2 GiB para o sistema.
    """
    recommendations = []
    for item in load_catalog() if catalog is None else catalog:
        result = deepcopy(item)
        result.update(fit="unknown", rationale="Metadados insuficientes para estimar o uso.",
                      estimated_memory_gb=None, execution_mode="unknown")
        recommendations.append(result)
        fields = ("download_gb", "weights_memory_gb", "runtime_overhead_gb",
                  "auxiliary_memory_gb", "kv_cache_gb_per_1k_tokens",
                  "context_tokens", "max_context_tokens")
        numbers = [_number(item.get(field)) for field in fields]
        if any(value is None for value in numbers):
            continue
        download, weights, overhead, auxiliary, cache, context, maximum = numbers
        if min(download, weights, context, maximum) <= 0:
            continue
        estimate = weights + overhead + auxiliary + cache * context / 1024
        result["estimated_memory_gb"] = round(estimate, 2)
        if context > maximum:
            result.update(fit="not_recommended", rationale="Contexto solicitado excede o limite documentado.")
            continue
        disk = _number(hardware.get("disk_free_gb"))
        # Margem de instalação, sem presumir que blobs já estão no cache.
        disk_needed = download * 10**9 / 1024**3 * 1.2 + 1
        if disk is not None and disk < disk_needed:
            result.update(fit="not_recommended", rationale="Espaço livre insuficiente no disco consultado.")
            continue
        ram = _number(hardware.get("ram_available_gb"))
        if ram is None or disk is None:
            result["rationale"] = "Sensor de RAM ou disco indisponível; uso manual continua permitido."
            continue
        gpu_free = max((_number(gpu.get("free_gb")) or 0
                        for gpu in (hardware.get("gpus") or []) if isinstance(gpu, dict)), default=0)
        # Mesmo com offload completo há consumo de RAM para carregar os pesos.
        host_needed = weights + overhead + auxiliary
        use_gpu = gpu_free >= estimate and ram >= host_needed + 2
        available = gpu_free if use_gpu else max(0, ram - 2)
        mode = "gpu" if use_gpu else "cpu"
        result["execution_mode"] = mode
        if available < estimate:
            result.update(fit="not_recommended", rationale="RAM disponível insuficiente; GPU não comporta offload completo na estimativa.")
        else:
            comfortable = available >= estimate * 1.25
            result["fit"] = "comfortable" if comfortable else "tight"
            location = "GPU" if use_gpu else "CPU; a resposta pode ser lenta"
            result["rationale"] = (
                f"Cabe em {location}, com {'folga' if comfortable else 'pouca folga'}; "
                f"estimativa de {estimate:.1f} GiB para {int(context)} tokens, "
                "incluindo KV e auxiliares. Não é medição nem garantia de desempenho."
            )
    return recommendations
