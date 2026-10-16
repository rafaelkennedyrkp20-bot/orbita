from agent.core.tools import Tool, ToolContext, ToolRegistry, ToolResult


def ctx(tmp_path):
    return ToolContext(workspace=tmp_path)


def run(brain, name, args, tmp_path):
    return brain.registry.get(name).run(args, ctx(tmp_path))


def test_write_read_edit_cycle(brain, tmp_path):
    assert not run(brain, "write_file", {"path": "a/b.txt", "content": "linha 1\nlinha 2\n"}, tmp_path).is_error
    read = run(brain, "read_file", {"path": "a/b.txt"}, tmp_path)
    assert "linha 2" in read.text and "2\t" in read.text
    edit = run(brain, "edit_file", {"path": "a/b.txt", "old_string": "linha 2", "new_string": "linha dois"}, tmp_path)
    assert not edit.is_error
    assert (tmp_path / "a" / "b.txt").read_text(encoding="utf-8") == "linha 1\nlinha dois\n"


def test_edit_requires_unique_match(brain, tmp_path):
    (tmp_path / "x.txt").write_text("a a a", encoding="utf-8")
    result = run(brain, "edit_file", {"path": "x.txt", "old_string": "a", "new_string": "b"}, tmp_path)
    assert result.is_error and "3 vezes" in result.text
    result = run(brain, "edit_file", {"path": "x.txt", "old_string": "a", "new_string": "b", "replace_all": True}, tmp_path)
    assert not result.is_error and (tmp_path / "x.txt").read_text() == "b b b"


def test_glob_reports_sizes_and_sorts(brain, tmp_path):
    (tmp_path / "small.py").write_text("x")
    (tmp_path / "big.py").write_text("x" * 5000)
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "skip.py").write_text("x")
    result = run(brain, "glob_files", {"pattern": "**/*.py", "sort": "size"}, tmp_path).text
    assert result.index("big.py") < result.index("small.py")
    assert "skip.py" not in result and "Total: 2 arquivos" in result


def test_grep_finds_lines(brain, tmp_path):
    (tmp_path / "m.py").write_text("def alpha():\n    return 1\n")
    result = run(brain, "grep", {"pattern": r"def \w+", "glob": "*.py"}, tmp_path).text
    assert "m.py:1: def alpha():" in result


def test_shell_runs_and_strips_ansi(brain, tmp_path):
    result = run(brain, "run_shell", {"command": "Write-Output 'olá mundo'"}, tmp_path)
    assert not result.is_error and "olá mundo" in result.text and "\x1b[" not in result.text


def test_missing_required_argument_is_reported(brain, tmp_path):
    result = run(brain, "write_file", {"path": "x"}, tmp_path)
    assert result.is_error and "content" in result.text


def test_tool_exceptions_become_errors(tmp_path):
    registry = ToolRegistry()

    def boom(args, context):
        raise ValueError("quebrou")

    registry.register(Tool("boom", "x", {"type": "object", "properties": {}}, boom))
    result = registry.get("boom").run({}, ctx(tmp_path))
    assert result.is_error and "quebrou" in result.text


def test_deferred_tools_hidden_until_activated(tmp_path):
    registry = ToolRegistry()
    registry.register(Tool("mcp__rea__decompile", "Decompile a native function", {"type": "object"},
                           lambda a, c: ToolResult("ok"), source="mcp:rea", deferred=True, group="mcp"))
    assert registry.visible({"mcp"}) == []
    assert [t.name for t in registry.search("decompile function")] == ["mcp__rea__decompile"]
    assert [t.name for t in registry.visible({"mcp"}, activated={"mcp__rea__decompile"})] == ["mcp__rea__decompile"]
    assert registry.visible({"arquivos"}, activated={"mcp__rea__decompile"}) == []


def test_memory_tools(brain, tmp_path):
    run(brain, "remember", {"fact": "O usuário programa em Python"}, tmp_path)
    assert "Python" in run(brain, "recall", {"query": "python"}, tmp_path).text


def test_shell_quoted_executable_path(brain, tmp_path):
    result = run(brain, "run_shell", {"command": r'"C:\Windows\System32\whoami.exe"'}, tmp_path)
    assert not result.is_error, result.text


def test_shell_invalid_cwd(brain, tmp_path):
    result = run(brain, "run_shell", {"command": "Write-Output 1", "cwd": str(tmp_path / "nao")}, tmp_path)
    assert result.is_error and "inexistente" in result.text


def test_ansi_files_are_read_and_edited_in_their_encoding(brain, tmp_path):
    (tmp_path / "ansi.txt").write_bytes("ação".encode("cp1252"))
    assert "ação" in run(brain, "read_file", {"path": "ansi.txt"}, tmp_path).text
    run(brain, "edit_file", {"path": "ansi.txt", "old_string": "ação", "new_string": "função"}, tmp_path)
    assert (tmp_path / "ansi.txt").read_bytes() == "função".encode("cp1252")


def test_edit_preserves_crlf(brain, tmp_path):
    (tmp_path / "w.txt").write_bytes(b"a\r\nb\r\n")
    run(brain, "edit_file", {"path": "w.txt", "old_string": "b", "new_string": "c"}, tmp_path)
    assert (tmp_path / "w.txt").read_bytes() == b"a\r\nc\r\n"
