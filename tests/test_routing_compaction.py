"""Roteamento por especialidade e compactação inteligente do histórico."""

import pytest

import agent.core.agent_loop as loop
import agent.core.routing as routing
from agent.core.agent_loop import SUMMARY_PROMPT, AgentSession
from agent.core.providers import ChatResult, ProviderError
from test_agent_loop import ScriptedProvider, call  # noqa: F401  (reuso dos utilitários)


class StubSettings:
    """Configurações controladas: o ambiente real (chaves, conta Grok) não interfere."""

    def __init__(self, providers, credentials, **values):
        self._providers, self._credentials, self._values = providers, credentials, values

    def providers(self):
        return self._providers

    def has_credentials(self, name):
        return name in self._credentials

    def get(self, key, default=None):
        return self._values.get(key, default)


PROVIDERS = {
    "ollama": {"models": []},
    "deepseek": {"models": ["deepseek-chat"]},
    "anthropic": {"models": ["claude-opus-5-5"]},
    "openai": {"models": ["gpt-5"]},
}


@pytest.fixture(autouse=True)
def isolated_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(routing, "CATALOG_FILE", tmp_path / "model_catalog.json")


def test_catalog_first_match_wins():
    catalog = routing.load_catalog()
    assert routing.entry_for("ollama:qwen3.8-27b", catalog)["codigo"] == 2
    assert routing.entry_for("ollama:qwen2.5:14b", catalog)["codigo"] == 1
    assert routing.entry_for("deepseek:deepseek-reasoner", catalog)["raciocinio"] == 3


def test_economy_mode_changes_choice():
    creds = {"deepseek", "anthropic"}
    local = ["qwen2.5:14b"]
    maximo = StubSettings(PROVIDERS, creds, economy_mode="maximo")
    livre = StubSettings(PROVIDERS, {"anthropic"}, economy_mode="livre")
    assert routing.best("codigo", maximo, None, local) == "deepseek:deepseek-chat"
    assert routing.best("codigo", livre, None, local) == "anthropic:claude-opus-5-5"
    only_local = StubSettings(PROVIDERS, set(), economy_mode="maximo")
    assert routing.best("codigo", only_local, None, local) == "ollama:qwen2.5:14b"


def test_models_without_credentials_are_ignored():
    settings = StubSettings(PROVIDERS, {"deepseek"}, economy_mode="livre")
    refs = routing.candidate_refs(settings, None, routing.load_catalog(), [])
    assert "deepseek:deepseek-chat" in refs and not any(r.startswith("anthropic") for r in refs)


def test_image_specialty_uses_image_models_only():
    settings = StubSettings(PROVIDERS, {"openai", "deepseek"}, economy_mode="equilibrado")
    assert routing.best("imagem", settings, None, []) == "openai:gpt-image-1"
    # e modelos de imagem nunca são escolhidos para conversar
    assert routing.best("codigo", settings, None, []) != "openai:gpt-image-1"


def test_specialty_from_profile(brain):
    assert routing.specialty_for(brain.profiles.get("revisor")) == "revisao"
    assert routing.specialty_for(brain.profiles.get("geral")) == "geral"
    assert routing.specialty_for(brain.profiles.get("geral"), "pesquisa") == "pesquisa"


def test_table_text_lists_strengths_and_cost():
    settings = StubSettings(PROVIDERS, {"deepseek"}, economy_mode="equilibrado")
    table = routing.table_text(settings, None, ["qwen3.8-27b"])
    assert "ollama:qwen3.8-27b (local/grátis)" in table and "deepseek:deepseek-chat ($)" in table


def install(monkeypatch, script):
    fake = ScriptedProvider(script)
    monkeypatch.setattr(loop, "get_provider", lambda name, settings: fake)
    return fake


def test_delegate_uses_parent_model_by_default(brain, monkeypatch):
    brain.route_model = lambda specialty: "ollama:modelo-local-barato"   # roteador quer ir para o local
    fake = install(monkeypatch, [
        ChatResult(tool_calls=[call("delegate_task", tasks=[{"task": "parte A"}, {"task": "parte B"}])]),
        ChatResult(text="feito"), ChatResult(text="feito"),
        ChatResult(text="integrado"),
    ])
    session = AgentSession(brain, brain.profiles.get("geral"), "river", "deepseek-v4", approve=lambda r: "yes")
    assert session.run("faça em paralelo") == "integrado"
    assert {c["model"] for c in fake.calls} == {"deepseek-v4"}   # cópias do principal, nada de modelo local
    assert "SEU mesmo modelo (river:deepseek-v4)" in session.system_prompt([])


def test_delegate_uses_routed_model_when_team_is_automatic(brain, monkeypatch):
    brain.settings.set("team_model", "auto", save=False)
    brain.route_model = lambda specialty: {"codigo": "deepseek:deepseek-chat"}.get(specialty)
    fake = install(monkeypatch, [
        ChatResult(tool_calls=[call("delegate_task", tasks=[{"task": "implemente X", "profile": "programador"}])]),
        ChatResult(text="feito pelo subagente"),
        ChatResult(text="integrado"),
    ])
    session = AgentSession(brain, brain.profiles.get("geral"), "ollama", "local", approve=lambda r: "yes")
    assert session.run("faça X") == "integrado"
    assert fake.calls[1]["model"] == "deepseek-chat"


def big_session(brain):
    brain.settings.set("economy_mode", "maximo", save=False)
    session = AgentSession(brain, brain.profiles.get("geral"), "fake", "m1", approve=lambda r: "yes")
    for i in range(10):
        session.messages.append({"role": "user", "content": f"pedido {i} " + "x" * 8000})
        session.messages.append({"role": "assistant", "content": f"resposta {i}"})
    return session


def test_compaction_summarizes_old_turns(brain, monkeypatch):
    fake = install(monkeypatch, [ChatResult(text="RESUMO: usuário quer o relatório X"), ChatResult(text="ok")])
    session = big_session(brain)
    assert session.run("novo pedido") == "ok"
    assert session.summary.startswith("RESUMO")
    assert fake.calls[0]["messages"][0]["content"] == SUMMARY_PROMPT and fake.calls[0]["tools"] is None
    assert "Resumo da conversa anterior" in fake.calls[1]["messages"][0]["content"]
    users = [m for m in session.messages if m["role"] == "user"]
    assert [u["content"][:8] for u in users] == ["pedido 9", "novo ped"]


def test_manual_compaction_runs_below_the_limit_and_keeps_last_request(brain, monkeypatch):
    fake = install(monkeypatch, [ChatResult(text="## Objetivo\nsite hacker")])
    session = AgentSession(brain, brain.profiles.get("geral"), "fake", "m1", approve=lambda r: "yes")
    for i in range(3):   # conversa pequena: o automático (85%) não faria nada
        session.messages += [{"role": "user", "content": f"pedido {i}"}, {"role": "assistant", "content": f"ok {i}"}]
    assert session._maybe_compact([]) == 0 and not fake.calls
    assert session._maybe_compact([], force=True) == 4
    assert session.summary.startswith("## Objetivo")
    assert [m["content"] for m in session.messages] == ["pedido 2", "ok 2"]
    assert "## Próximos passos" in SUMMARY_PROMPT


def test_manual_compaction_needs_more_than_one_request(brain, monkeypatch):
    install(monkeypatch, [])
    session = AgentSession(brain, brain.profiles.get("geral"), "fake", "m1", approve=lambda r: "yes")
    session.messages = [{"role": "user", "content": "único"}, {"role": "assistant", "content": "ok"}]
    assert session._maybe_compact([], force=True) == 0 and session.messages[0]["content"] == "único"


def test_compaction_failure_falls_back_to_trimming(brain, monkeypatch):
    install(monkeypatch, [ProviderError("sem rede"), ChatResult(text="ok mesmo assim")])
    session = big_session(brain)
    assert session.run("novo pedido") == "ok mesmo assim"
    assert session.summary is None
