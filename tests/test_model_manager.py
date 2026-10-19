"""Fila de download do Ollama: um job, cancelamento e retomada após fechar o app."""

import json
import threading
import time

import httpx
import pytest

from agent.core.model_manager import ModelManager, ollama_action, valid_model_name


class Script:
    def __init__(self, lines):
        self.lines = lines
        self.closed = False
        self.started = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_lines(self):
        self.started.set()
        for line in self.lines:
            if self.closed:
                return
            yield line

    def close(self):
        self.closed = True


def wait_done(events, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if any(event.get("done") for event in list(events)):
            return True
        time.sleep(0.02)
    return False


def test_rejects_bad_names():
    with pytest.raises(ValueError):
        valid_model_name("../etc/passwd")
    with pytest.raises(ValueError):
        valid_model_name("nome com espaço")


def test_second_pull_does_not_start_another_download(tmp_path):
    gate = threading.Event()
    calls = []
    entered = threading.Event()

    class Hold(Script):
        def iter_lines(self):
            entered.set()
            assert gate.wait(3)
            if self.closed:
                return
            yield from self.lines

    def opener(base, model):
        calls.append(model)
        return Hold(['{"status":"success","completed":1,"total":1}'])

    done = []
    manager = ModelManager(tmp_path / "jobs.json")
    first = manager.start_pull(
        "http://127.0.0.1:11434", "qwen3:1.7b",
        lambda event: done.append(event), opener=opener)
    assert entered.wait(3)
    second = manager.start_pull("http://127.0.0.1:11434", "qwen3:1.7b", opener=opener)
    assert second["id"] == first["id"]
    assert calls == ["qwen3:1.7b"]
    gate.set()
    assert wait_done(done)
    assert manager.job("qwen3:1.7b")["state"] == "done"


def test_cancel_is_not_reported_as_success(tmp_path):
    started = threading.Event()

    class Block(Script):
        def __init__(self):
            super().__init__([])
            self.flag = started

        def iter_lines(self):
            self.flag.set()
            while not self.closed:
                time.sleep(0.02)
            return
            yield ""

    def opener(base, model):
        return Block()

    seen = []
    manager = ModelManager(tmp_path / "jobs.json")
    manager.start_pull("http://127.0.0.1:11434", "qwen3:4b", seen.append, opener=opener)
    assert started.wait(3)
    assert manager.cancel("qwen3:4b")
    assert wait_done(seen)
    job = manager.job("qwen3:4b")
    assert job["state"] == "cancelled"
    assert seen[-1].get("cancelled") is True
    assert seen[-1].get("state") != "done"


def test_restart_marks_running_job_interrupted(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps([{
        "id": "abc", "model": "gemma3:4b", "state": "running",
        "message": "baixando", "completed": 3, "total": 9,
    }]), encoding="utf-8")
    manager = ModelManager(path)
    job = manager.job("gemma3:4b")
    assert job["state"] == "interrupted"
    assert "pronto" in job["message"]
    again = ModelManager(path)
    assert again.job("gemma3:4b")["state"] == "interrupted"


def test_ollama_error_is_not_success(tmp_path):
    def opener(base, model):
        return Script(['{"error":"modelo inexistente"}'])

    seen = []
    manager = ModelManager(tmp_path / "jobs.json")
    manager.start_pull("http://127.0.0.1:11434", "nope:latest", seen.append, opener=opener)
    assert wait_done(seen)
    assert manager.job("nope:latest")["state"] == "error"
    assert seen[-1]["done"] is True and "error" in seen[-1]


def test_unload_and_delete_use_ollama_routes():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, json.loads(request.content.decode())))
        return httpx.Response(200, json={"ok": True})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert "descarregado" in ollama_action("http://127.0.0.1:11434", "qwen3:1.7b", "unload", client=client)
        assert "removido" in ollama_action("http://127.0.0.1:11434", "qwen3:1.7b", "delete", client=client)
    assert seen[0][0:2] == ("POST", "/api/generate")
    assert seen[0][2]["keep_alive"] == 0
    assert seen[1][0:2] == ("DELETE", "/api/delete")
