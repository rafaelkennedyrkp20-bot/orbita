"""Checkpoints por resposta: foto antes/depois, diff e desfazer sem tocar no git do projeto."""

import subprocess

import pytest

from agent.core import checkpoints as cp

pytestmark = pytest.mark.skipif(not cp.git_available(), reason="git não instalado")


@pytest.fixture
def project(tmp_path):
    ws = tmp_path / "projeto"
    ws.mkdir()
    (ws / "app.py").write_text("print('oi')\n", encoding="utf-8")
    (ws / "apagar.txt").write_text("fica?\n", encoding="utf-8")
    return ws, cp.Checkpoints(tmp_path / "sombra")


def _agent_edits(ws):
    (ws / "app.py").write_text("print('olá')\nprint('mundo')\n", encoding="utf-8")
    (ws / "apagar.txt").unlink()
    (ws / "novo").mkdir()
    (ws / "novo" / "modulo.py").write_text("x = 1\n", encoding="utf-8")


def test_finish_lists_what_the_turn_changed(project):
    ws, store = project
    before = store.snapshot(ws, "antes")
    _agent_edits(ws)
    turn = store.finish(ws, before, "depois")
    got = {c.path: c.status for c in turn.changes}
    assert got == {"app.py": "M", "apagar.txt": "D", "novo/modulo.py": "A"}
    app = next(c for c in turn.changes if c.path == "app.py")
    assert (app.added, app.removed) == (2, 1)
    assert "+print('mundo')" in store.diff(ws, turn.before, turn.after)


def test_nothing_changed_means_no_turn(project):
    ws, store = project
    before = store.snapshot(ws, "antes")
    assert store.finish(ws, before, "depois") is None


def test_undo_restores_and_redo_reapplies(project):
    ws, store = project
    before = store.snapshot(ws, "antes")
    _agent_edits(ws)
    turn = store.finish(ws, before, "depois")

    result = store.undo(ws, turn.before, turn.after)
    assert (ws / "app.py").read_text(encoding="utf-8") == "print('oi')\n"
    assert (ws / "apagar.txt").exists()
    assert not (ws / "novo").exists()          # pasta vazia criada pelo agente também some
    assert sorted(result["removed"]) == ["novo/modulo.py"]

    store.undo(ws, *result["redo"])
    assert "mundo" in (ws / "app.py").read_text(encoding="utf-8")
    assert (ws / "novo" / "modulo.py").exists()
    assert not (ws / "apagar.txt").exists()


def test_project_git_is_untouched(project):
    ws, store = project
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    before = store.snapshot(ws, "antes")
    _agent_edits(ws)
    store.finish(ws, before, "depois")
    log = subprocess.run(["git", "log", "--oneline"], cwd=ws, capture_output=True, text=True)
    assert log.returncode != 0 or not log.stdout.strip()   # nenhum commit no repositório do usuário


def test_home_and_drive_root_are_not_eligible(tmp_path):
    from pathlib import Path
    assert not cp.eligible(Path.home())
    assert not cp.eligible(Path(Path.home().anchor))
    assert cp.eligible(tmp_path)
