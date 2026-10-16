"""
medir_velocidade.py — Mede o desempenho do motor do Órbita (inicialização, TTFT e custo por turno).

Mede:
  a) Inicialização do motor: import de agent.core.brain + criação de Brain() (sem abrir a janela)
  b) Tempo até o primeiro token (TTFT) de uma resposta (Ollama local se ativo, + provider falso determinístico)
  c) Custo de montar o prompt e o histórico a cada turno: system_prompt, routing, conversations e memória
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _ollama_running() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.0):
            return True
    except Exception:
        return False


def measure_once() -> dict[str, float]:
    results: dict[str, float] = {}

    # a) Inicialização do motor (import + Brain)
    t0 = time.perf_counter()
    import agent.core.brain as brain_mod
    t_import = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    brain = brain_mod.Brain(start_mcp=True)
    t_brain = (time.perf_counter() - t1) * 1000.0

    results["a1_import_brain_ms"] = t_import
    results["a2_create_brain_ms"] = t_brain
    results["a_init_total_ms"] = t_import + t_brain

    from agent.core.conversations import ConversationStore, to_ui_blocks
    from agent.core.providers import ChatResult, Provider
    from agent.core import providers as providers_mod

    # b) Tempo até o primeiro token (TTFT)
    # Mede o caminho real de AgentSession.run até o primeiro chunk de texto emitido.
    class _FastProvider(Provider):
        def chat(self, model, messages, tools=None, *, on_text=None, **extra):
            if on_text:
                on_text("ok")
            return ChatResult(text="ok", stop_reason="stop", usage={"input_tokens": 10, "output_tokens": 1})

    # Limpa cache de modelos locais para medir o custo real do primeiro turno da sessão
    brain._local_models = None
    first_token_at: list[float] = []

    def on_event(kind: str, data: dict) -> None:
        if kind == "text" and not first_token_at:
            first_token_at.append(time.perf_counter())

    session = brain.new_session(events=on_event)
    orig_get_provider = providers_mod.get_provider
    fake_provider = _FastProvider("fake", {}, brain.settings)

    def _patched_get_provider(name: str, settings):
        if name == session.provider_name:
            return fake_provider
        return orig_get_provider(name, settings)

    providers_mod.get_provider = _patched_get_provider
    brain_mod.get_provider = _patched_get_provider
    from agent.core import agent_loop as loop_mod
    loop_mod.get_provider = _patched_get_provider
    try:
        t_start = time.perf_counter()
        session.run("Responda apenas: ok")
        t_end = time.perf_counter()
        results["b_ttft_ms"] = ((first_token_at[0] if first_token_at else t_end) - t_start) * 1000.0
    finally:
        providers_mod.get_provider = orig_get_provider
        brain_mod.get_provider = orig_get_provider
        loop_mod.get_provider = orig_get_provider

    # Se Ollama estiver rodando com modelo instalado, registra também o TTFT com Ollama real
    if _ollama_running():
        models = brain.local_models()
        if models:
            first_ollama: list[float] = []

            def on_ollama_event(kind: str, data: dict) -> None:
                if kind in ("text", "reasoning") and not first_ollama:
                    first_ollama.append(time.perf_counter())
                    ollama_session.cancel.set()

            ollama_session = brain_mod.AgentSession(
                brain, brain.profile, "ollama", models[0], events=on_ollama_event
            )
            t_o = time.perf_counter()
            try:
                ollama_session.run("Responda apenas: ok")
                results["b_ollama_ttft_ms"] = ((first_ollama[0] if first_ollama else time.perf_counter()) - t_o) * 1000.0
            except Exception:
                pass

    # c) Custo de montar o prompt e o histórico a cada turno (média por turno em 20 iterações)
    iters = 20
    tools = session.visible_tools()

    # c1: system_prompt (inclui equipe, roteamento, skills, MCP, memória e instruções do projeto)
    t0 = time.perf_counter()
    for _ in range(iters):
        session.system_prompt(tools)
    results["c1_system_prompt_ms"] = ((time.perf_counter() - t0) * 1000.0) / iters

    # c2: routing (best para as especialidades da equipe + table_text)
    local_models = brain.local_models()
    t0 = time.perf_counter()
    for _ in range(iters):
        for spec in ("codigo", "revisao", "pesquisa", "raciocinio", "visao", "geral"):
            brain_mod.routing.best(spec, brain.settings, brain.current_model, local_models)
        brain_mod.routing.table_text(brain.settings, brain.current_model, local_models)
    results["c2_routing_ms"] = ((time.perf_counter() - t0) * 1000.0) / iters

    # c3: conversations (save + load + list + to_ui_blocks em pasta temporária com 25 conversas)
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(Path(tmp))
        sample_msgs = []
        for i in range(12):
            sample_msgs.append({"role": "user", "content": f"Pedido de teste {i} " * 8})
            sample_msgs.append({
                "role": "assistant",
                "content": f"Explicação detalhada {i} " * 12,
                "tool_calls": [{"id": f"call_{i}", "name": "read_file", "arguments": {"path": "a.py"}}],
            })
            sample_msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "name": "read_file", "content": "x = 1\n" * 20})
        for idx in range(25):
            cid = f"{idx:012x}"
            store.save({
                "id": cid, "title": f"Conversa {idx}", "pinned_title": False,
                "created": "2026-10-16T00:00:00", "profile": "geral",
                "provider": "ollama", "model": "qwen3:14b", "messages": sample_msgs,
            })
        target_id = f"{12:012x}"
        t0 = time.perf_counter()
        for _ in range(iters):
            existing = store.load(target_id) or {}
            store.save({**existing, "id": target_id, "messages": sample_msgs})
            store.list(limit=50)
            to_ui_blocks(sample_msgs)
        results["c3_conversations_ms"] = ((time.perf_counter() - t0) * 1000.0) / iters

    # c4: memória (facts + search_facts + get_relevant_context)
    t0 = time.perf_counter()
    for _ in range(iters):
        brain.memory.facts(30)
        brain.memory.search_facts("python windows agente")
        brain.memory.get_relevant_context("como configurar o projeto python no windows")
    results["c4_memory_ms"] = ((time.perf_counter() - t0) * 1000.0) / iters

    results["c_turn_overhead_ms"] = (
        results["c1_system_prompt_ms"]
        + results["c2_routing_ms"]
        + results["c3_conversations_ms"]
        + results["c4_memory_ms"]
    )

    brain.shutdown()
    return results


def _print_table(metrics: dict[str, float], title: str = "Medicao de Velocidade") -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = [
        ("a) Inicialização total (import + Brain)", metrics["a_init_total_ms"]),
        ("   |- a.1) import agent.core.brain", metrics["a1_import_brain_ms"]),
        ("   +- a.2) Brain() init", metrics["a2_create_brain_ms"]),
        ("b) Tempo até 1º token — motor (TTFT)", metrics["b_ttft_ms"]),
    ]
    if "b_ollama_ttft_ms" in metrics:
        rows.append(("   +- b.ollama) TTFT com Ollama local", metrics["b_ollama_ttft_ms"]))
    rows.extend([
        ("c) Custo por turno (prompt + histórico)", metrics["c_turn_overhead_ms"]),
        ("   |- c.1) system_prompt()", metrics["c1_system_prompt_ms"]),
        ("   |- c.2) routing (equipe + tabela)", metrics["c2_routing_ms"]),
        ("   |- c.3) conversations (save+list+ui)", metrics["c3_conversations_ms"]),
        ("   +- c.4) memória (facts+search+ctx)", metrics["c4_memory_ms"]),
    ])
    print(f"\n=== {title} ===")
    print(f"{'Métrica':<44} | {'Tempo (ms)':>12}")
    print("-" * 59)
    for label, val in rows:
        print(f"{label:<44} | {val:>10.2f} ms")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mede a velocidade do Órbita")
    parser.add_argument("--json", action="store_true", help="Imprime apenas JSON com os resultados de uma execução")
    parser.add_argument("--runs", type=int, default=1, help="Número de processos independentes para calcular a mediana")
    args = parser.parse_args()

    if args.json:
        import json
        print(json.dumps(measure_once()))
        return 0

    if args.runs <= 1:
        _print_table(measure_once())
        return 0

    import json
    all_runs: list[dict[str, float]] = []
    for i in range(args.runs):
        out = subprocess.check_output(
            [sys.executable, str(Path(__file__).resolve()), "--json"],
            cwd=str(PROJECT_ROOT),
            text=True,
        )
        line = [ln for ln in out.strip().splitlines() if ln.strip().startswith("{")][-1]
        run_data = json.loads(line)
        all_runs.append(run_data)
        print(f"Execução {i + 1}/{args.runs}: init={run_data['a_init_total_ms']:.2f}ms | "
              f"ttft={run_data['b_ttft_ms']:.2f}ms | turno={run_data['c_turn_overhead_ms']:.2f}ms")

    medians = {k: statistics.median(r[k] for r in all_runs if k in r) for k in all_runs[0]}
    _print_table(medians, title=f"Mediana de {args.runs} execuções")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
