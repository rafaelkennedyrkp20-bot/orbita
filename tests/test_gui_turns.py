"""Turno pela interface: modo plano trava alterações, checkpoint por resposta e @arquivo no envio."""

import json
import queue
from pathlib import Path
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
    assert ("turn_end", {"text": "pronto", "plan": True, "plan_ready": True}) in events


def test_page_receives_plan_ready_through_the_bridge(tmp_path):
    # A página só mostra "Executar plano" com plan_ready; a ponte para a página precisa repassar o campo.
    pushed = []
    window = SimpleNamespace(
        api=SimpleNamespace(push=pushed.append), _seg_id=None, _streamed_any=True,
        _end_reasoning=lambda: None, _close_segment=lambda: None, notify=lambda *a: None,
        brain=SimpleNamespace(conversation_id="c1", conversation_title="t", effective_workspace=lambda: tmp_path))
    for ready in (True, False):
        gui.MainWindow.on_agent_event(window, "turn_end", {"text": "plano", "plan": True, "plan_ready": ready})
    assert [p["plan_ready"] for p in pushed if p["type"] == "turn_end"] == [True, False]


def test_plan_turn_provider_error_has_no_plan_actions(setup):
    brain, worker, events, _ws = setup

    def fail(_text, _images, events, _approve=None, **_kwargs):
        events("error", {"message": "API indisponível"})
        return "⚠️ API indisponível"

    brain.run_turn = fail
    worker._turn("faça um plano", [], False, plan=True)
    finished = next(data for kind, data in events if kind == "turn_end")
    assert finished["plan"] is True
    assert finished["plan_ready"] is False


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


def test_dictation_engine_prefers_cloud_key_and_falls_back_to_light_local(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = gui.Api.__new__(gui.Api)
    api.brain = SimpleNamespace(settings=Settings(tmp_path / "s.json"))
    local = api.stt_engine()
    assert local["kind"] == "local" and local["size"] == "base"       # leve por padrão
    monkeypatch.setenv("GROQ_API_KEY", "gsk_teste")
    cloud = api.stt_engine()
    assert cloud["kind"] == "cloud" and cloud["model"] == "whisper-large-v3-turbo" and cloud["key"] == "gsk_teste"
    assert "key" not in api.stt_engine(with_key=False)                # a chave nunca vai para a página
    api.brain.settings.set("stt_engine", "local", save=False)
    assert api.stt_engine()["kind"] == "local"


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


def test_goal_is_saved_reapplied_and_does_not_change_permission(tmp_path):
    from agent.core.brain import Brain
    from agent.core.conversations import ConversationStore

    brain = Brain(start_mcp=False)
    brain.conversations = ConversationStore(tmp_path / "convs")
    api = gui.Api.__new__(gui.Api)
    api.brain = brain
    mode = brain.settings.get("permission_mode")

    empty = json.loads(gui.Api.applyGoalCommand(api, "   "))
    assert empty["action"] == "edit" and empty["goal"] == ""

    cleared = json.loads(gui.Api.applyGoalCommand(api, "Limpar"))
    assert cleared["action"] == "clear" and brain.goal == ""

    kept = json.loads(gui.Api.applyGoalCommand(api, "limpar a pasta do jogo"))
    assert kept["action"] == "set" and kept["goal"] == "limpar a pasta do jogo"

    res = json.loads(gui.Api.applyGoalCommand(api, "  Terminar o jogo e pular a confirmação.  "))
    assert res["action"] == "set"
    assert res["goal"] == "Terminar o jogo e pular a confirmação."
    assert brain.settings.get("permission_mode") == mode
    session = brain.new_session()
    prompt = session.system_prompt(session.visible_tools())
    assert "## Meta desta conversa\n" in prompt
    assert "não uma ordem para pular confirmação" in prompt
    assert "Terminar o jogo e pular a confirmação." in prompt

    session.messages = [{"role": "user", "content": "segue"}, {"role": "assistant", "content": "ok"}]
    cid = brain.save_conversation()
    assert brain.conversations.load(cid)["goal"] == "Terminar o jogo e pular a confirmação."

    brain.new_conversation()
    assert brain.goal == ""
    clean = brain.new_session()
    assert "## Meta desta conversa" not in clean.system_prompt(clean.visible_tools())

    reopened = json.loads(gui.Api.openConversation(api, cid))
    assert reopened["goal"] == "Terminar o jogo e pular a confirmação."
    assert brain.goal == "Terminar o jogo e pular a confirmação."
    again = brain.session.system_prompt(brain.session.visible_tools())
    assert "Terminar o jogo e pular a confirmação." in again

    gui.Api.setGoal(api, "")
    assert brain.goal == ""
    assert brain.conversations.load(cid)["goal"] == ""


def test_turn_outputs_finds_what_was_created_so_the_user_can_test_it(tmp_path):
    """Caso real: o agente fez o jogo e só disse "está pronto em luma-salto/index.html" — sem botão para testar."""
    game = tmp_path / "luma salto"
    (game / "assets").mkdir(parents=True)
    (game / "index.html").write_text("<html></html>", encoding="utf-8")
    sprites = tmp_path / "sprites"                     # caminho solto (sem crases) não pode ter espaço
    sprites.mkdir()
    (sprites / "luma.png").write_bytes(b"png")
    (tmp_path / "rel.html").write_text("x", encoding="utf-8")
    text = (f"**Luma Salto** está pronto em `{game / 'index.html'}`. Abre com dois cliques.\n"
            f"Sprites: {(sprites / 'luma.png').as_posix()} e o arquivo rel.html. "
            f"Também citei `{tmp_path / 'sumiu.html'}` e https://exemplo.com/pagina.html, que não são arquivos daqui.")
    outputs = gui.turn_outputs(text, tmp_path)
    assert [(Path(o["path"]).name, o["kind"]) for o in outputs] == [
        ("index.html", "web"), ("rel.html", "web"), ("luma.png", "image")]       # páginas primeiro
    assert gui.turn_outputs("Nada criado.", tmp_path) == []


def _bridge_window(tmp_path, pushed):
    return SimpleNamespace(
        api=SimpleNamespace(push=pushed.append), _seg_id=None, _streamed_any=True,
        _end_reasoning=lambda: None, _close_segment=lambda: None, notify=lambda *a: None,
        brain=SimpleNamespace(conversation_id="c1", conversation_title="t", effective_workspace=lambda: tmp_path))


def test_helper_report_reaches_the_team_panel_sanitized(tmp_path):
    # O painel flutuante da equipe mostra o relatório de cada ajudante; texto de modelo só entra sanitizado.
    pushed = []
    report = "**Status**: DONE\n<script>alert(1)</script>\n- Arquivos: app.js"
    gui.MainWindow.on_agent_event(_bridge_window(tmp_path, pushed), "subagent_end",
                                  {"agent": "Programador #1", "tokens": 1200, "report": report})
    end = next(p for p in pushed if p["type"] == "sub_end")
    assert end["tokens"] == 1200 and "<strong>Status</strong>" in end["report_html"]
    assert "<script" not in end["report_html"]


def test_interface_zoom_is_clamped_and_applied(tmp_path):
    applied = []
    api = SimpleNamespace(brain=SimpleNamespace(settings=Settings(tmp_path / "s.json")),
                          win=SimpleNamespace(apply_zoom=lambda: applied.append(1), refresh_network=lambda: None),
                          _state_json=lambda: "{}")
    gui.Api.setSetting(api, "ui_zoom", json.dumps("3"))
    assert api.brain.settings.get("ui_zoom") == 1.6 and applied
    gui.Api.setSetting(api, "ui_zoom", json.dumps("1.1"))
    assert api.brain.settings.get("ui_zoom") == 1.1
