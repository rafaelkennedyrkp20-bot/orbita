"""Chat no navegador: HTTP real, sem modelos, dados ou configurações do usuário."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from types import SimpleNamespace

import pytest

from agent.core.browser_chat import BrowserChatServer, MAX_BODY_BYTES


class BrowserBrain:
    def __init__(self):
        self.current_model = ("fake", "modelo")
        self.profile = SimpleNamespace(id="geral", name="Geral")
        self.profiles = SimpleNamespace(list=lambda: [SimpleNamespace(id="geral", name="Geral"), SimpleNamespace(id="codigo", name="Código")])
        self.settings = SimpleNamespace(providers=lambda: {
            "fake": {"label": "Fake", "models": ["modelo", "outro"], "api_key": "NAO_EXIBIR"},
            "deepseek_web": {"label": "DeepSeek Web", "models": ["default", "expert"]},
        })
        self.temporary = False
        self.changes = []
        self.calls = []
        self.entered = threading.Event()
        self.cancelled = threading.Event()
        self.block = False
        self.ask = False
        self.answer = None
        self.new_count = 0

    def run_turn(self, text, *, events, approve):
        self.calls.append(text)
        self.entered.set()
        if self.ask:
            self.answer = approve({"type": "tool", "tool": "run_shell", "args": {"command": "echo teste"}})
        events("text", {"text": "<script>alert(1)</script> **ok**"})
        if self.block:
            assert self.cancelled.wait(4)
        return "<script>alert(1)</script> **ok**"

    def stop(self):
        self.cancelled.set()

    def new_conversation(self):
        self.new_count += 1

    def select_profile(self, profile_id):
        self.changes.append(("profile", profile_id))
        self.profile = SimpleNamespace(id=profile_id, name="Código")

    def select_model(self, provider, model):
        self.changes.append(("model", provider, model))
        self.current_model = provider, model

    def set_temporary(self, enabled):
        self.changes.append(("temporary", enabled))
        self.temporary = enabled
        self.new_conversation()


@pytest.fixture
def browser_server():
    server = BrowserChatServer(BrowserBrain(), port=0).start()
    try:
        yield server
    finally:
        server.stop()


def request(server, path, payload=None, *, auth=True, headers=None, method=None):
    head = {"Connection": "close"}
    if auth:
        head["Authorization"] = f"Bearer {server.token}"
    if payload is not None:
        head["Content-Type"] = "application/json"
    head.update(headers or {})
    body = json.dumps(payload).encode() if payload is not None else None
    conn = HTTPConnection(server.address[0], server.address[1], timeout=5)
    try:
        conn.request(method or ("POST" if payload is not None else "GET"), path, body=body, headers=head)
        response = conn.getresponse()
        return response.status, response.read().decode(), dict(response.getheaders())
    finally:
        conn.close()


def test_loopback_only_and_token_fragment():
    for host in ("0.0.0.0", "192.168.1.1", "example.org"):
        with pytest.raises(ValueError, match="local"):
            BrowserChatServer(BrowserBrain(), host=host, port=0)
    server = BrowserChatServer(BrowserBrain(), port=0)
    try:
        assert server.url.endswith("/#token=" + server.token)
        assert len(server.token) >= 32
    finally:
        server.stop()


def test_no_execution_before_auth_and_same_origin(browser_server):
    server = browser_server
    assert request(server, "/api/chat", {"message": "oi"}, auth=False)[0] == 401
    assert request(server, "/api/chat", {"message": "oi"}, headers={"Origin": "https://evil.example"})[0] == 403
    assert request(server, "/api/chat", {"message": "oi"}, headers={"Host": "evil.example"})[0] == 403
    assert server.brain.calls == []
    assert request(server, "/api/state", auth=False)[0] == 401


def test_page_and_state_do_not_expose_token(browser_server):
    status, page, headers = request(browser_server, "/", auth=False)
    assert status == 200
    assert browser_server.token not in page
    assert "localStorage" not in page and "sessionStorage" not in page
    assert "Content-Security-Policy" in headers
    status, body, _ = request(browser_server, "/api/state")
    assert status == 200
    assert json.loads(body)["model"] == "modelo"
    assert "NAO_EXIBIR" not in body


def test_chat_stream_and_server_markdown_sanitization(browser_server):
    status, body, _ = request(browser_server, "/api/chat", {"message": "oi"})
    assert status == 200
    records = [json.loads(line) for line in body.splitlines()]
    assert records[0]["type"] == "text"
    assert records[-1]["type"] == "done"
    assert "<script>" not in records[-1]["html"]
    assert "<strong>ok</strong>" in records[-1]["html"]
    assert browser_server.brain.calls == ["oi"]


def test_request_and_attachment_limits(browser_server):
    assert request(browser_server, "/api/chat", {"message": "x" * MAX_BODY_BYTES})[0] == 413
    assert request(browser_server, "/api/chat", {"message": ""})[0] == 400
    assert request(browser_server, "/api/chat", {"message": "oi", "attachments": [{"name": ".env", "content": "SECRET"}]})[0] == 400
    assert request(browser_server, "/api/chat", {"message": "oi", "attachments": [{"name": "bin.txt", "content": "a\u0000b"}]})[0] == 400
    assert browser_server.brain.calls == []
    assert request(browser_server, "/api/chat", {"message": "leia", "attachments": [{"name": "src/app.py", "content": "print('oi')"}]})[0] == 200
    assert "src/app.py" in browser_server.brain.calls[0]
    assert "print('oi')" in browser_server.brain.calls[0]


def test_busy_blocks_parallel_chat_and_new_and_stop_cancels(browser_server):
    browser_server.brain.block = True
    with ThreadPoolExecutor() as pool:
        chat = pool.submit(request, browser_server, "/api/chat", {"message": "aguarde"})
        assert browser_server.brain.entered.wait(2)
        assert request(browser_server, "/api/chat", {"message": "segundo"})[0] == 409
        assert request(browser_server, "/api/new", {})[0] == 409
        assert request(browser_server, "/api/config", {"temporary": True})[0] == 409
        assert request(browser_server, "/api/stop", {})[0] == 200
        assert chat.result()[0] == 200
    assert browser_server.brain.calls == ["aguarde"]
    assert request(browser_server, "/api/new", {})[0] == 200
    assert browser_server.brain.new_count == 1


def test_approval_fails_closed_without_explicit_interactive_support(browser_server):
    browser_server.brain.ask = True
    assert request(browser_server, "/api/chat", {"message": "teste"})[0] == 200
    assert browser_server.brain.answer == "no"
    assert request(browser_server, "/api/approve", {"id": "forjado", "answer": "yes"})[0] == 404
    assert request(browser_server, "/api/approve", {"id": "forjado", "answer": []})[0] == 400


def test_explicit_approval_and_stop_while_waiting(browser_server):
    server = browser_server
    server.brain.ask = True
    with ThreadPoolExecutor() as pool:
        chat = pool.submit(request, server, "/api/chat", {"message": "teste", "interactive_approval": True})
        assert server.brain.entered.wait(2)
        for _ in range(100):
            pending = json.loads(request(server, "/api/state")[1])["approvals"]
            if pending:
                break
            threading.Event().wait(.01)
        assert len(pending) == 1
        assert request(server, "/api/approve", {"id": pending[0]["id"], "answer": "always"})[0] == 400
        assert request(server, "/api/approve", {"id": pending[0]["id"], "answer": "yes"})[0] == 200
        assert chat.result()[0] == 200
        assert server.brain.answer == "yes"
        server.brain.entered.clear()
        chat = pool.submit(request, server, "/api/chat", {"message": "teste 2", "interactive_approval": True})
        assert server.brain.entered.wait(2)
        assert request(server, "/api/stop", {})[0] == 200
        assert chat.result()[0] == 200
        assert server.brain.answer == "no"


def test_config_validates_before_changing_and_respects_auth(browser_server):
    server = browser_server
    assert request(server, "/api/config", {"temporary": True}, auth=False)[0] == 401
    for payload in ({"profile": "inexistente"}, {"provider": "inexistente", "model": "modelo"},
                    {"provider": "fake", "model": "inventado"}, {"model": "modelo"},
                    {"temporary": "true"}, {"temporary": 1}, {"permission_mode": "livre"},
                    {"profile": "codigo", "temporary": []}):
        assert request(server, "/api/config", payload)[0] == 400
    assert server.brain.changes == []
    status, body, _ = request(server, "/api/config", {
        "profile": "codigo", "provider": "fake", "model": "outro", "temporary": True,
    })
    assert status == 200
    state = json.loads(body)
    assert state["model"] == "outro" and state["profile"]["id"] == "codigo" and state["temporary"] is True
    assert server.brain.changes == [("profile", "codigo"), ("model", "fake", "outro"), ("temporary", True)]
    assert "NAO_EXIBIR" not in body


def test_config_handles_controlled_brain_errors(browser_server, monkeypatch):
    def fail(*_args):
        raise ValueError("Modelo indisponível")

    monkeypatch.setattr(browser_server.brain, "select_model", fail)
    status, body, _ = request(browser_server, "/api/config", {"provider": "fake", "model": "outro"})
    assert status == 400 and "Modelo indisponível" in body
    assert request(browser_server, "/api/new", {})[0] == 200


def test_selection_keeps_local_policy_on_real_provider(browser_server, monkeypatch):
    from agent.core.providers import OpenAICompatProvider

    brain = browser_server.brain
    brain.settings.get = lambda key, default=None: "local_only" if key == "execution_policy" else default

    def forbid_network(*_args, **_kwargs):
        raise AssertionError("A política deveria bloquear antes de abrir uma conexão.")

    def run_turn(text, *, events, approve):
        provider, model = brain.current_model
        adapter = OpenAICompatProvider(provider, {
            "type": "openai", "base_url": "https://cloud.example/v1", "api_key": "segredo",
        }, brain.settings)
        return adapter.chat(model, [{"role": "user", "content": text}]).text

    monkeypatch.setattr("httpx.Client", forbid_network)
    monkeypatch.setattr(brain, "run_turn", run_turn)
    assert request(browser_server, "/api/config", {"provider": "fake", "model": "outro"})[0] == 200
    status, body, _ = request(browser_server, "/api/chat", {"message": "texto privado"})
    assert status == 200
    record = json.loads(body.strip())
    assert record["type"] == "error" and "somente local" in record["message"]


def test_close_temporary_idle_clears_ram_without_changing_mode(browser_server):
    server = browser_server
    server.brain.temporary = True
    assert request(server, "/api/close", {}, auth=False)[0] == 401
    assert server.brain.new_count == 0
    assert request(server, "/api/close", {})[0] == 200
    assert server.brain.new_count == 1
    assert server.brain.temporary is True


def test_close_never_clears_a_persistent_conversation(browser_server):
    assert request(browser_server, "/api/close", {})[0] == 200
    assert browser_server.brain.new_count == 0
    assert browser_server.brain.temporary is False


def test_close_temporary_running_cancels_and_clears_after_finish(browser_server, monkeypatch):
    server = browser_server
    server.brain.temporary = True
    server.brain.block = True
    finish_allowed = threading.Event()
    original = server.brain.run_turn

    def wait_before_finish(*args, **kwargs):
        result = original(*args, **kwargs)
        assert finish_allowed.wait(4)
        return result

    monkeypatch.setattr(server.brain, "run_turn", wait_before_finish)
    with ThreadPoolExecutor() as pool:
        chat = pool.submit(request, server, "/api/chat", {"message": "aguarde"})
        assert server.brain.entered.wait(2)
        try:
            assert request(server, "/api/close", {})[0] == 200
            assert server.brain.cancelled.is_set()
            assert server.brain.new_count == 0
            assert request(server, "/api/new", {})[0] == 409
        finally:
            finish_allowed.set()
        assert chat.result()[0] == 200
    assert server.brain.new_count == 1 and server.brain.temporary is True
