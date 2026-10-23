"""Contrato Moonshot/Kimi com transporte simulado, sem conta ou chamada paga."""

import copy
import json
from dataclasses import replace

import httpx
import pytest

from agent.core import capabilities, providers
from agent.core.agent_loop import AgentSession, _mask_old_observations
from agent.core.providers import OpenAICompatProvider, ProviderError
from agent.core.settings import DEFAULT_PROVIDERS, Settings


def test_moonshot_preset_keeps_user_provider_overrides(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"providers": {
        "moonshot": {"base_url": "https://custom.example/v1", "models": ["my-model"]},
        "existing": {"type": "openai", "base_url": "http://127.0.0.1:9000"},
    }}), encoding="utf-8")
    settings = Settings(path)
    preset = DEFAULT_PROVIDERS["moonshot"]
    assert preset["base_url"] == "https://api.moonshot.ai/v1"
    assert preset["api_key_env"] == "MOONSHOT_API_KEY"
    assert preset["models"] == ["kimi-k3.1-pro", "kimi-k3.1-pro-highspeed"]
    assert settings.provider("moonshot")["base_url"] == "https://custom.example/v1"
    assert settings.provider("moonshot")["models"] == ["my-model"]
    assert "existing" in settings.providers() and "deepseek" in settings.providers()


@pytest.mark.parametrize("model", ["kimi-k3", "kimi-k3.1-pro", "kimi-k3.1-pro-highspeed",
                                  "moonshotai/kimi-k3.1-pro", "kimi-k2.7-code"])
def test_kimi_replays_reasoning_on_final_and_tool_messages(model):
    history = [
        {"role": "user", "content": "renderize"},
        {"role": "assistant", "content": "", "reasoning": "Vou consultar a cena.",
         "tool_calls": [{"id": "c1", "name": "list_dir", "arguments": {}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "cena.blend"},
        {"role": "assistant", "content": "Cena encontrada.", "reasoning": "Arquivo conferido."},
        {"role": "user", "content": "agora exporte"},
    ]
    before = copy.deepcopy(history)
    wire = OpenAICompatProvider("moonshot", {})._convert(model, history)
    assert wire[1]["reasoning_content"] == history[1]["reasoning"]
    assert wire[3]["reasoning_content"] == history[3]["reasoning"]
    assert wire[1]["tool_calls"][0]["id"] == "c1"
    assert history == before


def test_kimi_stream_preserves_tools_and_omits_fixed_parameters(monkeypatch):
    requests = []
    events = [
        {"choices": [{"delta": {"reasoning_content": "Conferir "}}]},
        {"choices": [{"delta": {"reasoning_content": "a cena.", "tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "list_dir", "arguments": "{}"}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]

    def respond(request):
        requests.append(json.loads(request.content))
        body = "".join("data: " + json.dumps(item) + "\n\n" for item in events) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    monkeypatch.setenv("MOONSHOT_API_KEY", "isolated-test-key")
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(providers, "_shared_http_client", lambda: client)
        provider = OpenAICompatProvider("moonshot", DEFAULT_PROVIDERS["moonshot"])
        result = provider.chat("kimi-k3.1-pro", [{"role": "user", "content": "liste"}],
                               [{"name": "list_dir", "description": "List", "parameters": {"type": "object"}}],
                               temperature=0.2, max_tokens=24000, effort="high")
    assert result.reasoning == "Conferir a cena."
    assert result.tool_calls == [{"id": "c1", "name": "list_dir", "arguments": {}}]
    assert requests[0]["max_completion_tokens"] == 24000
    assert requests[0]["reasoning_effort"] == "high"
    assert "temperature" not in requests[0] and "thinking" not in requests[0]
    assert requests[0]["tools"][0]["function"]["name"] == "list_dir"


def test_kimi_agent_session_replays_complete_assistants_across_two_turns(brain, tmp_path, monkeypatch):
    requests = []
    deltas = [
        {"reasoning_content": "Preciso listar a pasta.", "tool_calls": [
            {"index": 0, "id": "c1", "function": {"name": "list_dir", "arguments": '{"path": "."}'}}]},
        {"reasoning_content": "Pasta conferida.", "content": "Concluído."},
        {"reasoning_content": "Lembro da conferência.", "content": "Confirmado."},
    ]

    def respond(request):
        requests.append(json.loads(request.content))
        chunk = {"choices": [{"delta": deltas.pop(0)}]}
        return httpx.Response(200, text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")

    monkeypatch.setenv("MOONSHOT_API_KEY", "isolated-test-key")
    profile = replace(brain.profiles.get("geral"), workspace=str(tmp_path))
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(providers, "_shared_http_client", lambda: client)
        session = AgentSession(brain, profile, "moonshot", "kimi-k3.1-pro")
        assert session.run("liste a pasta do projeto") == "Concluído."
        assert session.run("confirme o resultado anterior") == "Confirmado."
    assistants = [m for m in requests[2]["messages"] if m["role"] == "assistant"]
    assert [m["reasoning_content"] for m in assistants] == ["Preciso listar a pasta.", "Pasta conferida."]
    assert assistants[0]["tool_calls"][0]["id"] == "c1"
    assert any(m.get("tool_call_id") == "c1" for m in requests[2]["messages"])


def test_kimi_rejects_unsupported_effort_before_network(monkeypatch):
    provider = OpenAICompatProvider("moonshot", DEFAULT_PROVIDERS["moonshot"])
    monkeypatch.setattr(providers, "_shared_http_client", lambda: pytest.fail("não deve chamar a rede"))
    with pytest.raises(ProviderError, match="low, high ou max"):
        provider.chat("kimi-k3.1-pro", [{"role": "user", "content": "oi"}], effort="medium")


@pytest.mark.parametrize("model,keep", [("kimi-k3", True), ("kimi-k3.1-pro", True), ("kimi-k2.7-code", True),
                                       ("deepseek-reasoner", False)])
def test_kimi_turn_history_retains_required_reasoning(brain, model, keep):
    session = AgentSession(brain, brain.profiles.get("geral"), "moonshot", model)
    session.messages = [
        {"role": "user", "content": "primeiro pedido"},
        {"role": "assistant", "content": "feito", "reasoning": "Raciocínio obrigatório."},
        {"role": "user", "content": "segundo pedido"},
    ]
    before = copy.deepcopy(session.messages)
    assistants = [m for m in session._wire_messages([]) if m["role"] == "assistant"]
    assert ("reasoning" in assistants[0]) == keep
    assert session.messages == before


def test_reasoning_is_included_in_context_size():
    plain = [{"role": "assistant", "content": "feito"}]
    thinking = [{**plain[0], "reasoning": "r" * 7000}]
    assert AgentSession._history_size(thinking) >= AgentSession._history_size(plain) + 2000


def test_kimi_keeps_returned_tool_arguments_when_masking_large_observations():
    history = [{"role": "user", "content": "crie os arquivos"}]
    for i in range(14):
        history.extend([
            {"role": "assistant", "reasoning": f"passo {i}", "content": "",
             "tool_calls": [{"id": f"c{i}", "name": "write_file",
                             "arguments": {"path": f"cena{i}.py", "content": "x" * 1000}}]},
            {"role": "tool", "tool_call_id": f"c{i}", "name": "write_file", "content": "y" * 3000},
        ])
    before = copy.deepcopy(history)
    _mask_old_observations(history, 0, preserve_assistants=True)
    assert history[1] == before[1]
    assert len(history[2]["content"]) < len(before[2]["content"])
    _mask_old_observations(before, 0)
    assert len(before[1]["tool_calls"][0]["arguments"]["content"]) < 1000


def test_kimi_does_not_send_reasoning_larger_than_context(brain, monkeypatch):
    session = AgentSession(brain, brain.profiles.get("geral"), "moonshot", "kimi-k3.1-pro")
    session.messages = [
        {"role": "user", "content": "gere"},
        {"role": "assistant", "content": "", "reasoning": "r" * 20000,
         "tool_calls": [{"id": "c1", "name": "list_dir", "arguments": {}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "pronto"},
    ]
    monkeypatch.setattr(session, "_history_budget", lambda *_args: 1000)
    with pytest.raises(ProviderError, match="compact"):
        session._wire_messages([])


@pytest.mark.parametrize("model", ["kimi-k3", "kimi-k3.1-pro", "kimi-k3.1-pro-highspeed"])
def test_kimi_uses_documented_context_and_frontier_tier(model):
    assert capabilities.context_window("moonshot", model) == 1_000_000
    assert capabilities.tier("moonshot", model) == "frontier"
