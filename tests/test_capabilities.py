"""Liberdade por modelo: modelos de ponta ganham autonomia, locais pequenos ganham foco."""

import pytest

from agent.core import capabilities as cap


@pytest.mark.parametrize("provider,model,expected", [
    ("anthropic", "claude-opus-5-5", "frontier"),
    ("anthropic", "claude-fable-5-1", "frontier"),
    ("openai", "gpt-5", "frontier"),
    ("openrouter", "anthropic/claude-sonnet-5-5", "frontier"),
    ("river", "deepseek-ai/DeepSeek-V4.1-Flash", "frontier"),
    ("xai", "grok-4-fast", "frontier"),
    ("grok", "grok-build", "frontier"),
    ("gemini", "gemini-2.5-pro", "frontier"),
    ("ollama", "qwen3:14b", "compact"),
    ("ollama", "huihui_ai/qwen2.5-abliterate:14b", "compact"),
    ("ollama", "llama3.2:3b", "compact"),
    ("openai", "gpt-4o-mini", "compact"),
    ("ollama", "hf.co/JonathanColetti/Qwen3.8-27B-Uncensored-GGUF:IQ4_XS", "standard"),
    ("together", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "standard"),
    ("mistral", "mistral-medium", "standard"),
])
def test_tiers(provider, model, expected):
    assert cap.tier(provider, model) == expected


def test_effects():
    assert cap.step_multiplier("frontier") == 2.0 and cap.step_multiplier("compact") == 1.0
    # A regra de quando delegar mora num lugar só (texto da equipe); a autonomia não empurra para a equipe.
    assert "delegate_task" not in cap.prompt_section("frontier")
    assert "Modo foco" in cap.prompt_section("compact") and cap.prompt_section("standard") == ""


@pytest.mark.parametrize("provider,model,window", [
    ("anthropic", "claude-opus-5-5", 1_000_000),
    ("anthropic", "claude-sonnet-4-6", 1_000_000),
    ("openrouter", "anthropic/claude-fable-5-1", 1_000_000),
    ("anthropic", "claude-haiku-4-5", 200_000),
    ("anthropic", "claude-sonnet-4-5", 200_000),
    ("anthropic", "claude-sonnet-4-20250514", 200_000),
    ("anthropic", "claude-opus-4-1-20250805", 200_000),
    ("openai", "gpt-4.1", 1_047_576),
    ("openai", "gpt-5.1", 400_000),
    ("google", "gemini-2.5-pro", 1_048_576),
    ("xai", "grok-4-fast", 2_000_000),
    ("deepseek", "deepseek-chat", 128_000),
    ("river", "modelo-desconhecido", 128_000),
])
def test_context_window_by_model(provider, model, window):
    assert cap.context_window(provider, model) == window


def test_history_budget_goes_up_to_one_million_only_where_supported(brain):
    from agent.core.agent_loop import AgentSession

    def budget(provider, model, mode="equilibrado"):
        brain.settings.set("economy_mode", mode, save=False)
        return AgentSession(brain, brain.profiles.get("geral"), provider, model)._history_budget([], "")

    assert 850_000 <= budget("anthropic", "claude-opus-5-5") <= 1_000_000   # 1M menos a reserva da resposta
    assert budget("openai", "gpt-4.1") <= 1_000_000                          # nunca passa de 1M
    assert 100_000 <= budget("deepseek", "deepseek-chat") < 128_000          # limite real do modelo
    assert budget("anthropic", "claude-opus-5-5", "maximo") <= 24_000        # economia máxima continua enxuta
    assert budget("ollama", "qwen3:8b") <= 16384                             # local: o num_ctx configurado


def test_task_budget_default_is_one_million_and_old_default_is_upgraded(tmp_path):
    import json

    from agent.core.settings import Settings

    assert Settings(tmp_path / "novo.json").get("turn_token_budget") == 1_000_000
    old = tmp_path / "antigo.json"
    old.write_text(json.dumps({"turn_token_budget": 400000}), encoding="utf-8")
    assert Settings(old).get("turn_token_budget") == 1_000_000     # o padrão antigo sobe
    mine = tmp_path / "escolhido.json"
    mine.write_text(json.dumps({"turn_token_budget": 250000}), encoding="utf-8")
    assert Settings(mine).get("turn_token_budget") == 250000       # escolha da pessoa fica
