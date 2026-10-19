"""API local: desligada não escuta, e ligada não executa ferramenta nem vaza chave."""

import json
import threading
from http.client import HTTPConnection

import pytest

from agent.core.local_api import LocalApi, LocalApiError, default_chat, maybe_start


TOKEN = "t" * 16


class _Settings:
    def __init__(self, local_api="off", policy="open"):
        self._data = {"local_api": local_api, "execution_policy": policy, "remote_access": "off"}
        self._providers = {
            "ollama": {"type": "ollama", "base_url": "http://127.0.0.1:11434", "models": ["llama"],
                       "api_key": "sk-ollama-nao-mostrar"},
            "lmstudio": {"type": "openai", "base_url": "http://127.0.0.1:1234/v1", "models": ["llama"],
                         "api_key": "sk-lmstudio-nao-mostrar"},
            "nuvem": {"type": "openai", "base_url": "https://example.invalid/v1", "models": ["eco"],
                      "api_key": "sk-nuvem-nao-mostrar"},
        }

    def get(self, key, default=None):
        return self._data.get(key, default)

    def providers(self):
        return self._providers

    def provider(self, name):
        if name not in self._providers:
            raise KeyError(name)
        return self._providers[name]


def _refuse_bind(*_args, **_kwargs):
    raise AssertionError("não deveria escutar")


def test_off_and_missing_token_do_not_bind(monkeypatch):
    monkeypatch.setattr("agent.core.local_api.ThreadingHTTPServer", _refuse_bind)
    assert maybe_start(_Settings("off")) is None
    monkeypatch.delenv("ORBITA_LOCAL_API_TOKEN", raising=False)
    with pytest.raises(LocalApiError, match="ORBITA_LOCAL_API_TOKEN"):
        maybe_start(_Settings("on"))
    monkeypatch.setenv("ORBITA_LOCAL_API_TOKEN", "curto")
    with pytest.raises(LocalApiError, match="ORBITA_LOCAL_API_TOKEN"):
        maybe_start(_Settings("on"))


def test_other_hosts_do_not_bind(monkeypatch):
    monkeypatch.setattr("agent.core.local_api.ThreadingHTTPServer", _refuse_bind)
    for host in ("0.0.0.0", "localhost", "192.168.0.10"):
        with pytest.raises(LocalApiError, match="127.0.0.1"):
            LocalApi(_Settings(), lambda *_args: "", token=TOKEN, host=host)


def _request(port, method, path, body=None, token=None, origin=None, length=None):
    headers = {"Connection": "close"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    if length is not None:
        headers["Content-Length"] = str(length)
    payload = None if body is None else json.dumps(body).encode("utf-8")
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read()
    finally:
        conn.close()
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeError, json.JSONDecodeError):
        parsed = {"raw": raw}
    return response.status, parsed, raw


def test_auth_origin_and_models_do_not_leak_or_call_chat():
    calls = []

    def chat(*args):
        calls.append(args)
        return "nao"

    api = LocalApi(_Settings(), chat, token=TOKEN).start()
    try:
        port = api.address[1]
        status, _body, _raw = _request(port, "GET", "/v1/models")
        assert status == 401 and calls == []
        status, _body, _raw = _request(port, "GET", "/v1/models", token="outra-chave-16!!")
        assert status == 401 and calls == []
        status, _body, _raw = _request(port, "GET", "/v1/models", token=TOKEN, origin="https://evil.example")
        assert status == 403 and calls == []
        status, body, raw = _request(port, "GET", "/v1/models", token=TOKEN)
        assert status == 200
        ids = [row["id"] for row in body["data"]]
        assert "ollama:llama" in ids and "lmstudio:llama" in ids
        assert b"sk-" not in raw
        assert all(set(row) == {"id", "object", "owned_by"} for row in body["data"])
    finally:
        api.stop()


def test_tools_approval_and_unknown_model_do_not_call_chat():
    calls = []

    def chat(*args):
        calls.append(args)
        return "nao"

    api = LocalApi(_Settings(), chat, token=TOKEN).start()
    try:
        port = api.address[1]
        messages = [{"role": "user", "content": "oi"}]
        status, _body, _raw = _request(port, "POST", "/v1/chat/completions",
                                       {"model": "nuvem:eco", "messages": messages, "tools": []}, token=TOKEN)
        assert status == 403
        status, _body, _raw = _request(port, "POST", "/v1/chat/completions",
                                       {"model": "nuvem:eco", "messages": messages, "tool_choice": "auto"}, token=TOKEN)
        assert status == 403
        status, _body, _raw = _request(port, "POST", "/v1/approve", {"ok": True}, token=TOKEN)
        assert status == 403
        status, _body, _raw = _request(port, "POST", "/v1/chat/completions",
                                       {"model": "eco", "messages": messages}, token=TOKEN)
        assert status == 400
        status, _body, _raw = _request(port, "POST", "/v1/chat/completions",
                                       {"model": "nuvem:ausente", "messages": messages}, token=TOKEN)
        assert status == 404
        status, _body, _raw = _request(port, "POST", "/v1/chat/completions", {"model": "nuvem:eco", "messages": messages},
                                       token=TOKEN, length=300_000)
        assert status == 413
        assert calls == []
    finally:
        api.stop()


def test_completion_uses_the_listed_model_id():
    def chat(provider, model, messages, cancel, on_text):
        assert (provider, model) == ("nuvem", "eco")
        assert messages[0]["content"] == "oi"
        assert on_text is None
        return "pronto"

    api = LocalApi(_Settings(), chat, token=TOKEN).start()
    try:
        status, body, _raw = _request(api.address[1], "POST", "/v1/chat/completions",
                                      {"model": "nuvem:eco", "messages": [{"role": "user", "content": "oi"}]},
                                      token=TOKEN)
    finally:
        api.stop()
    assert status == 200
    assert body["model"] == "nuvem:eco"
    assert body["id"].startswith("chatcmpl-")
    assert body["choices"][0]["message"]["content"] == "pronto"
    assert api.releases == 1


def test_cancel_before_complete_does_not_call_chat_or_hold_the_slot():
    calls = []

    def chat(*args):
        calls.append(args)
        return "nao"

    api = LocalApi(_Settings(), chat, token=TOKEN)
    try:
        cancel = threading.Event()
        cancel.set()
        with pytest.raises(LocalApiError, match="cancelada"):
            api.complete("ollama", "llama", [{"role": "user", "content": "oi"}], cancel, None)
        assert calls == []
        assert api.releases == 0
    finally:
        api._httpd.server_close()


def test_stream_cancel_stops_and_releases(monkeypatch):
    from agent.core import local_api

    original = local_api._Handler._stream

    def wrapped(self, provider, model, messages, cancel, response_id, full_model):
        raw = self.wfile

        class Guard:
            def write(self, data):
                if data.startswith(b"data:"):
                    raise OSError("cliente foi embora")
                return raw.write(data)

            def __getattr__(self, name):
                return getattr(raw, name)

        self.wfile = Guard()
        return original(self, provider, model, messages, cancel, response_id, full_model)

    monkeypatch.setattr(local_api._Handler, "_stream", wrapped)
    seen = {}

    def chat(provider, model, messages, cancel, on_text):
        seen["called"] = True
        on_text("pedaço")
        seen["cancelled"] = cancel.is_set()
        return "cortado"

    api = LocalApi(_Settings(), chat, token=TOKEN).start()
    try:
        conn = HTTPConnection("127.0.0.1", api.address[1], timeout=5)
        try:
            body = json.dumps({"model": "nuvem:eco", "stream": True,
                               "messages": [{"role": "user", "content": "oi"}]}).encode("utf-8")
            conn.request("POST", "/v1/chat/completions", body=body,
                         headers={"Authorization": f"Bearer {TOKEN}", "Connection": "close",
                                  "Content-Type": "application/json"})
            response = conn.getresponse()
            response.read()
            assert response.status == 200
        finally:
            conn.close()
    finally:
        api.stop()
    assert seen["called"] is True
    assert seen["cancelled"] is True
    assert api.releases == 1


def test_default_chat_ignores_tool_calls(monkeypatch):
    executed = []

    class Result:
        text = "só texto"
        tool_calls = [{"name": "run_shell", "arguments": {"command": "whoami"}}]

    class Provider:
        def chat(self, model, messages, tools=None, cancel=None, on_text=None):
            assert tools is None
            executed.append(tools)
            return Result()

    monkeypatch.setattr("agent.core.providers.get_provider", lambda name, settings: Provider())
    text = default_chat(_Settings(), "nuvem", "eco", [{"role": "user", "content": "oi"}], threading.Event(), None)
    assert text == "só texto"
    assert executed == [None]


def test_default_chat_refuses_cloud_when_local_only(monkeypatch):
    monkeypatch.setattr("agent.core.providers.get_provider", lambda name, settings: (_ for _ in ()).throw(AssertionError("provedor")))
    with pytest.raises(LocalApiError, match="somente local"):
        default_chat(_Settings(policy="local_only"), "nuvem", "eco",
                     [{"role": "user", "content": "oi"}], threading.Event(), None)


class _RealSettings(_Settings):
    """Settings com o que get_provider precisa, para usar adaptadores reais."""

    def __init__(self, policy="open"):
        super().__init__("on", policy)
        self._providers["grok"] = {"type": "grok_cli", "models": ["grok-build"]}

    @staticmethod
    def api_key(cfg):
        return ""


def test_chat_endpoints_refuse_external_agent_without_starting_it(monkeypatch):
    """#7: Grok Build é um agente com ferramentas próprias; chat sem ferramentas não pode iniciá-lo."""
    from agent.core.grok_cli import GrokBuildProvider

    started = []
    monkeypatch.setattr(GrokBuildProvider, "run_agent", lambda self, *a, **k: started.append(k) or ("x", None, {}))
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: started.append(a) or (_ for _ in ()).throw(AssertionError("Popen")))
    settings = _RealSettings()
    with pytest.raises(LocalApiError, match="agente externo") as error:
        default_chat(settings, "grok", "grok-build", [{"role": "user", "content": "só texto"}], threading.Event(), None)
    assert error.value.status == 403

    api = LocalApi(settings, lambda p, m, msgs, c, t: default_chat(settings, p, m, msgs, c, t), token=TOKEN).start()
    try:
        status, body, _raw = _request(api.address[1], "POST", "/v1/chat/completions",
                                      {"model": "grok:grok-build", "messages": [{"role": "user", "content": "oi"}]},
                                      token=TOKEN)
    finally:
        api.stop()
    assert status == 404 and "grok:grok-build" not in {row["id"] for row in api.model_list()["data"]}
    assert started == []


class _FakeStream:
    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        pass


@pytest.mark.parametrize("provider", ["ollama", "lmstudio"])
def test_local_endpoint_reserves_the_gpu_queue_once(monkeypatch, provider):
    """#8: a API local e o provedor reservavam local-gpu duas vezes; a fila não é reentrante e travava."""
    from agent.core import providers
    from agent.core.inference_queue import INFERENCE_QUEUE

    calls = []

    def fake_stream(client, url, payload, headers, attempts=3, timeout=None):
        calls.append(url)
        if url.endswith("/api/chat"):
            return _FakeStream([json.dumps({"message": {"content": "ok"}, "done": True})])
        return _FakeStream([])

    monkeypatch.setattr(providers, "_stream_request", fake_stream)
    monkeypatch.setattr(providers.OpenAICompatProvider, "_consume",
                        staticmethod(lambda response, on_text, on_reasoning, cancel: providers.ChatResult(text="ok")))
    settings = _RealSettings()
    api = LocalApi(settings, lambda p, m, msgs, c, t: default_chat(settings, p, m, msgs, c, t), token=TOKEN)
    cancel = threading.Event()
    out = {}
    worker = threading.Thread(target=lambda: out.setdefault(
        "text", api.complete(provider, "llama", [{"role": "user", "content": "oi"}], cancel, None)), daemon=True)
    try:
        worker.start()
        worker.join(5)
        stuck = worker.is_alive()
        cancel.set()
        worker.join(5)
    finally:
        api._httpd.server_close()
    assert not stuck, "a chamada ficou presa na fila de inferência"
    assert out["text"] == "ok" and len(calls) == 1
    state = INFERENCE_QUEUE.snapshot()["local-gpu"]
    assert state["active"] == 0 and state["waiting"] == 0


def test_local_endpoint_still_serializes_concurrent_requests(monkeypatch):
    from agent.core import providers

    lock, running, peak = threading.Lock(), [0], [0]

    def fake_stream(client, url, payload, headers, attempts=3, timeout=None):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        threading.Event().wait(0.2)
        with lock:
            running[0] -= 1
        return _FakeStream([json.dumps({"message": {"content": "ok"}, "done": True})])

    monkeypatch.setattr(providers, "_stream_request", fake_stream)
    settings = _RealSettings()
    api = LocalApi(settings, lambda p, m, msgs, c, t: default_chat(settings, p, m, msgs, c, t), token=TOKEN)
    results = []
    workers = [threading.Thread(target=lambda: results.append(
        api.complete("ollama", "llama", [{"role": "user", "content": "oi"}], threading.Event(), None)), daemon=True)
        for _ in range(3)]
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
    finally:
        api._httpd.server_close()
    assert results == ["ok", "ok", "ok"]
    assert peak[0] == 1
