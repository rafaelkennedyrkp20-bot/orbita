"""Alternativas de busca sem depender de rede nem de chaves reais."""

import requests

from agent.actions import web_search as search


class Search:
    rows = []
    error = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def text(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return self.rows


def configure(monkeypatch, *, rows=(), error=None):
    monkeypatch.setattr(search, "DDGS", Search)
    monkeypatch.setattr(Search, "rows", rows)
    monkeypatch.setattr(Search, "error", error)
    for key in ("BRAVE_SEARCH_API_KEY", "GOOGLE_SEARCH_API_KEY", "GOOGLE_SEARCH_CX"):
        monkeypatch.delenv(key, raising=False)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def test_ddgs_success_never_uses_paid_alternatives(monkeypatch):
    configure(monkeypatch, rows=[{"title": "Um", "href": "https://a.example", "body": "A"}] * 2)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "segredo")
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("rede")))
    assert search._search_results("teste", 3, "br-pt") == [
        {"title": "Um", "href": "https://a.example", "body": "A"}]


def test_brave_fallback_on_ddgs_error_normalizes_and_limits(monkeypatch):
    configure(monkeypatch, error=RuntimeError("DDGS fora do ar"))
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-segredo")
    seen = []

    def get(url, **kwargs):
        seen.append((url, kwargs))
        return Response({"web": {"results": [
            {"title": str(i), "url": "https://a.example/" + str(i), "description": "texto"}
            for i in range(5)]}})

    monkeypatch.setattr(requests, "get", get)
    rows = search._search_results("teste", 2, "br-pt")
    assert len(rows) == 2 and rows[0]["href"] == "https://a.example/0"
    assert rows[0]["body"] == "texto"
    assert seen[0][0] == "https://api.search.brave.com/res/v1/web/search"
    assert seen[0][1]["headers"]["X-Subscription-Token"] == "brave-segredo"
    assert seen[0][1]["params"]["count"] == 2
    assert seen[0][1]["timeout"] > 0


def test_google_fallback_after_empty_ddgs_and_brave(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-segredo")
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "google-segredo")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "motor")
    seen = []

    def get(url, **kwargs):
        seen.append((url, kwargs))
        return Response({"web": {"results": []}} if "brave" in url else {
            "items": [{"title": "Google", "link": "https://g.example", "snippet": "resultado"}]})

    monkeypatch.setattr(requests, "get", get)
    assert search._search_results("termo", 30, "br-pt") == [
        {"title": "Google", "href": "https://g.example", "body": "resultado"}]
    assert seen[0][1]["params"]["count"] == 20
    assert seen[1][1]["params"] == {"key": "google-segredo", "cx": "motor", "q": "termo", "num": 10}


def test_missing_credentials_do_not_request_alternatives(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("rede")))
    assert search._search_results("teste", 5, "br-pt") == []


def test_provider_exception_cannot_leak_secret_to_response_or_log(monkeypatch, caplog):
    configure(monkeypatch, error=RuntimeError("DDGS"))
    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "google-segredo")
    monkeypatch.setenv("GOOGLE_SEARCH_CX", "motor")
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: (_ for _ in ()).throw(
        requests.RequestException("https://google.example?key=google-segredo")))
    result = search.web_search("teste")
    assert "indisponíveis" in result
    assert "google-segredo" not in result + caplog.text
