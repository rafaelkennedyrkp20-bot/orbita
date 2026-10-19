"""Acesso na rede: desligado não escuta, pareamento expira e não aprova execução."""

import json
from http.client import HTTPConnection

import pytest

from agent.core.remote_access import (
    PairError, Pairing, RemoteServer, allowed_host, lan_address, open_remote,
)


class _Settings:
    def __init__(self, remote_access="off"):
        self.value = remote_access

    def get(self, key, default=None):
        if key == "remote_access":
            return self.value
        return default


def test_off_does_not_bind(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.core.remote_access.RemoteServer",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deveria escutar")),
    )
    assert open_remote(None, Pairing(tmp_path / "vazio.json")) is None
    assert open_remote(_Settings("off"), Pairing(tmp_path / "vazio.json")) is None


def test_refused_addresses_do_not_bind(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agent.core.remote_access.ThreadingHTTPServer",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("não deveria escutar")),
    )
    pairing = Pairing(tmp_path / "aparelhos.json")
    for host in ("0.0.0.0", "8.8.8.8", "localhost"):
        with pytest.raises(PairError, match="recusado"):
            RemoteServer(pairing, lambda *_args: "", host=host)
    assert allowed_host("127.0.0.1")
    assert allowed_host("192.168.1.20")
    assert allowed_host("10.0.0.4")
    assert not allowed_host("0.0.0.0")
    assert not allowed_host("8.8.8.8")
    found = lan_address()
    if found is not None:
        assert allowed_host(found)
        assert found != "0.0.0.0"


def test_code_expires_and_five_failures_burn_it(tmp_path):
    pairing = Pairing(tmp_path / "aparelhos.json")
    pairing.issue("projeto-a", now=1_000, code="123456")
    with pytest.raises(PairError, match="expirado"):
        pairing.pair("123456", now=1_300)
    pairing.issue("projeto-a", now=2_000, code="123456")
    for _ in range(5):
        with pytest.raises(PairError, match="recusado"):
            pairing.pair("000000", now=2_000)
    with pytest.raises(PairError):
        pairing.pair("123456", now=2_000)
    assert pairing.public_devices() == []


def test_success_hides_the_token_and_revoke_survives_reload(tmp_path):
    path = tmp_path / "aparelhos.json"
    pairing = Pairing(path)
    pairing.issue("E:/Projeto", now=10, code="654321")
    granted = pairing.pair("654321", now=10)
    raw = path.read_text(encoding="utf-8")
    stored = json.loads(raw)
    device = stored["devices"][granted["device_id"]]
    assert granted["token"] not in raw
    assert "token" not in device
    assert device["token_hash"]
    again = Pairing(path)
    assert again.authorize(granted["token"])["project"] == "E:/Projeto"
    assert again.revoke(granted["device_id"])
    assert Pairing(path).authorize(granted["token"]) is None
    public = json.dumps(again.public_devices())
    assert granted["token"] not in public
    assert "revoked" in public


def _post(port, path, payload, token=None):
    headers = {"Connection": "close", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", path, body=json.dumps(payload).encode("utf-8"), headers=headers)
        response = conn.getresponse()
        raw = response.read()
    finally:
        conn.close()
    return response.status, json.loads(raw.decode("utf-8"))


def _get(port, path, token):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers={"Authorization": f"Bearer {token}", "Connection": "close"})
        response = conn.getresponse()
        raw = response.read()
    finally:
        conn.close()
    return response.status, json.loads(raw.decode("utf-8"))


def test_remote_chat_stays_inside_the_paired_project(tmp_path):
    calls = []

    def chat(messages, project):
        calls.append((messages, project))
        return "ok"

    pairing = Pairing(tmp_path / "aparelhos.json")
    pairing.issue("alpha", code="111111")
    server = RemoteServer(pairing, chat, host="127.0.0.1", port=0).start()
    try:
        port = server.address[1]
        status, body = _post(port, "/pair", {"code": "111111"})
        assert status == 200 and body["project"] == "alpha"
        token = body["token"]
        assert token not in (tmp_path / "aparelhos.json").read_text(encoding="utf-8")
        status, _body = _post(port, "/v1/chat/completions",
                              {"messages": [{"role": "user", "content": "oi"}], "project": "beta"}, token)
        assert status == 403 and calls == []
        status, _body = _post(port, "/v1/chat/completions",
                              {"messages": [{"role": "user", "content": "oi"}], "tools": [{"name": "run_shell"}]}, token)
        assert status == 403 and calls == []
        status, body = _post(port, "/v1/approve", {"ok": True}, token)
        assert status == 403 and "não aprova" in body["error"] and calls == []
        status, body = _get(port, "/v1/project", token)
        assert status == 200 and body == {"project": "alpha"}
        status, body = _post(port, "/v1/chat/completions",
                             {"messages": [{"role": "user", "content": "oi"}]}, token)
        assert status == 200 and body["project"] == "alpha"
        assert calls == [([{"role": "user", "content": "oi"}], "alpha")]
        assert body["id"].startswith("chatcmpl-")
    finally:
        server.stop()
