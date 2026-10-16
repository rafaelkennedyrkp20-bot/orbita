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
    assert "delegate_task" in cap.prompt_section("frontier")
    assert "delegate_task" not in cap.prompt_section("frontier", depth=1)   # subagente não delega
    assert "Modo foco" in cap.prompt_section("compact") and cap.prompt_section("standard") == ""
