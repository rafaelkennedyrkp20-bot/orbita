"""Contrato do conector de conta, sem enviar dados nem precisar de login."""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent.core import deepseek_web as web
from agent.core.providers import ProviderError
from agent.core.settings import Settings


def sse(value):
    return "data: " + json.dumps(value)


def test_stream_keeps_raw_markdown_and_separates_reasoning():
    parser = web._Completion()
    assert parser.feed([sse({"v": {"response": {"fragments": [
        {"type": "THINK", "content": "Penso"}]}}})]) == [("reasoning", "Penso")]
    assert parser.feed([sse({"p": "response/fragments/-1/content", "o": "APPEND", "v": " mais"})]) == [
        ("reasoning", " mais")]
    assert parser.feed([sse({"v": " ainda"})]) == [("reasoning", " ainda")]
    assert parser.feed([sse({"p": "response/fragments", "o": "APPEND", "v": [
        {"type": "RESPONSE", "content": "```python\n"}]}),
        sse({"p": "response/fragments/-1/content", "v": "print(1)\n```"}),
        "data: [DONE]"]) == [("text", "```python\n"), ("text", "print(1)\n```")]


def test_protocol_errors_are_not_empty_success():
    with pytest.raises(ProviderError, match="falha de geração"):
        web._Completion().feed([sse({"type": "error"})])
    with pytest.raises(ProviderError, match="SSE inválido"):
        web._Completion().feed(["data: {broken"])
    with pytest.raises(ProviderError, match="formato dos fragmentos"):
        web._Completion().feed([sse({"p": "response/fragments/-1/content", "v": "sem fragmento"})])


def test_serialization_preserves_system_tools_and_rejects_lost_images():
    messages = [
        {"role": "system", "content": "use ferramentas"},
        {"role": "assistant", "content": "", "tool_calls": [{"name": "read_file", "arguments": {"path": "a"}}]},
        {"role": "tool", "name": "read_file", "tool_call_id": "call1", "content": "conteúdo"},
        {"role": "user", "content": "continue"},
    ]
    serialized = web.serialize_messages(messages)
    assert [json.loads(line) for line in serialized.splitlines()[1:]] == messages
    with pytest.raises(ProviderError, match="imagens"):
        web.serialize_messages([{"role": "user", "content": "ver", "images": ["p.png"]}])


class Editor:
    @property
    def first(self):
        return self

    def count(self):
        return 1

    def fill(self, prompt):
        self.prompt = prompt

    def press(self, key):
        assert key == "Enter"


class Page:
    def __init__(self, frames, *, authenticated=True):
        self.editor = Editor()
        self.frames = iter(frames)
        self.authenticated = authenticated
        self.closed = False
        self.options = None

    def evaluate(self, script, options=None):
        if "localStorage" in script:
            return self.authenticated
        if script == web._DRAIN:
            return next(self.frames)
        if options is not None:
            self.options = options

    def locator(self, selector):
        assert selector == "textarea"
        return self.editor

    def wait_for_timeout(self, milliseconds):
        pass


def install_page(monkeypatch, page):
    @contextmanager
    def browser(cfg, visible=False):
        try:
            yield page
        finally:
            page.closed = True
    monkeypatch.setattr(web, "_browser_page", browser)


def provider(tmp_path):
    settings = Settings(tmp_path / "settings.json")
    return web.DeepSeekWebProvider("deepseek_web", {
        "type": "deepseek_web", "base_url": web.CHAT_URL, "profile_dir": str(tmp_path / "profile")}, settings)


def test_provider_streams_callbacks_and_closes_owned_page(tmp_path, monkeypatch):
    page = Page([{"lines": [sse({"v": {"response": {"fragments": [
        {"type": "THINK", "content": "r"}, {"type": "RESPONSE", "content": "olá"}]}}})], "done": True}])
    install_page(monkeypatch, page)
    text, reasoning = [], []
    result = provider(tmp_path).chat("expert-thinking", [{"role": "user", "content": "oi"}],
                                     on_text=text.append, on_reasoning=reasoning.append)
    assert result.text == "olá" and result.reasoning == "r" and result.stop_reason == "stop"
    assert text == ["olá"] and reasoning == ["r"]
    assert page.closed
    assert page.options == {"model": "expert", "thinking": True, "search": False}


def test_search_option_and_deletion_failure_are_explicit(tmp_path, monkeypatch):
    page = Page([{"lines": [sse({"v": {"response": {"fragments": [
        {"type": "RESPONSE", "content": "resposta"}]}}})], "done": True}])
    old_evaluate = page.evaluate

    def evaluate(script, options=None):
        if script == web._DELETE_OWN_CHAT:
            return {"ok": False, "error": "A sessão não foi criada nesta chamada."}
        return old_evaluate(script, options)

    page.evaluate = evaluate
    install_page(monkeypatch, page)
    monkeypatch.setenv("ORBITA_DEEPSEEK_WEB_SEARCH", "1")
    monkeypatch.setenv("ORBITA_DEEPSEEK_DELETE_CHAT", "true")
    text = []
    result = provider(tmp_path).chat("default", [], on_text=text.append)
    assert page.options["search"] is True
    assert result.native["deepseek_web"]["remote_chat_deleted"] is False
    assert "não foi criada" in result.text
    assert "".join(text) == result.text
    assert page.closed


def test_boolean_options_respect_false_configuration(monkeypatch):
    monkeypatch.setenv("ORBITA_DEEPSEEK_WEB_SEARCH", "1")
    assert web._option({}, "search_enabled", "ORBITA_DEEPSEEK_WEB_SEARCH") is True
    assert web._option({"search_enabled": False}, "search_enabled", "ORBITA_DEEPSEEK_WEB_SEARCH") is False
    assert web._option({"search_enabled": "false"}, "search_enabled", "ORBITA_DEEPSEEK_WEB_SEARCH") is False


def test_missing_login_and_backend_errors_surface(tmp_path, monkeypatch):
    page = Page([], authenticated=False)
    install_page(monkeypatch, page)
    with pytest.raises(ProviderError, match="--deepseek-login"):
        provider(tmp_path).chat("default", [])
    assert page.closed
    page = Page([{"error": "HTTP 429", "done": True}])
    install_page(monkeypatch, page)
    with pytest.raises(ProviderError, match="HTTP 429"):
        provider(tmp_path).chat("default", [])
    assert page.closed


def test_cancel_before_browser_and_local_only_block_network(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(web, "_browser_page", lambda *a, **kw: opened.append(True))
    client = provider(tmp_path)
    cancel = threading.Event()
    cancel.set()
    assert client.chat("default", [], cancel=cancel).stop_reason == "cancelled"
    client.settings.set("execution_policy", "local_only", save=False)
    with pytest.raises(ProviderError, match="somente local"):
        client.chat("default", [])
    with pytest.raises(ProviderError, match="somente local"):
        web.login(client.cfg, client.settings)
    assert not opened


def test_cancel_midstream_returns_partial_answer_and_closes(tmp_path, monkeypatch):
    cancel = threading.Event()
    page = Page([{"lines": [sse({"v": {"response": {"fragments": [
        {"type": "RESPONSE", "content": "parcial"}]}}})], "done": False}])
    install_page(monkeypatch, page)
    result = provider(tmp_path).chat("default", [], cancel=cancel, on_text=lambda text: cancel.set())
    assert result.text == "parcial" and result.stop_reason == "cancelled" and page.closed


def test_cancel_also_attempts_opt_in_remote_cleanup(tmp_path, monkeypatch):
    cancel = threading.Event()
    page = Page([{"lines": [sse({"v": {"response": {"fragments": [
        {"type": "RESPONSE", "content": "parcial"}]}}})], "done": False}])
    old_evaluate, cleanup = page.evaluate, []

    def evaluate(script, options=None):
        if script == web._DELETE_OWN_CHAT:
            cleanup.append(True)
            return {"ok": True}
        return old_evaluate(script, options)

    page.evaluate = evaluate
    install_page(monkeypatch, page)
    client = provider(tmp_path)
    client.cfg["delete_remote_chat"] = True
    result = client.chat("default", [], cancel=cancel, on_text=lambda text: cancel.set())
    assert result.stop_reason == "cancelled" and result.text == "parcial"
    assert result.native["deepseek_web"]["remote_chat_deleted"] is True
    assert cleanup == [True] and page.closed


def test_cdp_is_local_only_and_same_profile_shares_lock(tmp_path):
    with pytest.raises(ProviderError, match="este computador"):
        web.status({"cdp_url": "http://remote.example:9222"})
    cfg = {"profile_dir": str(tmp_path / "profile")}
    assert web._session_lock(cfg) is web._session_lock(dict(cfg))
    assert web.status(cfg)["profile_exists"] is False


def test_cdp_closes_only_owned_tab_and_uses_current_thread(monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    events = []

    class Tab:
        def set_default_timeout(self, value):
            pass

        def add_init_script(self, value):
            pass

        def goto(self, *args, **kwargs):
            events.append(("goto", threading.get_ident()))

        def close(self):
            events.append("tab_closed")

    class Context:
        def new_page(self):
            return Tab()

        def close(self):
            events.append("context_closed")

    class Browser:
        contexts = [Context()]

        def close(self):
            events.append("browser_closed")

    class Runtime:
        chromium = None

        def __init__(self):
            self.chromium = self

        def connect_over_cdp(self, *args, **kwargs):
            return Browser()

    @contextmanager
    def runtime():
        yield Runtime()
        events.append("disconnected")

    monkeypatch.setattr(playwright, "sync_playwright", runtime)
    with web._browser_page({"cdp_url": "http://127.0.0.1:9222"}):
        pass
    assert events == [("goto", threading.get_ident()), "tab_closed", "disconnected"]


@pytest.mark.parametrize("delete_mode", ["off", "own", "existing", "rejected"])
def test_real_browser_preserves_site_stream_and_observes_completion(tmp_path, monkeypatch, delete_mode):
    """Página local: autenticação, envio pelo DOM e resposta SSE no Chrome real."""
    playwright = pytest.importorskip("playwright.sync_api")
    channel = "chrome" if Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists() else None
    try:
        with playwright.sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True, **({"channel": channel} if channel else {}))
            browser.close()
    except playwright.Error as error:
        if "Executable doesn't exist" in str(error) or "not found" in str(error):
            pytest.skip("Navegador Playwright não instalado")
        raise
    bodies = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = """<textarea></textarea><script>
            localStorage.setItem('userToken', 'fixture-local');
            document.querySelector('textarea').addEventListener('keydown', async event => {
              if(event.key !== 'Enter') return;
              event.preventDefault();
              let id = 'preexisting-session';
              if (CREATE) {
                const created = await fetch('/api/v0/chat_session/create', {method: 'POST', body:'{}'});
                id = (await created.json()).data.biz_data.chat_session.id;
              }
              const response = await fetch('/api/v0/chat/completion', {
                method: 'POST', headers: {Authorization: 'Bearer fixture-local'},
                body: JSON.stringify({prompt: event.target.value, chat_session_id: id})});
              window.siteResponse = await response.text();
            });</script>""".replace("CREATE", "false" if delete_mode == "existing" else "true").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            bodies.append({"path": self.path, **json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            if self.path == "/api/v0/chat_session/create":
                self._json({"code": 0, "data": {"biz_data": {"chat_session": {"id": "owned-session"}}}})
                return
            if self.path == "/api/v0/chat_session/delete":
                assert self.headers["Authorization"] == "Bearer fixture-local"
                self._json({"code": 5, "msg": "exclusão rejeitada"} if delete_mode == "rejected" else {"code": 0})
                return
            body = (sse({"v": {"response": {"fragments": [
                {"type": "THINK", "content": "raciocínio"}]}}}) + "\n\n" +
                sse({"p": "response/fragments", "o": "APPEND", "v": [
                    {"type": "RESPONSE", "content": "```python\nprint(1)\n```"}]}) +
                "\n\ndata: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(web, "CHAT_URL", f"http://127.0.0.1:{server.server_port}/")
    client = provider(tmp_path)
    client.cfg.update(search_enabled=True, delete_remote_chat=delete_mode != "off")
    if channel:
        client.cfg["browser_channel"] = channel
    try:
        result = client.chat("expert-thinking", [{"role": "user", "content": "oi"}])
        assert result.text.startswith("```python\nprint(1)\n```") and result.reasoning == "raciocínio"
        completion = next(body for body in bodies if body["path"].endswith("/completion"))
        assert completion["model_type"] == "expert" and completion["thinking_enabled"] is True
        assert completion["search_enabled"] is True
        assert "oi" in completion["prompt"]
        deletions = [body for body in bodies if body["path"].endswith("/delete")]
        if delete_mode in {"off", "existing"}:
            assert not deletions
        else:
            assert deletions == [{"path": "/api/v0/chat_session/delete", "chat_session_id": "owned-session"}]
        if delete_mode == "own":
            assert result.native["deepseek_web"]["remote_chat_deleted"] is True
        elif delete_mode in {"existing", "rejected"}:
            assert result.native["deepseek_web"]["remote_chat_deleted"] is False
            assert "Não consegui apagar" in result.text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
