"""Compara modelos com os mesmos casos. Não escolhe sozinho o modelo do dia a dia.

Uso:
  venv\\Scripts\\python.exe scripts\\avaliar_modelos.py
  venv\\Scripts\\python.exe scripts\\avaliar_modelos.py ollama:qwen3:4b
O primeiro nome antes dos dois-pontos é o provedor. O resto é o modelo.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.core.model_eval import CASES, rank, run_comparison  # noqa: E402


def _hardware_label() -> str:
    from agent.actions.gpu_monitor import get_hardware_info

    info = get_hardware_info()
    gpus = info.get("gpus") or []
    gpu = gpus[0].get("name") if gpus else "gpu não detectada"
    return f"ram_gb={info.get('ram_total_gb')} gpu={gpu}"


def _ask(provider_name: str, model: str):
    from agent.core.providers import get_provider
    from agent.core.settings import Settings

    provider = get_provider(provider_name, Settings())

    def ask(prompt: str) -> dict:
        started = time.perf_counter()
        result = provider.chat(
            model, [{"role": "user", "content": prompt}], max_tokens=180, temperature=0,
        )
        usage = result.usage if isinstance(result.usage, dict) else {}
        return {
            "text": result.text or "",
            "usage": usage,
            "seconds": round(time.perf_counter() - started, 3),
        }

    return ask


def main() -> None:
    if len(sys.argv) < 2:
        for case in CASES:
            print(f"{case['id']}: {case['prompt']}")
        print("Passe provedor:modelo para uma rodada real. Cancelamento e erro não vencem por velocidade.")
        return
    spec = sys.argv[1].strip()
    if ":" not in spec or spec.startswith(":") or spec.endswith(":"):
        print("Use provedor:modelo. Exemplo: ollama:qwen3:4b")
        return
    provider_name, model = spec.split(":", 1)
    try:
        rows = run_comparison(spec, _ask(provider_name, model), hardware=_hardware_label())
    except Exception as error:
        print(f"Não consegui falar com {spec}: {error}")
        return
    print(f"Hardware: {rows[0]['hardware']}. Quantização e contexto não vêm neste roteiro.")
    for row in rows:
        state = "ok" if row["ok"] else (row.get("reason") or "errado")
        print(f"{row['id']}: {state} em {row.get('seconds')} s, tokens={row.get('output_tokens')}")
    winners = rank(rows)
    if not winners:
        print("Nenhum caso entrou no ranking.")
        return
    print("Ranking (só acertos): " + ", ".join(row["id"] for row in winners))


if __name__ == "__main__":
    main()
