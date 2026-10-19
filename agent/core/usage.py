"""
usage.py — Medidor de consumo de tokens e políticas de economia.

Modos de economia (escolhidos na interface):
    maximo       contexto enxuto, saídas de ferramentas curtas, subagentes no modelo econômico
    equilibrado  padrão: contexto até 1M nos modelos que aceitam, corta o que é velho/repetido
    livre        contexto até 1M e saídas de ferramentas maiores; só o orçamento do usuário freia

O "freio": se uma tarefa passar do orçamento por tarefa (ou o dia passar do orçamento
diário), o agente PAUSA e pergunta se deve continuar — nunca gasta tudo de uma vez.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import date

from agent.core.config import DATA_DIR

USAGE_FILE = DATA_DIR / "usage.json"


@dataclass(frozen=True)
class EconomyPolicy:
    context_tokens: int          # teto de contexto por chamada (o limite real é o menor entre este e o do modelo)
    tool_output_chars: int       # tamanho máximo de cada resultado de ferramenta
    old_tool_output_chars: int   # resultados antigos (turnos anteriores) são encurtados
    max_steps: int
    skills_index_chars: int

    @staticmethod
    def for_mode(mode: str) -> "EconomyPolicy":
        return ECONOMY_POLICIES.get(mode, ECONOMY_POLICIES["equilibrado"])


ECONOMY_POLICIES = {
    "maximo": EconomyPolicy(24_000, 8_000, 600, 15, 2_500),
    "equilibrado": EconomyPolicy(1_000_000, 20_000, 1_500, 30, 6_000),
    "livre": EconomyPolicy(1_000_000, 40_000, 6_000, 60, 12_000),
}

ECONOMY_LABELS = {
    "maximo": "Economia máxima",
    "equilibrado": "Equilibrado",
    "livre": "Livre (mais contexto)",
}


def estimate_tokens(text: str) -> int:
    """Estimativa rápida e independente de provedor (~3,5 caracteres por token)."""
    return int(len(text) / 3.5) + 1


class UsageTracker:
    """Acumula tokens por dia e por provedor:modelo em `data/usage.json`."""

    def __init__(self, path=USAGE_FILE):
        self.path = path
        self._lock = threading.Lock()
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def record(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
        today = date.today().isoformat()
        with self._lock:
            day = self._data.setdefault(today, {})
            entry = day.setdefault(f"{provider}:{model}", {"input": 0, "output": 0, "calls": 0})
            entry["input"] += int(input_tokens or 0)
            entry["output"] += int(output_tokens or 0)
            entry["calls"] += 1
            # Mantém só 90 dias de histórico
            for old in sorted(self._data)[:-90]:
                del self._data[old]
            tmp = self.path.with_suffix(".tmp")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)

    def today(self) -> dict:
        with self._lock:
            return dict(self._data.get(date.today().isoformat(), {}))

    def today_total(self, include_local: bool = False) -> int:
        total = 0
        for key, entry in self.today().items():
            if not include_local and key.startswith("ollama:"):
                continue  # modelos locais não custam dinheiro
            total += entry["input"] + entry["output"]
        return total
