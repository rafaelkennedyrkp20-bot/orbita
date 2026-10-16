"""Testes determinísticos que travam os ganhos de desempenho (sem depender de relógio)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent.core import providers, routing
from agent.core.conversations import ConversationStore
from agent.core.profiles import Profile, ProfileManager
from agent.core.settings import Settings


def test_import_brain_does_not_load_heavy_packages():
    code = (
        "import sys, agent.core.brain; "
        "heavy = {'anthropic', 'httpx', 'mcp', 'asyncio', 'markdown', 'pygments', "
        "'kokoro_onnx', 'faster_whisper', 'pyautogui'}; "
        "loaded = sorted(heavy & set(sys.modules)); "
        "assert not loaded, f'Módulos pesados importados cedo demais: {loaded}'"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=15)


def test_brain_init_keeps_httpx_and_anthropic_lazy():
    code = (
        "import sys; "
        "from agent.core.brain import Brain; "
        "b = Brain(start_mcp=False); "
        "loaded = {'anthropic', 'httpx'} & set(sys.modules); "
        "assert not loaded, f'Brain(start_mcp=False) importou: {loaded}'; "
        "t = b.registry.get('generate_image'); "
        "assert t is not None and t.risk == 'write' and t.group == 'imagem'"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=15)


def test_windows_uname_does_not_spawn_ver_subprocess(monkeypatch):
    import os
    import platform
    import agent.core.brain as brain_mod

    assert brain_mod is not None
    if os.name != "nt":
        return
    monkeypatch.setattr(
        subprocess, "check_output",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("platform.system() não deve abrir cmd.exe")),
    )
    assert platform.system() == "Windows"
    assert platform.release()


def test_settings_caches_providers_and_grok_credentials(tmp_path, monkeypatch):
    from agent.core import grok_cli

    settings = Settings(tmp_path / "settings.json")
    Settings._grok_cred_cache = None
    calls = []

    def fake_exe():
        calls.append("exe")
        return "C:/grok.exe"

    monkeypatch.setattr(grok_cli, "executable", fake_exe)
    monkeypatch.setattr(grok_cli, "is_logged_in", lambda: True)

    for _ in range(20):
        assert settings.has_credentials("grok") is True
    assert len(calls) == 1

    # Cache de provedores invalida ao adicionar/remover provedor customizado
    monkeypatch.setattr(Settings, "save_api_key", staticmethod(lambda env, val: None))
    pid = settings.add_custom_provider(label="Teste Rápido", base_url="http://127.0.0.1:9999/v1")
    assert pid in settings.providers()
    settings.remove_custom_provider(pid)
    assert pid not in settings.providers()


def test_routing_catalog_cache_and_invalidation(tmp_path):
    cat_file = tmp_path / "model_catalog.json"
    first = routing.load_catalog(cat_file)
    second = routing.load_catalog(cat_file)
    assert first is second

    # Alterar o arquivo em disco invalida o cache imediatamente
    custom = [{"ref": "openai:custom-fast", "codigo": 3, "cost": 1}]
    cat_file.write_text(json.dumps(custom), encoding="utf-8")
    third = routing.load_catalog(cat_file)
    assert third == custom and third is not first


def test_conversation_store_avoids_redundant_json_reads(tmp_path, monkeypatch):
    store = ConversationStore(tmp_path / "convs")
    cid = "abcdef012345"
    store.save({
        "id": cid, "title": "Conversa rápida", "pinned_title": False,
        "created": "2026-10-16T00:00:00", "profile": "geral",
        "provider": "ollama", "model": "qwen3:14b",
        "messages": [{"role": "user", "content": "oi"}],
    })
    assert len(store.list()) == 1

    # Com o arquivo inalterado em disco, list() e load() usam o cache em memória
    def forbid_loads(*args, **kwargs):
        raise AssertionError("json.loads não deveria ser chamado para conversa já em cache")

    monkeypatch.setattr(json, "loads", forbid_loads)
    items = store.list()
    assert len(items) == 1 and items[0]["title"] == "Conversa rápida"
    loaded = store.load(cid)
    assert loaded is not None and loaded["messages"][0]["content"] == "oi"


def test_profile_manager_keeps_team_and_ordered_lists_cached(tmp_path):
    pm = ProfileManager(tmp_path / "profiles")
    initial_team_ids = [p.id for p in pm.team()]
    assert "programador" in initial_team_ids

    novo = Profile(id="especialista_perf", name="Especialista", in_team=True)
    pm.save(novo)
    assert "especialista_perf" in [p.id for p in pm.team()]
    assert pm.delete("especialista_perf") is True
    assert "especialista_perf" not in [p.id for p in pm.team()]


def test_providers_share_single_http_client():
    c1 = providers._shared_http_client()
    c2 = providers._shared_http_client()
    assert c1 is c2
    assert Path(providers.__file__).is_file()
