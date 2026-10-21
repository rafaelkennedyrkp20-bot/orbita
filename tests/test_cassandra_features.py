"""Contratos novos de conversa temporária e anexos, independentes de conta externa."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock

from agent.core.brain import Brain
from agent.core import mentions
from agent.memory.memory_manager import MemoryManager
from agent.core.settings import Settings


def test_memory_only_never_creates_files(tmp_path):
    memory = MemoryManager(daily_dir=tmp_path / "daily", long_dir=tmp_path / "long",
                           profile_path=tmp_path / "profile.json", memory_only=True)
    memory.log_interaction("segredo temporário", "resposta")
    memory.remember_fact("fato temporário")
    memory.save_profile()
    memory.save_long_term()
    assert memory.facts() == ["fato temporário"]
    assert "segredo temporário" in memory.get_relevant_context("temporário")
    assert list(tmp_path.iterdir()) == []


def test_temporary_conversation_restores_original_memory_and_does_not_save():
    brain = Brain.__new__(Brain)
    original = Mock()
    brain.memory = original
    brain.session = None
    brain.conversation_id = "existing"
    brain.conversation_title = "Anterior"
    brain.pinned_prompt = brain.goal = ""
    brain.conversations = Mock()
    brain.set_temporary(True)
    assert brain.temporary is True and brain.memory is not original
    assert brain.conversation_id is None
    brain.session = SimpleNamespace(messages=[{"role": "user", "content": "temporário"}])
    assert brain.save_conversation() is None
    brain.conversations.save.assert_not_called()
    brain.set_temporary(False)
    assert brain.memory is original and brain.session is None
    assert brain.temporary is False


def test_new_temporary_conversation_discards_previous_temporary_facts():
    brain = Brain.__new__(Brain)
    brain.temporary = True
    brain.memory = MemoryManager(memory_only=True)
    brain.memory.remember_fact("fato da conversa descartada")
    brain.memory.log_interaction("pedido temporário", "resposta")
    brain.new_conversation()
    assert brain.memory.facts() == []
    assert brain.memory.get_relevant_context("temporário") is None


def test_explicit_attachments_include_nested_text_and_report_omissions(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("answer = 42", encoding="utf-8")
    (tmp_path / ".env").write_text("TOKEN=segredo", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\0binary")
    (tmp_path / "large.txt").write_text("x" * (mentions.INLINE_FILE_CHARS + 10))
    out = mentions.attach_paths("analise", [str(tmp_path)], workspace=tmp_path)
    assert out.startswith("analise")
    assert "answer = 42" in out and "src/a.py" in out
    assert "TOKEN=segredo" not in out and "\0" not in out
    assert "omitido" in out.lower() and "large.txt" in out


def test_attachments_read_has_a_byte_bound_and_deduplicates(tmp_path, monkeypatch):
    path = tmp_path / "note.txt"
    path.write_text("conteúdo único", encoding="utf-8")
    out = mentions.attach_paths("veja", [str(path), str(path), str(tmp_path)], workspace=tmp_path)
    assert out.count("conteúdo único") == 1
    # O leitor não pode carregar o arquivo inteiro para depois cortar.
    monkeypatch.setattr(Path, "read_bytes", lambda _self: (_ for _ in ()).throw(AssertionError("leitura ilimitada")))
    assert mentions._read_text(path) == "conteúdo único"


def test_attachment_project_scope_rejects_outside(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("fora do projeto")
    out = mentions.attach_paths("veja", [str(outside)], workspace=root, project_only=True)
    assert "fora do projeto" not in out
    assert "escopo" in out.lower()


def test_attachments_accept_windows_short_temp_paths():
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "note.txt"
        path.write_text("conteúdo no caminho temporário", encoding="utf-8")
        assert "conteúdo no caminho temporário" in mentions.attach_paths("veja", [str(path)], workspace=Path(folder))


def test_content_from_attachment_does_not_expand_mentions(tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("EXAMPLE_SECRET=not-a-real-key")
    note = tmp_path / "note.txt"
    note.write_text("leia @.env")
    text = mentions.attach_paths("analise", [str(note)], workspace=tmp_path)
    brain = Brain.__new__(Brain)
    brain.settings = Settings(tmp_path / "settings.json")
    brain.profiles = SimpleNamespace(get=lambda _name: SimpleNamespace(id="geral"))
    brain.memory = Mock()
    brain.pinned_prompt = brain.goal = ""
    brain.save_conversation = Mock()
    session = Mock(provider_name="ollama", model=brain.current_model[1])
    session.run.return_value = "ok"
    brain.session = session
    brain.run_turn(text)
    received = session.run.call_args.args[0]
    assert "leia @.env" in received and "EXAMPLE_SECRET" not in received


def test_session_permission_is_not_persisted_by_unrelated_save(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(path)
    settings.set("permission_mode", "auto")
    settings.set_session_only("permission_mode", "livre")
    settings.set("theme", "light")
    assert settings.get("permission_mode") == "livre"
    assert Settings(path).get("permission_mode") == "auto"
    # Escolha explícita na interface continua podendo mudar a preferência persistente.
    settings.set("permission_mode", "perguntar")
    assert Settings(path).get("permission_mode") == "perguntar"
