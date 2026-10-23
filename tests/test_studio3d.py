"""Integrações 3D: contrato HTTP real local e execução isolada, sem apps externos."""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.core.studio3d import Studio3D, validate_unreal_url
from agent.actions.studio3d import register_studio3d_tools
from agent.core.tools import ToolContext, ToolRegistry


class FakeBox:
    def list(self):
        return [{"id": "blender", "installed": False, "system_exe": "", "exe": ""}]


@pytest.fixture
def studio(tmp_path):
    return Studio3D(tmp_path / "studio.json", box=FakeBox())


def test_model_can_configure_local_connection_without_running_an_app(studio, tmp_path):
    registry, events = ToolRegistry(), []
    register_studio3d_tools(registry, studio)
    tool = registry.get("studio3d_configure")
    assert tool.risk == "write"
    ctx = ToolContext(tmp_path, emit=lambda kind, data: events.append((kind, data)))
    result = tool.run({"unreal": {"enabled": True, "url": "http://localhost:30010"}}, ctx)
    assert not result.is_error
    assert json.loads(result.text)["unreal"]["state"] == "not_checked"
    assert studio.status()["unreal"]["url"] == "http://127.0.0.1:30010"
    assert events[0][0] == "studio3d" and events[0][1]["status"]["unreal"]["enabled"]
    before = studio.path.read_bytes()
    assert tool.run({"unreal": {"url": "http://example.com:30010"}}, ctx).is_error
    assert studio.path.read_bytes() == before


def test_model_configuration_rejects_cancel_and_reserved_editor(studio, tmp_path):
    from agent.core.mcp_hub import SERVER_LEASES
    registry = ToolRegistry()
    register_studio3d_tools(registry, studio)
    tool = registry.get("studio3d_configure")
    assert tool.run({}, ToolContext(tmp_path)).is_error
    cancel = threading.Event()
    cancel.set()
    assert tool.run({"unreal": {"enabled": True}}, ToolContext(tmp_path, cancel=cancel)).is_error
    owner = object()
    assert SERVER_LEASES.acquire("studio3d-unreal", owner, timeout=0)
    try:
        assert tool.run({"unreal": {"enabled": True}}, ToolContext(tmp_path)).is_error
        assert not studio.path.exists()
        assert SERVER_LEASES.owner("studio3d-unreal") is owner
    finally:
        SERVER_LEASES.release_all(owner)


@pytest.fixture
def server():
    received = []
    response = {"status": 200, "body": {"HttpRoutes": [
        {"Path": "/remote/object/call", "Verb": "Put"},
        {"Path": "/remote/object/describe", "Verb": "Put"}]}}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append((self.command, self.path, None))
            self.respond()

        def do_PUT(self):
            received.append((self.command, self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.respond()

        def respond(self):
            data = json.dumps(response["body"]).encode()
            self.send_response(response["status"])
            if response.get("location"):
                self.send_header("Location", response["location"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", received, response
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


@pytest.mark.parametrize("url", ["http://example.org:30010", "http://127.0.0.1:30010/remote", "file:///x",
                                    "http://u:p@localhost:30010", "http://localhost:30010/?x=1",
                                    "http://127.0.0.1:30010/#x", "http://127.0.0.2:30010", "https://localhost:30010"])
def test_unreal_url_rejects_nonlocal_or_ambiguous_addresses(url):
    with pytest.raises(ValueError):
        validate_unreal_url(url)


def test_url_normalizes_localhost_without_dns():
    assert validate_unreal_url("http://localhost:30010/") == "http://127.0.0.1:30010"
    assert validate_unreal_url("http://[::1]:30010") == "http://[::1]:30010"


def test_configuration_is_atomic_and_persists(studio, tmp_path):
    assert not studio.path.exists()
    before = studio.status()
    studio.configure({"unreal": {"enabled": True, "url": "http://localhost:30011"}})
    saved = Studio3D(studio.path, box=FakeBox()).status()
    assert saved["unreal"]["enabled"] is True
    assert saved["unreal"]["url"] == "http://127.0.0.1:30011"
    assert before["unreal"]["enabled"] is False
    content = studio.path.read_bytes()
    with pytest.raises(ValueError):
        studio.configure({"unreal": {"url": "http://example.com"}})
    assert studio.path.read_bytes() == content


def test_status_is_offline_and_probe_validates_protocol(studio, server):
    url, received, response = server
    studio.configure({"unreal": {"enabled": True, "url": url}})
    assert studio.status()["unreal"]["state"] == "not_checked"
    assert received == []
    state = studio.probe()
    assert state["unreal"]["state"] == "available"
    assert state["unreal"]["checked_at"]
    assert received == [("GET", "/remote/info", None)]
    response["body"] = {"unrelated": True}
    assert studio.probe()["unreal"]["state"] == "error"


def test_redirect_is_not_followed(studio, server):
    url, received, response = server
    studio.configure({"unreal": {"enabled": True, "url": url}})
    response.update(status=302, location=url + "/unexpected")
    assert studio.probe()["unreal"]["state"] == "error"
    assert len(received) == 1


def test_call_requires_enablement_and_never_retries_a_mutation(studio, server):
    url, received, response = server
    with pytest.raises(ValueError):
        studio.unreal_call("/Game/A", "DoIt", {})
    assert received == []
    studio.configure({"unreal": {"enabled": True, "url": url}})
    response["body"] = {"ReturnValue": True}
    assert studio.unreal_call("/Game/A", "DoIt", {"X": 3}) == {"ReturnValue": True}
    assert received == [("PUT", "/remote/object/call", {"objectPath": "/Game/A", "functionName": "DoIt",
                                                           "parameters": {"X": 3}, "generateTransaction": True})]
    response["status"] = 500
    with pytest.raises(RuntimeError):
        studio.unreal_call("/Game/A", "DoIt", {})
    assert len(received) == 2


def test_call_and_describe_validate_inputs_before_network(studio, server):
    url, received, response = server
    studio.configure({"unreal": {"enabled": True, "url": url}})
    for object_path, function, params in [("", "DoIt", {}), ("/Game/A", "", {}), ("/Game/A", "DoIt", [])]:
        with pytest.raises(ValueError):
            studio.unreal_call(object_path, function, params)
    assert received == []
    response["body"] = {"Functions": []}
    assert studio.unreal_describe("/Game/A") == {"Functions": []}
    assert received[0] == ("PUT", "/remote/object/describe", {"objectPath": "/Game/A"})


def test_probe_handles_wrong_json_type(studio, server):
    url, received, response = server
    studio.configure({"unreal": {"enabled": True, "url": url}})
    response["body"] = ["wrong"]
    assert studio.probe()["unreal"]["state"] == "error"
    assert "HttpRoutes" in studio.status()["unreal"]["message"]


def test_blender_path_must_be_absolute_executable(studio, tmp_path):
    with pytest.raises(ValueError):
        studio.configure({"blender": {"path": "relative.exe"}})
    with pytest.raises(ValueError):
        studio.configure({"blender": {"path": str(tmp_path / "missing.exe")}})


def test_tools_keep_exec_risk_and_obey_policies(studio):
    from agent.core.local_policy import tool_block
    from agent.core.staged_writes import staged_block
    registry = ToolRegistry()
    register_studio3d_tools(registry, studio)
    assert registry.get("studio3d_status").risk == "read"
    assert registry.get("unreal_describe").risk == "read"
    for name in ["unreal_call", "blender_run_script"]:
        tool = registry.get(name)
        assert tool.risk == "exec" and tool.group == "shell"
        assert tool_block({"execution_policy": "local_only"}, tool)
        assert staged_block({"staged_writes": "on"}, tool)


def test_tools_handle_cancel_before_contact(studio, server, tmp_path):
    url, received, response = server
    studio.configure({"unreal": {"enabled": True, "url": url}})
    registry = ToolRegistry()
    register_studio3d_tools(registry, studio)
    cancel = threading.Event()
    cancel.set()
    result = registry.get("unreal_call").run({"object_path": "/Game/A", "function_name": "DoIt"},
                                             ToolContext(tmp_path, cancel=cancel))
    assert result.is_error and "cancel" in result.text.lower()
    assert received == []


def test_blender_runs_only_existing_project_script_and_surfaces_failure(studio, tmp_path, monkeypatch):
    script = tmp_path / "scene.py"
    script.write_text("print('render')", encoding="utf-8")
    outside = tmp_path.parent / "outside.py"
    calls = []
    monkeypatch.setattr(studio, "_blender_executable", lambda: Path(sys.executable))
    monkeypatch.setattr(studio, "_run_process", lambda command, cwd, timeout, cancel: calls.append((command, cwd)) or
                        {"returncode": 1, "output": "Python error", "elapsed_seconds": 0.1})
    with pytest.raises(ValueError):
        studio.blender_run_script(str(outside), tmp_path)
    with pytest.raises(ValueError):
        studio.blender_run_script("missing.py", tmp_path)
    result = studio.blender_run_script("scene.py", tmp_path)
    command, cwd = calls[0]
    assert command[0] == sys.executable and command[-1] == str(script)
    assert "--background" in command and "--python-exit-code" in command
    assert cwd == tmp_path and result["returncode"] == 1


def test_process_runner_has_real_timeout_cancellation_and_bounded_output(studio, tmp_path):
    out = studio._run_process([sys.executable, "-c", "print('x' * 200000)"], tmp_path, 5, None)
    assert out["returncode"] == 0 and len(out["output"]) <= 24000
    result = studio._run_process([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, 0.15, None)
    assert result["timed_out"] and result["returncode"] != 0
    cancel = threading.Event()
    timer = threading.Timer(0.15, cancel.set)
    timer.start()
    try:
        result = studio._run_process([sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, 5, cancel)
    finally:
        timer.cancel()
    assert result["cancelled"] and result["returncode"] != 0


def test_corrupt_configuration_does_not_crash_and_keeps_disabled_defaults(tmp_path):
    path = tmp_path / "studio.json"
    path.write_text('{broken', encoding="utf-8")
    status = Studio3D(path, box=FakeBox()).status()
    assert not status["unreal"]["enabled"]
    assert status["config_error"]


def test_configuration_change_invalidates_probe(studio, server):
    url, received, response = server
    studio.configure({"unreal": {"enabled": True, "url": url}})
    assert studio.probe()["unreal"]["state"] == "available"
    studio.configure({"unreal": {"enabled": False}})
    assert studio.status()["unreal"]["state"] == "disabled"
    assert not studio.status()["unreal"]["checked_at"]


def test_missing_blender_does_not_discard_unreal_configuration(studio, tmp_path):
    executable = tmp_path / ("blender.exe" if os.name == "nt" else "blender")
    executable.write_bytes(b"fake binary")
    executable.chmod(0o755)
    studio.configure({"blender": {"path": str(executable)}, "unreal": {"enabled": True}})
    executable.unlink()
    reloaded = Studio3D(studio.path, box=FakeBox()).status()
    assert reloaded["unreal"]["enabled"]
    assert reloaded["blender"]["state"] == "missing"
    assert reloaded["blender"]["configured_path"] == str(executable)


def test_http_response_and_request_are_bounded(studio, server):
    url, received, response = server
    studio.configure({"unreal": {"enabled": True, "url": url}})
    with pytest.raises(ValueError, match="1 MB"):
        studio.unreal_call("/Game/A", "DoIt", {"data": "x" * 1_000_001})
    assert received == []
    response["body"] = {"data": "x" * 1_000_001}
    assert studio.probe()["unreal"]["state"] == "error"
    assert "1 MB" in studio.status()["unreal"]["message"]


def test_timeout_kills_the_spawned_tree_and_closes_output_reader(studio, tmp_path):
    script = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)']); time.sleep(10)"
    result = studio._run_process([sys.executable, "-c", script], tmp_path, 0.5, None)
    assert result["timed_out"] and result["elapsed_seconds"] < 5
    assert not any(t.name == "orbita-blender-output" and t.is_alive() for t in threading.enumerate())


def test_unreal_tool_holds_session_lease_until_turn_end(studio, server, tmp_path):
    from agent.core.mcp_hub import SERVER_LEASES
    url, received, response = server
    studio.configure({"unreal": {"enabled": True, "url": url}})
    response["body"] = {}
    registry = ToolRegistry()
    register_studio3d_tools(registry, studio)
    session = SimpleNamespace()
    ctx = ToolContext(tmp_path, session=session)
    try:
        result = registry.get("unreal_call").run({"object_path": "/Game/A", "function_name": "DoIt"}, ctx)
        assert not result.is_error
        assert SERVER_LEASES.owner("studio3d-unreal") is session
    finally:
        SERVER_LEASES.release_all(session)
