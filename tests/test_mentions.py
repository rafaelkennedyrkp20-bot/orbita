"""@arquivo: busca para o autocompletar e anexo do conteúdo citado."""

from agent.core import mentions


def _project(tmp_path):
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "gui.py").write_text("janela = 1\n", encoding="utf-8")
    (tmp_path / "agent" / "brain.py").write_text("cerebro = 2\n", encoding="utf-8")
    (tmp_path / "pasta com espaço").mkdir()
    (tmp_path / "pasta com espaço" / "nota.txt").write_text("olá\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "gui.js").write_text("x", encoding="utf-8")
    (tmp_path / "foto.png").write_bytes(b"\x89PNG\0\0binario")
    mentions._cache.clear()
    return tmp_path


def test_search_prefers_file_name_and_skips_heavy_folders(tmp_path):
    ws = _project(tmp_path)
    assert mentions.search(ws, "gui") == ["agent/gui.py"]
    assert set(mentions.search(ws, "agent/")) == {"agent/gui.py", "agent/brain.py"}
    assert len(mentions.search(ws, "")) == 4


def test_expand_attaches_content_and_keeps_user_text(tmp_path):
    ws = _project(tmp_path)
    out = mentions.expand('corrija @agent/gui.py e veja @"pasta com espaço/nota.txt".', ws)
    assert out.startswith('corrija @agent/gui.py e veja @"pasta com espaço/nota.txt".')
    assert "### agent/gui.py" in out and "janela = 1" in out
    assert "### pasta com espaço/nota.txt" in out and "olá" in out


def test_expand_ignores_emails_unknown_and_outside_paths(tmp_path):
    ws = _project(tmp_path)
    text = "mande para a@b.com, veja @naoexiste.py e @../segredo.txt"
    assert mentions.expand(text, ws) == text


def test_binary_and_folders_are_listed_not_inlined(tmp_path):
    ws = _project(tmp_path)
    out = mentions.expand("olhe @foto.png e @agent", ws)
    assert "- foto.png (não anexado" in out
    assert "- agent/ (pasta)" in out
    assert "PNG" not in out.split("---", 1)[1].replace("foto.png", "")
