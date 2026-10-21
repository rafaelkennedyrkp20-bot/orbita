"""Fila remota: limites, repetição e permissões, sem serviços externos."""

import json
import threading
from types import SimpleNamespace

import pytest
import requests

from agent.core import prompt_polling as polling


class Response:
    status_code = 200

    def __init__(self, payload, *, raw=None):
        self.raw = json.dumps(payload).encode() if raw is None else raw
        self.headers = {"Content-Length": str(len(self.raw))}
        self.closed = False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.raw

    def close(self):
        self.closed = True


class Brain:
    def __init__(self):
        self.settings = {"permission_mode": "auto"}
        self.calls = []
        self.new = 0
        self.stopped = threading.Event()
        self.session = None

    def new_conversation(self):
        self.new += 1

    def run_turn(self, prompt, *, approve, events):
        self.session = SimpleNamespace(cancel=threading.Event())
        self.calls.append((prompt, approve))
        events("text", {"text": "feito"})
        return "feito"

    def stop(self):
        self.stopped.set()
        if self.session:
            self.session.cancel.set()


def test_once_accepts_cassandra_envelope_and_deduplicates_completed_items(monkeypatch):
    brain = Brain()
    response = Response({"body": json.dumps([
        {"id": "a", "prompt": "um"}, {"id": "a", "prompt": "um"},
        {"prompt": "dois"}, {"prompt": "dois"}, {}, "inválido"])})
    seen = []

    def get(url, **kwargs):
        seen.append((url, kwargs))
        return response

    monkeypatch.setattr(requests, "get", get)
    approve = lambda _request: "no"
    count = polling.run_polling(brain, "https://queue.example/agent/pending-prompts", 1,
                                once=True, api_key="segredo", approve=approve)
    assert count == 2 and brain.new == 2
    assert brain.calls == [("um", approve), ("dois", approve)]
    assert brain.settings["permission_mode"] == "auto"
    assert seen[0][1]["headers"]["Authorization"] == "Bearer segredo"
    assert seen[0][1]["allow_redirects"] is False and response.closed


@pytest.mark.parametrize("delay", [0, -1, float("nan"), float("inf"), .49])
def test_invalid_intervals_fail_before_network(monkeypatch, delay):
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: pytest.fail("rede"))
    with pytest.raises(ValueError, match="intervalo"):
        polling.run_polling(Brain(), "https://queue.example", delay, once=True)


@pytest.mark.parametrize("url", ["file:///x", "https://user:pass@queue.example", "https://", "http://x:bad", "https://x/#fragment"])
def test_invalid_endpoints_fail_before_network(monkeypatch, url):
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: pytest.fail("rede"))
    with pytest.raises(ValueError):
        polling.run_polling(Brain(), url, 1, once=True)


def test_local_only_blocks_even_before_fetching_queue(monkeypatch):
    brain = Brain()
    brain.settings["execution_policy"] = "local_only"
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: pytest.fail("rede"))
    with pytest.raises(polling.PollingError, match="somente local"):
        polling.run_polling(brain, "https://queue.example", 1, once=True)


def test_failure_is_retried_next_cycle_but_success_is_not(monkeypatch):
    brain = Brain()
    stop = threading.Event()
    cycle = 0

    def get(*_args, **_kwargs):
        nonlocal cycle
        cycle += 1
        if cycle == 3:
            stop.set()
        return Response([{"id": "a", "prompt": "tarefa"}])

    original = brain.run_turn

    def turn(prompt, *, approve, events):
        answer = original(prompt, approve=approve, events=events)
        if len(brain.calls) == 1:
            events("error", {"message": "provedor fora do ar"})
        return answer

    brain.run_turn = turn
    monkeypatch.setattr(requests, "get", get)
    assert polling.run_polling(brain, "https://queue.example", .5, stop=stop) == 1
    assert len(brain.calls) == 2 and cycle == 3


def test_oversized_response_is_closed_without_execution(monkeypatch):
    brain = Brain()
    response = Response([])
    response.headers["Content-Length"] = str(polling.MAX_RESPONSE_BYTES + 1)
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: response)
    with pytest.raises(polling.PollingError, match="limite"):
        polling.run_polling(brain, "https://queue.example", .5, once=True)
    assert not brain.calls and response.closed


def test_exception_does_not_include_authentication_data(monkeypatch, caplog):
    def fail(*_args, **_kwargs):
        raise requests.RequestException("Authorization Bearer segredo")

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(polling.PollingError) as error:
        polling.run_polling(Brain(), "https://queue.example", .5, once=True, api_key="segredo")
    assert "segredo" not in str(error.value) + caplog.text


def test_stop_during_turn_reaches_brain_without_waiting_for_delay(monkeypatch):
    brain, stop = Brain(), threading.Event()
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: Response([{"prompt": "longa"}]))

    def turn(_prompt, *, approve, events):
        stop.set()
        assert brain.stopped.wait(2)
        return "interrompido"

    brain.run_turn = turn
    assert polling.run_polling(brain, "https://queue.example", 60, stop=stop, once=True) == 0


def test_default_approval_callback_denies_execution(monkeypatch):
    brain = Brain()
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: Response([{"prompt": "teste"}]))
    assert polling.run_polling(brain, "https://queue.example", .5, once=True) == 1
    assert brain.calls[0][1]({"tool": "run_shell", "risk": "exec"}) == "no"


def test_failed_cassandra_envelope_does_not_execute_body(monkeypatch):
    brain = Brain()
    response = Response({"ok": False, "body": '[{"prompt":"não executar"}]'})
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: response)
    with pytest.raises(polling.PollingError, match="indisponível"):
        polling.run_polling(brain, "https://queue.example", .5, once=True)
    assert brain.calls == []


def test_response_without_content_length_still_has_streaming_limit(monkeypatch):
    brain = Brain()
    response = Response([], raw=b"x" * (polling.MAX_RESPONSE_BYTES + 1))
    response.headers.clear()
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: response)
    with pytest.raises(polling.PollingError, match="limite"):
        polling.run_polling(brain, "https://queue.example", .5, once=True)
    assert brain.calls == [] and response.closed
