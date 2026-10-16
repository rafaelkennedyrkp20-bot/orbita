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
