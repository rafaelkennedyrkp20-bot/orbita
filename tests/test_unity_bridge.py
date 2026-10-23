"""Ponte Unity: contrato autenticado local e instalação somente em projeto explícito.

Não substitui validação no Editor Unity real: testes de Python usam servidor local.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from agent.actions.studio3d import register_studio3d_tools
from agent.core.mcp_hub import SERVER_LEASES
from agent.core.studio3d import Studio3D, UNITY_BRIDGE
from agent.core.tools import ToolContext, ToolRegistry


class FakeBox:
    def list(self):
        return []


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "UnityProject"
    (root / "Assets").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.0.0f1", encoding="utf-8")
    studio = Studio3D(tmp_path / "studio.json", box=FakeBox())
    registry = ToolRegistry()
    register_studio3d_tools(registry, studio)
    return studio, root, registry


@pytest.fixture
def endpoint(setup, monkeypatch):
    from agent.core import studio3d
    studio, root, registry = setup
    studio.unity_install_bridge(str(root))
    token = (root / "Library/Orbita/bridge-token.txt").read_text(encoding="utf-8")
    requests = []
    response = {"protocol": "OrbitaUnity/1"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append((self.command, self.path, json.loads(body) if body else None, self.headers.get("X-Orbita-Token")))
            data = json.dumps(response).encode()
            self.send_response(200 if self.headers.get("X-Orbita-Token") == token else 403)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(studio3d, "UNITY_PORT", server.server_port)
    studio.configure({"unity": {"url": f"http://127.0.0.1:{server.server_port}"}})
    yield studio, root, registry, requests, response, token
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_unity_install_is_explicit_idempotent_and_does_not_leak_token(setup):
    studio, root, registry = setup
    result = studio.unity_install_bridge(str(root))
    target = root / "Assets/Editor/OrbitaBridge.cs"
    assert target.read_text(encoding="utf-8") == UNITY_BRIDGE.read_text(encoding="utf-8")
    token_path = root / "Library/Orbita/bridge-token.txt"
    token = token_path.read_text(encoding="utf-8")
    assert len(token) == 64
    assert token not in studio.path.read_text(encoding="utf-8")
    assert token not in json.dumps(result)
    assert token not in json.dumps(studio.status())
    assert studio.status()["unity"]["project_path"] == str(root)
    assert studio.status()["unity"]["state"] == "not_checked"
    studio.unity_install_bridge(str(root))
    assert token_path.read_text(encoding="utf-8") == token


def test_install_preserves_existing_code_and_rejects_invalid_projects(setup, tmp_path):
    studio, root, registry = setup
    with pytest.raises(ValueError, match="Projeto Unity inválido"):
        studio.unity_install_bridge(str(tmp_path))
    target = root / "Assets/Editor/OrbitaBridge.cs"
    target.parent.mkdir()
    target.write_text("// código da pessoa", encoding="utf-8")
    with pytest.raises(ValueError, match="conteúdo diferente"):
        studio.unity_install_bridge(str(root))
    assert target.read_text(encoding="utf-8") == "// código da pessoa"
    assert not (root / "Library").exists()


def test_install_checks_project_write_scope_before_any_write(setup, tmp_path):
    studio, root, registry = setup
    workspace = tmp_path / "OtherProject"
    workspace.mkdir()
    session = SimpleNamespace(settings={"file_scope": "project"}, workspace=workspace)
    result = registry.get("unity_install_bridge").run({"project_path": str(root)}, ToolContext(workspace, session=session))
    assert result.is_error and "Escopo do projeto" in result.text
    assert not (root / "Assets/Editor").exists()


def test_unity_native_connection_has_a_fixed_loopback_port(setup):
    studio, root, registry = setup
    for url in ("http://127.0.0.1:30013", "http://[::1]:30012"):
        with pytest.raises(ValueError, match="30012"):
            studio.configure({"unity": {"url": url}})


def test_probe_validates_protocol_and_authenticates_without_exposing_credentials(endpoint):
    studio, root, registry, requests, response, token = endpoint
    assert studio.probe()["unity"]["state"] == "available"
    assert requests == [("GET", "/orbita/info", None, token)]
    response["protocol"] = "other"
    assert studio.probe()["unity"]["state"] == "error"
    assert token not in studio.status()["unity"]["message"]


def test_scene_and_creation_use_separate_read_and_exec_contracts(endpoint):
    studio, root, registry, requests, response, token = endpoint
    response.update(scene="Assets/Main.unity", objects=[])
    result = registry.get("unity_scene").run({}, ToolContext(root))
    assert not result.is_error and json.loads(result.text)["objects"] == []
    response.clear()
    response["created"] = {"name": "Teste", "instance_id": 42}
    result = registry.get("unity_create_primitive").run({"primitive": "cube", "name": "Teste",
        "position": {"x": 1, "y": 2, "z": 3}}, ToolContext(root))
    assert not result.is_error
    assert requests[-1] == ("POST", "/orbita/primitive", {"primitive": "cube", "name": "Teste",
                                  "position": {"x": 1, "y": 2, "z": 3}}, token)
    assert registry.get("unity_scene").risk == "read"
    assert registry.get("unity_create_primitive").risk == "exec"
    assert registry.get("unity_install_bridge").risk == "exec"


@pytest.mark.parametrize("position", [{"x": float("nan"), "y": 0, "z": 0}, {"x": True, "y": 0, "z": 0},
                                     {"x": 0, "y": 0}, {"x": 1000001, "y": 0, "z": 0}])
def test_unity_invalid_creation_is_rejected_before_network(endpoint, position):
    studio, root, registry, requests, response, token = endpoint
    with pytest.raises(ValueError):
        studio.unity_create_primitive("cube", "Bad", position)
    assert requests == []


@pytest.mark.parametrize("engine", ["unreal", "unity"])
def test_reserved_engine_cannot_change_target_or_install_bridge(setup, engine):
    studio, root, registry = setup
    owner = object()
    assert SERVER_LEASES.acquire(f"studio3d-{engine}", owner, timeout=0)
    before = studio.status()
    try:
        with pytest.raises(ValueError, match="reservada"):
            studio.configure({engine: {"enabled": True}})
        assert studio.status()[engine] == before[engine]
        assert SERVER_LEASES.owner(f"studio3d-{engine}") is owner
        if engine == "unity":
            with pytest.raises(ValueError, match="reservado"):
                studio.unity_install_bridge(str(root))
            assert not (root / "Assets/Editor").exists()
    finally:
        SERVER_LEASES.release_all(owner)
    studio.configure({engine: {"enabled": True}})
    assert studio.status()[engine]["enabled"]


def test_unity_execution_respects_managed_policies(setup):
    from agent.core.local_policy import tool_block
    from agent.core.staged_writes import staged_block
    studio, root, registry = setup
    for name in ("unity_create_primitive", "unity_install_bridge"):
        tool = registry.get(name)
        assert tool_block({"execution_policy": "local_only"}, tool)
        assert staged_block({"staged_writes": "on"}, tool)


def test_missing_token_blocks_network_and_read_cannot_install(endpoint):
    studio, root, registry, requests, response, token = endpoint
    (root / "Library/Orbita/bridge-token.txt").unlink()
    result = registry.get("unity_scene").run({}, ToolContext(root))
    assert result.is_error and "unity_install_bridge" in result.text
    assert requests == []


def test_bridge_is_packaged_as_an_explicit_public_resource():
    from scripts import build_package
    resources = build_package.resources(build_package.ROOT, names=[build_package.UNITY_BRIDGE])
    assert resources == [(UNITY_BRIDGE, "agent/integrations/unity")]


def test_bridge_editor_contract_has_no_arbitrary_execution_endpoint():
    source = UNITY_BRIDGE.read_text(encoding="utf-8")
    assert "[InitializeOnLoad]" in source
    assert "new TcpListener(IPAddress.Loopback, Port)" in source
    assert 'headers.ContainsKey("Origin")' in source
    assert 'headers.TryGetValue("X-Orbita-Token"' in source
    assert "EditorApplication.update += Dispatch" in source
    assert "Undo.RegisterCreatedObjectUndo" in source
    assert "SaveScene" not in source and "Process.Start" not in source and "Assembly.Load" not in source
