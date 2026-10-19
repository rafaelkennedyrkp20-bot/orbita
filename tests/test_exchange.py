"""Pacote próprio de conversa e perfil: ida e volta, sem segredo e sem segunda cópia."""

import json

from agent.core.conversations import ConversationStore
from agent.core.exchange import (
    conversation_markdown, export_conversation, export_profile, import_conversation, import_profile,
)
from agent.core.profiles import Profile, ProfileManager


def _conversation():
    return {
        "id": "abc123abc123",
        "title": "Notas",
        "profile": "geral",
        "model": "ollama:qwen3:4b",
        "project": "E:/obra",
        "summary": "",
        "pinned_prompt": "",
        "pinned_title": True,
        "messages": [
            {"role": "user", "content": "qual é o prazo"},
            {"role": "assistant", "content": "sexta", "command": "rm -rf /"},
        ],
        "external_session": "segredo-de-sessao",
        "api_key": "sk-abcdefghijklmnopqrstuvwxyz",
    }


def test_roundtrip_drops_secrets_and_importing_twice_does_not_duplicate(tmp_path):
    store = ConversationStore(tmp_path / "conversations")
    package = export_conversation(_conversation())
    blob = json.dumps(package)
    assert "sk-" not in blob and "segredo-de-sessao" not in blob and "rm -rf" not in blob
    assert "qual é o prazo" in conversation_markdown(package)
    first = import_conversation(store, package)
    second = import_conversation(store, package)
    assert first == second
    saved = json.loads((tmp_path / "conversations" / f"{first}.json").read_text(encoding="utf-8"))
    assert [item["content"] for item in saved["messages"]] == ["qual é o prazo", "sexta"]
    assert "command" not in saved["messages"][1]
    assert saved.get("external_session") is None
    assert list(tmp_path.joinpath("conversations").glob("*.json")).__len__() == 1


def test_profile_export_strips_a_key_and_imports_once(tmp_path):
    manager = ProfileManager(tmp_path / "profiles")
    before = len(manager.list())
    profile = Profile(id="extra", name="Extra", system_prompt="use sk-abcdefghijklmnopqrstuvwxyz agora")
    package = export_profile(profile)
    assert "sk-" not in json.dumps(package)
    package["profile"]["api_key"] = "gsk_abcdefghijklmnopqrstuvwxyz"
    package["profile"]["execute"] = True
    first = import_profile(manager, package)
    second = import_profile(manager, package)
    assert first == second
    assert len(manager.list()) == before + 1
    saved = json.loads((tmp_path / "profiles" / f"{first}.json").read_text(encoding="utf-8"))
    assert "api_key" not in saved and "execute" not in saved
    assert "sk-" not in saved["system_prompt"]


def test_unknown_version_is_refused(tmp_path):
    store = ConversationStore(tmp_path / "conversations")
    package = export_conversation(_conversation())
    package["version"] = 99
    try:
        import_conversation(store, package)
    except ValueError as error:
        assert "Versão" in str(error)
    else:
        raise AssertionError("versão desconhecida foi aceita")
