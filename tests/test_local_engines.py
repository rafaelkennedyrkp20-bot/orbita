"""Descoberta local valida o protocolo, sem alterar a seleção do usuário."""

import threading

import httpx
import pytest

from agent.core.local_engines import detect_local_engines, probe_engine


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("kind,payload,models,status", [
    ("ollama", {"models": [{"name": "qwen3:8b"}]}, ["qwen3:8b"], "available"),
    ("openai", {"data": [{"id": "local/model"}]}, ["local/model"], "available"),
    ("ollama", {"models": []}, [], "no_models"),
    ("openai", {"data": []}, [], "no_models"),
    ("openai", {"message": "outro programa"}, [], "incompatible"),
    ("ollama", {"models": [{"id": "errado"}]}, [], "incompatible"),
])
def test_protocol_validation(kind, payload, models, status):
    cfg = {"type": kind, "base_url": "http://127.0.0.1:1234/v1"}
    with client_for(lambda r: httpx.Response(200, json=payload)) as client:
        result = probe_engine("local", cfg, client=client)
    assert result["status"] == status
    assert result["models"] == models


def test_probe_uses_correct_route_and_does_not_send_credentials():
    seen = []

    def handler(request):
        seen.append((request.url.path, request.headers.get("authorization")))
        return httpx.Response(401)

    with client_for(handler) as client:
        row = probe_engine("ollama", {"type": "ollama", "base_url": "http://localhost:11434/v1",
                                      "api_key": "segredo"}, client=client)
    assert seen == [("/api/tags", None)]
    assert row["status"] == "auth_required"
    assert "segredo" not in str(row)


def test_timeout_has_actionable_status():
    def handler(request):
        raise httpx.ReadTimeout("sem resposta", request=request)

    with client_for(handler) as client:
        row = probe_engine("lmstudio", {"type": "openai", "base_url": "http://127.0.0.1:1234/v1"}, client=client)
    assert row["status"] == "offline"
    assert row["message"]


def test_scan_never_contacts_remote_or_follows_redirects():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.com"})

    providers = {
        "cloud": {"type": "openai", "base_url": "https://api.example.com/v1"},
        "local": {"type": "openai", "base_url": "http://127.0.0.1:5555/v1"},
    }
    with client_for(handler) as client:
        rows = detect_local_engines(providers, client=client)
    assert len(rows) == 1 and rows[0]["status"] == "incompatible"
    assert seen == ["http://127.0.0.1:5555/v1/models"]


@pytest.mark.parametrize("url", ["http://127.0.0.1.evil.test/v1", "http://user:password@localhost/v1", "file:///tmp/x"])
def test_untrusted_urls_are_not_probed(url):
    with client_for(lambda r: pytest.fail("URL indevida foi consultada")) as client:
        assert detect_local_engines({"x": {"type": "openai", "base_url": url}}, client=client) == []


def test_cancelled_scan_makes_no_requests():
    cancel = threading.Event()
    cancel.set()
    with client_for(lambda r: pytest.fail("sonda após cancelar")) as client:
        assert detect_local_engines({"x": {"type": "openai", "base_url": "http://[::1]:1234/v1"}},
                                    cancel=cancel, client=client) == []


def test_html_and_oversize_responses_are_not_valid_engines():
    for response in (httpx.Response(200, text="<html>Outra página</html>"),
                     httpx.Response(200, content=b" " * 70000)):
        with client_for(lambda r: response) as client:
            row = probe_engine("x", {"type": "openai", "base_url": "http://localhost:1234/v1"}, client=client)
        assert row["status"] == "incompatible"
