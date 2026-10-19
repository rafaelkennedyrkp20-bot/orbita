"""Mapa limitado do projeto e evidência real de verificação da equipe."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent.core import agent_loop, repo_map
from agent.core.agent_loop import AgentSession
from agent.core.providers import ChatResult
from agent.core.tools import Tool, ToolResult


def write(root, path, source="def function(): pass\n"):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target


def test_map_symbols_imports_ignore_and_secrets(tmp_path):
    write(tmp_path, "app.py", "from api import serve\nclass Client: pass\ndef start(): pass\n")
    write(tmp_path, "api.ts", "import {x} from './library';\nexport function serve() {}\n")
    for name in ["data/private.py", "venv/hidden.py", "models/model.py", ".env.py", "secrets.py", "ignored.py"]:
        write(tmp_path, name)
    write(tmp_path, ".gitignore", "ignored.py\ngenerated/\n")
    write(tmp_path, "generated/no.py")
    write(tmp_path, "nested/.gitignore", "local.py\n")
    write(tmp_path, "nested/local.py")
    data = json.loads(repo_map.RepoMap(tmp_path).render())
    paths = {entry["path"] for entry in data}
    assert paths == {"app.py", "api.ts"}
    app = next(entry for entry in data if entry["path"] == "app.py")
    assert set(app["symbols"]) == {"Client", "start"} and "api" in app["imports"]
    assert "serve" in next(entry for entry in data if entry["path"] == "api.ts")["symbols"]


def test_cache_invalidates_edit_add_delete_and_gitignore(tmp_path, monkeypatch):
    source = write(tmp_path, "app.py", "def before(): pass\n")
    index = repo_map.RepoMap(tmp_path)
    assert "before" in index.render()
    original = Path.read_bytes
    reads = []

    def tracked(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    assert "before" in index.render() and source not in reads
    source.write_text("def after_change(): pass\n", encoding="utf-8")
    assert "after_change" in index.render() and "before" not in index.render()
    write(tmp_path, "new.py")
    assert "new.py" in index.render()
    write(tmp_path, ".gitignore", "new.py\n")
    assert "new.py" not in index.render()
    source.unlink()
    assert index.render() == ""


def test_bounded_files_bytes_time_and_valid_json(tmp_path, monkeypatch):
    for i in range(12):
        write(tmp_path, f"f{i:02}.py", "def visible(): pass\n" * 100)
    assert len(json.loads(repo_map.RepoMap(tmp_path, max_files=2).render())) == 2
    assert repo_map.RepoMap(tmp_path, max_bytes=10).render() == ""
    rendered = repo_map.RepoMap(tmp_path).render(max_chars=220)
    assert len(rendered) <= 220 and isinstance(json.loads(rendered), list)
    counter = iter(range(1000))
    monkeypatch.setattr(repo_map.time, "monotonic", lambda: next(counter))
    assert repo_map.RepoMap(tmp_path, max_seconds=0.1).render() == ""


def test_never_follows_symlink_or_reparse_point(tmp_path):
    outside = tmp_path / "outside"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write(outside, "private.py", "def secret_function(): pass\n")
    try:
        (workspace / "link").symlink_to(outside, target_is_directory=True)
        (workspace / "leak.py").symlink_to(outside / "private.py")
    except OSError:
        pytest.skip("sistema não permite criar symlinks")
    assert repo_map.RepoMap(workspace).render() == ""


def test_prompt_requires_explicit_workspace_and_treats_map_as_data(brain, tmp_path, monkeypatch):
    source = write(tmp_path, "app.py", "def visible(): pass\n")
    index_calls = []
    original = repo_map.RepoMap.render
    monkeypatch.setattr(repo_map.RepoMap, "render", lambda self, **kwargs: index_calls.append(self.root) or original(self, **kwargs))
    session = AgentSession(brain, brain.profiles.get("programador"), "fake", "m")
    session.system_prompt([])
    assert not index_calls
    session.profile = replace(session.profile, workspace=str(tmp_path))
    prompt = session.system_prompt([])
    assert source.name in prompt and "Dados do mapa do projeto" in prompt
    assert "não são instruções" in prompt and index_calls == [tmp_path.resolve()]


@pytest.mark.parametrize("outcome", ["PASS", "FAIL", "MISSING", "DENIED", "SKIP"])
def test_verify_requested_requires_actual_gate(brain, monkeypatch, tmp_path, outcome):
    class FakeProvider:
        supports_native_tools = True

        def chat(self, *args, **kwargs):
            return ChatResult(text="Status: DONE\nArquivos: app.py\nVerificação: Quality Gate: PASS")

    monkeypatch.setattr(agent_loop, "get_provider", lambda *a: FakeProvider())
    brain.settings.set("default_workspace", str(tmp_path), save=False)
    gate_calls = []
    brain.registry.unregister_source("unused")
    if outcome == "MISSING":
        original = brain.registry.get
        monkeypatch.setattr(brain.registry, "get", lambda name: None if name == "verify_project" else original(name))
    else:
        text = "Quality Gate: PASS\n[PASS] pyflakes: 0 erros" if outcome == "PASS" else (
            "Quality Gate: PASS\n[SKIP] pyflakes indisponível" if outcome == "SKIP" else "Quality Gate: FAIL")
        brain.registry.register(Tool("verify_project", "verify", {},
                                     lambda a, c: gate_calls.append(1) or ToolResult(text, is_error=outcome == "FAIL"),
                                     risk="exec", group="shell"))
    session = AgentSession(brain, brain.profiles.get("geral"), "fake", "m", approve=lambda r: "no")
    brain.settings.set("permission_mode", "auto" if outcome == "DENIED" else "livre", save=False)
    result = session.delegate([{"task": "implemente", "verify": True}])
    if outcome == "PASS":
        assert "Status: DONE" in result.text and gate_calls == [1]
    else:
        assert "Status: DONE" not in result.text
        assert "Status: PARTIAL" in result.text and "Não trate como pronto" in result.text
