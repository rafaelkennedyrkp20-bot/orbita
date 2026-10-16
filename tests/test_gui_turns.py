"""Turno pela interface: modo plano trava alterações, checkpoint por resposta e @arquivo no envio."""

import json
import queue
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6.QtWebEngineWidgets")

from agent import gui  # noqa: E402
from agent.core import checkpoints  # noqa: E402
from agent.core.settings import Settings  # noqa: E402


class StubBrain:
    def __init__(self, tmp_path, workspace):
        self.workspace = workspace
        self.settings = Settings(tmp_path / "settings.json")
        self.settings.set("default_workspace", str(workspace), save=False)
        self.settings.set("permission_mode", "livre", save=False)
        self.profile = SimpleNamespace(workspace="")
        self.session = SimpleNamespace(always_allowed={"write_file"})
        self.current_model = ("ollama", "m")
        self.seen = {}

    def effective_workspace(self):
        return self.workspace

    def run_turn(self, text, images, events=None, approve=None):
        # Como o loop real: no modo livre não pergunta; nos outros, write_file pede permissão.
        mode = self.settings.get("permission_mode")
        answer = "yes" if mode == "livre" else approve({"type": "tool", "tool": "write_file", "risk": "write"})
        self.seen = {"text": text, "mode": mode, "allowed": set(self.session.always_allowed), "answer": answer}
        if answer == "yes":
            (self.workspace / "novo.py").write_text("x = 1\n", encoding="utf-8")
        return "pronto"


@pytest.fixture
def setup(tmp_path):
    ws = tmp_path / "projeto"
    ws.mkdir()
    (ws / "app.py").write_text("print('oi')\n", encoding="utf-8")
    brain = StubBrain(tmp_path, ws)
    worker = gui.AgentWorker(brain, push=lambda payload: None)
    worker.checkpoints = checkpoints.Checkpoints(tmp_path / "sombra")
    events = []
    worker.events = lambda kind, data: events.append((kind, data))
    return brain, worker, events, ws


def test_plan_turn_blocks_changes_and_restores_permissions(setup):
    brain, worker, events, ws = setup
    worker._turn("refatore tudo", [], False, plan=True)
    assert brain.seen["mode"] == "perguntar" and brain.seen["answer"] == "no"
    assert brain.seen["allowed"] == set()                     # "sempre permitir" não fura o plano
    assert brain.settings.get("permission_mode") == "livre"   # volta ao que era
    assert brain.session.always_allowed == {"write_file"}
    assert not (ws / "novo.py").exists()
    assert ("turn_end", {"text": "pronto", "plan": True}) in events


@pytest.mark.skipif(not checkpoints.git_available(), reason="git não instalado")
def test_normal_turn_reports_checkpoint(setup):
    brain, worker, events, ws = setup
    worker._turn("crie novo.py", [], False)
    cp = next(data for kind, data in events if kind == "checkpoint")
    assert [(c["path"], c["status"]) for c in cp["changes"]] == [("novo.py", "A")]
    worker.checkpoints.undo(ws, cp["before"], cp["after"])
    assert not (ws / "novo.py").exists()


def test_stop_releases_a_pending_approval(setup):
    import threading
    import time

    _, worker, _, _ = setup
    answers = []
    thread = threading.Thread(target=lambda: answers.append(worker.approve({"type": "tool", "tool": "run_shell"})))
    thread.start()
    for _ in range(50):          # espera a confirmação ficar pendente
        if worker._pending:
            break
        time.sleep(0.02)
    worker.deny_pending()        # o que o botão Parar faz
    thread.join(timeout=2)
    assert not thread.is_alive() and answers == ["no"]


KEY = "rv_FAKEa1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ."   # chave inventada só para o teste


@pytest.mark.parametrize("name", ["gpt-4o-mini", "deepseek-chat", "qwen3:14b", "claude-opus-5-5", "gemini-2.5-flash",
                                  "meta-llama/Llama-3.3-70B-Instruct-Turbo", "Qwen3-235B-A22B-Instruct-2507",
                                  "hf.co/JonathanColetti/Qwen3.8-27B-Uncensored-GGUF:IQ4_XS", "grok-4-fast"])
def test_model_names_are_not_secrets(name):
    assert not gui.looks_like_secret(name)


def test_api_keys_are_detected():
    assert gui.looks_like_secret(KEY)
    assert gui.looks_like_secret("sk-proj-Ab3dEfGh1jKlMnOpQrStUvWxYz0123456789")
    assert gui.looks_like_secret("qualquer-coisa", known_keys=("qualquer-coisa",))


def _api_with_key_as_model(tmp_path, monkeypatch):
    monkeypatch.setenv("ORBITA_RIVER_API_KEY", KEY)
    settings = Settings(tmp_path / "s.json")
    settings.set("providers", {"river": {"type": "openai", "label": "river", "base_url": "https://api.river.ai/v1",
                                         "api_key_env": "ORBITA_RIVER_API_KEY", "models": [KEY, "river-large"]}})
    settings.set("provider", "river")
    settings.set("model", KEY)
    api = gui.Api.__new__(gui.Api)
    api.brain = SimpleNamespace(settings=settings, select_model=lambda p, m: None)
    return api, settings


def test_scrub_removes_a_saved_key_from_the_model_fields(tmp_path, monkeypatch):
    api, settings = _api_with_key_as_model(tmp_path, monkeypatch)
    assert api.scrub_secret_models() is True
    assert settings.get("model") == "river-large"
    assert settings.provider("river")["models"] == ["river-large"]
    assert KEY not in (tmp_path / "s.json").read_text(encoding="utf-8")
    assert api.scrub_secret_models() is False   # nada mais a corrigir


def test_select_model_and_add_provider_refuse_a_key(tmp_path, monkeypatch):
    api, _ = _api_with_key_as_model(tmp_path, monkeypatch)
    assert "chave de API" in json.loads(gui.Api.selectModel(api, "river", KEY))["error"]
    raw = json.dumps({"label": "outra", "url": "https://x/v1", "key": "abc123", "model": "abc123"})
    assert "chave de API" in json.loads(gui.Api.addProvider(api, raw))["error"]


def test_send_attaches_mentions_and_plan_note(setup):
    brain, worker, _, ws = setup
    api = gui.Api.__new__(gui.Api)      # sem janela: só o que send usa
    api.brain = brain
    api.win = SimpleNamespace(worker=SimpleNamespace(commands=queue.Queue()))
    gui.Api.send(api, json.dumps({"text": "explique @app.py", "plan": True}))
    command, (text, images, speak, plan) = api.win.worker.commands.get_nowait()
    assert command == "turn" and plan is True
    assert "print('oi')" in text and "[Modo plano]" in text
    assert gui._visible_user_text(text) == "explique @app.py"


def test_api_rename_and_delete_conversation(tmp_path):
    from agent.core.brain import Brain
    from agent.core.conversations import ConversationStore

    brain = Brain(start_mcp=False)
    brain.conversations = ConversationStore(tmp_path / "convs")
    api = gui.Api.__new__(gui.Api)
    api.brain = brain

    session = brain.new_session()
    session.messages = [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}]
    cid = brain.save_conversation()
    assert cid and brain.conversation_id == cid

    assert json.loads(gui.Api.renameConversation(api, cid, "  Título Personalizado  ")) is True
    assert brain.conversation_title == "Título Personalizado"
    saved = brain.conversations.load(cid)
    assert saved["title"] == "Título Personalizado" and saved["pinned_title"] is True

    assert json.loads(gui.Api.deleteConversation(api, cid)) is True
    assert brain.conversations.load(cid) is None
    assert brain.conversation_id is None and brain.session is None


def test_pinned_prompt_saved_reapplied_and_in_system_prompt(tmp_path):
    from agent.core.brain import Brain
    from agent.core.conversations import ConversationStore

    brain = Brain(start_mcp=False)
    brain.conversations = ConversationStore(tmp_path / "convs")
    api = gui.Api.__new__(gui.Api)
    api.brain = brain

    # Conversa nova sem mensagens: vale desde o primeiro turno
    res = json.loads(gui.Api.setPinnedPrompt(api, "  Responda sempre em tópicos curtos.  "))
    assert res["pinned_prompt"] == "Responda sempre em tópicos curtos."
    session = brain.new_session()
    sys_prompt = session.system_prompt(session.visible_tools())
    assert "## Instruções fixas desta conversa\nResponda sempre em tópicos curtos." in sys_prompt

    session.messages = [{"role": "user", "content": "teste"}, {"role": "assistant", "content": "ok"}]
    cid = brain.save_conversation()
    assert brain.conversations.load(cid)["pinned_prompt"] == "Responda sempre em tópicos curtos."

    # Nova conversa limpa o prompt fixo
    brain.new_conversation()
    assert brain.pinned_prompt == ""
    clean_session = brain.new_session()
    assert "## Instruções fixas desta conversa" not in clean_session.system_prompt(clean_session.visible_tools())

    # Reabrir a conversa reaplica o prompt fixo na sessão e no system prompt
    reopened = json.loads(gui.Api.openConversation(api, cid))
    assert reopened["pinned_prompt"] == "Responda sempre em tópicos curtos."
    assert brain.pinned_prompt == "Responda sempre em tópicos curtos."
    reopened_prompt = brain.session.system_prompt(brain.session.visible_tools())
    assert "## Instruções fixas desta conversa\nResponda sempre em tópicos curtos." in reopened_prompt

    # Remover o prompt fixo atualiza a sessão e o arquivo salvo
    gui.Api.setPinnedPrompt(api, "")
    assert brain.pinned_prompt == ""
    assert "## Instruções fixas desta conversa" not in brain.session.system_prompt(brain.session.visible_tools())
    assert brain.conversations.load(cid)["pinned_prompt"] == ""
