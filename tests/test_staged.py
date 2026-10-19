"""Revisão antes de gravar: proposta, acúmulo, conflito e leitura do que ainda não está no disco."""

from agent.core.staged_writes import Store
from agent.core.tools import ToolContext


class _Settings:
    def __init__(self, **values):
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


def test_two_edits_accumulate_and_reject_does_not_write(tmp_path):
    path = tmp_path / "nota.txt"
    path.write_bytes("um\r\ndois\r\n".encode("cp1252"))
    store = Store(tmp_path / "staged.json")
    assert store.propose_edit(path, "dois", "três") is None
    assert store.propose_edit(path, "um", "zero") is None
    assert path.read_bytes() == "um\r\ndois\r\n".encode("cp1252")
    assert store.read(path) == "zero\r\ntrês\r\n"
    assert "-dois" in store.diff(path) and "+três" in store.diff(path)
    assert store.reject(path) is None
    assert path.read_bytes() == "um\r\ndois\r\n".encode("cp1252")
    assert store.read(path) is None


def test_apply_preserves_encoding_and_conflict_does_not_overwrite(tmp_path):
    path = tmp_path / "café.txt"
    original = "café\r\nlinha\r\n".encode("cp1252")
    path.write_bytes(original)
    store = Store(tmp_path / "staged.json")
    assert store.propose_edit(path, "linha", "duas") is None
    path.write_bytes("mudou\r\n".encode("cp1252"))
    assert "Nada foi sobrescrito" in (store.apply(path) or "")
    assert path.read_bytes() == "mudou\r\n".encode("cp1252")
    path.write_bytes(original)
    fresh = Store(tmp_path / "outra.json")
    assert fresh.propose_edit(path, "linha", "duas") is None
    assert fresh.apply(path) is None
    assert path.read_bytes() == "café\r\nduas\r\n".encode("cp1252")


def test_create_then_read_sees_the_proposal(brain, tmp_path, monkeypatch):
    store = Store(tmp_path / "staged.json")
    monkeypatch.setattr("agent.core.staged_writes.get_store", lambda: store)
    session = type("Session", (), {"settings": _Settings(staged_writes="on"), "workspace": tmp_path})()
    context = ToolContext(workspace=tmp_path, session=session)
    written = brain.registry.get("write_file").run({"path": "novo.txt", "content": "alfa"}, context)
    assert "ainda não está no disco" in written.text
    assert not (tmp_path / "novo.txt").exists()
    read = brain.registry.get("read_file").run({"path": "novo.txt"}, context)
    assert "PROPOSTA" in read.text and "alfa" in read.text
    edited = brain.registry.get("edit_file").run(
        {"path": "novo.txt", "old_string": "alfa", "new_string": "beta"}, context)
    assert not edited.is_error
    assert store.apply(tmp_path / "novo.txt") is None
    assert (tmp_path / "novo.txt").read_text(encoding="utf-8") == "beta"
