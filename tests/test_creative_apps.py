"""CLI nativa de apps criativos sem shell, downloads ou executáveis externos reais."""

import json
import sys
import threading
from pathlib import Path

import pytest

from agent.actions.creative_apps import register_creative_app_tools
from agent.core.studio3d import Studio3D
from agent.core.tools import ToolContext, ToolRegistry


class FakeBox:
    def __init__(self, managed=None, system=None):
        self.managed = managed
        self.system = system

    def find_executable(self, _app):
        return self.managed

    def system_executable(self, _app):
        return self.system


def app_tool(box):
    registry = ToolRegistry()
    register_creative_app_tools(registry, box=box)
    return registry.get("creative_app_run")


def test_tool_is_exec_shell_and_obeys_existing_policies():
    from agent.core.local_policy import tool_block
    from agent.core.staged_writes import staged_block

    tool = app_tool(FakeBox())
    assert tool.risk == "exec" and tool.group == "shell"
    assert tool_block({"execution_policy": "local_only"}, tool)
    assert staged_block({"staged_writes": "on"}, tool)


@pytest.mark.parametrize("app", ["godot", "openscad"])
def test_missing_app_explains_explicit_install_without_downloading(tmp_path, app):
    result = app_tool(FakeBox()).run({"app": app, "arguments": ["--version"]}, ToolContext(tmp_path))
    assert result.is_error and "toolbox_install" in result.text and app in result.text


@pytest.mark.parametrize("values", [
    {"app": "unknown", "arguments": []},
    {"app": "godot", "arguments": "--version"},
    {"app": "godot", "arguments": [1]},
    {"app": "godot", "arguments": ["bad\0argument"]},
    {"app": "godot", "arguments": ["x" * 4097]},
    {"app": "godot", "arguments": ["x"] * 129},
    {"app": "godot", "arguments": ["x" * 4000] * 5},
    {"app": "openscad", "arguments": [], "timeout": 0},
    {"app": "openscad", "arguments": [], "timeout": 601},
    {"app": "openscad", "arguments": [], "timeout": True},
    {"app": "openscad", "arguments": [], "timeout": "30"},
    {"app": "openscad", "arguments": [], "timeout": float("nan")},
])
def test_invalid_arguments_never_start_a_process(tmp_path, monkeypatch, values):
    monkeypatch.setattr(Studio3D, "_run_process", lambda *_args: pytest.fail("não deve executar"))
    result = app_tool(FakeBox(managed=Path(sys.executable))).run(values, ToolContext(tmp_path))
    assert result.is_error


@pytest.mark.parametrize("app", ["godot", "openscad"])
def test_cli_runs_real_process_stub_in_project_and_keeps_literal_arguments(tmp_path, monkeypatch, app):
    script = tmp_path / "native_app_stub.py"
    script.write_text("import json, os, sys\nprint(json.dumps({'cwd': os.getcwd(), 'args': sys.argv[1:]}))\n",
                      encoding="utf-8")
    run_process = Studio3D._run_process
    commands = []

    def run_stub(command, cwd, timeout, cancel):
        commands.append(command)
        return run_process([sys.executable, str(script), *command[1:]], cwd, timeout, cancel)

    monkeypatch.setattr(Studio3D, "_run_process", staticmethod(run_stub))
    args = ["--version", "scene with spaces.scad", "$(not-a-command)", "x; echo y"]
    result = app_tool(FakeBox(system=sys.executable)).run({"app": app, "arguments": args}, ToolContext(tmp_path))
    assert not result.is_error
    outcome = json.loads(result.text)
    output = json.loads(outcome["output"])
    assert Path(output["cwd"]) == tmp_path
    assert output["args"][-len(args):] == args
    assert commands[0][0] == sys.executable
    if app == "godot":
        assert commands[0][1:4] == ["--headless", "--path", str(tmp_path)]
    else:
        assert commands[0][1:] == args


def test_tool_reports_nonzero_exit_and_timeout_from_real_process(tmp_path, monkeypatch):
    run_process = Studio3D._run_process
    script = tmp_path / "failure.py"
    script.write_text("import sys\nprint('export failure')\nsys.exit(7)\n", encoding="utf-8")
    monkeypatch.setattr(Studio3D, "_run_process", staticmethod(
        lambda command, cwd, timeout, cancel: run_process([sys.executable, str(script)], cwd, timeout, cancel)))
    tool = app_tool(FakeBox(managed=Path(sys.executable)))
    failed = tool.run({"app": "openscad", "arguments": ["--version"]}, ToolContext(tmp_path))
    assert failed.is_error and json.loads(failed.text)["returncode"] == 7
    assert "export failure" in failed.text
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    timed_out = tool.run({"app": "openscad", "arguments": [], "timeout": 1}, ToolContext(tmp_path))
    assert timed_out.is_error and json.loads(timed_out.text)["timed_out"]


def test_tool_cancels_only_its_spawned_process(tmp_path, monkeypatch):
    run_process = Studio3D._run_process
    monkeypatch.setattr(Studio3D, "_run_process", staticmethod(
        lambda command, cwd, timeout, cancel: run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"], cwd, timeout, cancel)))
    cancel = threading.Event()
    timer = threading.Timer(0.2, cancel.set)
    timer.start()
    try:
        result = app_tool(FakeBox(managed=Path(sys.executable))).run(
            {"app": "godot", "arguments": ["--version"]}, ToolContext(tmp_path, cancel=cancel))
    finally:
        timer.cancel()
    assert result.is_error and json.loads(result.text)["cancelled"]


def test_cancelled_context_never_spawns_app(tmp_path, monkeypatch):
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(Studio3D, "_run_process", lambda *_args: pytest.fail("não deve executar"))
    result = app_tool(FakeBox(managed=Path(sys.executable))).run(
        {"app": "godot", "arguments": ["--version"]}, ToolContext(tmp_path, cancel=cancel))
    assert result.is_error and "cancel" in result.text.lower()


def test_builtin_registry_exposes_native_creative_tool(brain):
    assert brain.registry.get("creative_app_run").risk == "exec"
