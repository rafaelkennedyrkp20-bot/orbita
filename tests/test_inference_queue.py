"""Fila de inferência: concorrência real sem depender de servidor/modelo."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent.core.inference_queue import InferenceQueue, inference_resource
from agent.core.providers import ChatResult, OllamaProvider, OpenAICompatProvider


def test_resource_detects_local_engines_without_serializing_gateways():
    assert inference_resource({"type": "ollama"}) == "local-gpu"
    assert inference_resource({"type": "openai", "base_url": "http://localhost:1234/v1"}) == "local-gpu"
    assert inference_resource({"type": "openai", "base_url": "http://127.0.0.1:11434/v1"}) == "local-gpu"
    assert inference_resource({"type": "openai", "base_url": "http://localhost:20128/v1"}) is None
    assert inference_resource({"type": "openai", "base_url": "https://api.openai.com/v1"}) is None
    assert inference_resource({"type": "ollama", "base_url": "http://server:11434"}) is None
    assert inference_resource({"type": "ollama", "inference_resource": False}) is None
    assert inference_resource({"inference_resource": "gpu-estudio"}) == "gpu-estudio"


def test_serializes_fifo_and_releases_on_exception():
    queue = InferenceQueue()
    entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
    order = []

    def first():
        with queue.slot("gpu") as acquired:
            assert acquired
            entered.set()
            assert release.wait(3)
            order.append("first")
            raise ValueError("erro do modelo")

    def second():
        with queue.slot("gpu", on_event=lambda e: waiting.set() if e["state"] == "waiting" else None) as acquired:
            assert acquired
            order.append("second")

    with ThreadPoolExecutor(2) as pool:
        one = pool.submit(first)
        assert entered.wait(3)
        two = pool.submit(second)
        assert waiting.wait(3)
        assert queue.snapshot()["gpu"]["waiting"] == 1
        assert not two.done()
        release.set()
        with pytest.raises(ValueError, match="erro do modelo"):
            one.result(timeout=3)
        two.result(timeout=3)
    assert order == ["first", "second"]
    stats = queue.snapshot()["gpu"]
    assert stats["active"] == 0 and stats["waiting"] == 0
    assert stats["completed"] == 2 and stats["duration_seconds"] >= 0


def test_waiting_cancel_does_not_wait_for_active_call():
    queue = InferenceQueue()
    cancel, waiting = threading.Event(), threading.Event()
    events = []

    def callback(event):
        events.append(event)
        if event["state"] == "waiting":
            waiting.set()

    def cancelled_call():
        with queue.slot("gpu", cancel=cancel, on_event=callback) as acquired:
            return acquired

    with queue.slot("gpu"):
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(cancelled_call)
            assert waiting.wait(3)
            cancel.set()
            assert future.result(timeout=3) is False
        assert queue.snapshot()["gpu"]["waiting"] == 0
    assert events[-1]["state"] == "cancelled"
    with queue.slot("gpu") as acquired:
        assert acquired


def test_cloud_and_different_resources_remain_parallel():
    queue = InferenceQueue()
    with queue.slot("gpu"):
        with ThreadPoolExecutor(1) as pool:
            def call():
                with queue.slot(None) as cloud, queue.slot("other") as other:
                    return cloud and other
            assert pool.submit(call).result(timeout=3)


def test_provider_queued_cancellation_never_sends_request(monkeypatch):
    from agent.core import inference_queue, providers

    queue = InferenceQueue()
    monkeypatch.setattr(inference_queue, "INFERENCE_QUEUE", queue)
    monkeypatch.setattr(providers, "_shared_http_client", lambda: pytest.fail("não deve abrir HTTP"))
    cancel, waiting = threading.Event(), threading.Event()
    provider = OllamaProvider("ollama", {"type": "ollama"})
    with queue.slot("local-gpu"):
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(provider.chat, "m", [], cancel=cancel,
                                 on_inference_event=lambda e: waiting.set() if e["state"] == "waiting" else None)
            assert waiting.wait(3)
            cancel.set()
            assert future.result(timeout=3).stop_reason == "cancelled"


def test_provider_releases_between_calls_and_preserves_usage(monkeypatch):
    from agent.core import inference_queue, providers

    queue = InferenceQueue()
    monkeypatch.setattr(inference_queue, "INFERENCE_QUEUE", queue)
    monkeypatch.setattr(providers, "_shared_http_client", lambda: object())
    monkeypatch.setattr(providers, "_stream_request", lambda *a, **k: object())
    expected = ChatResult(text="oi", usage={"input_tokens": 4, "output_tokens": 2})
    monkeypatch.setattr(OpenAICompatProvider, "_consume", staticmethod(lambda *a: expected))
    provider = OpenAICompatProvider("lmstudio", {"base_url": "http://localhost:1234/v1"})
    for _ in range(2):
        assert provider.chat("m", []) is expected
        assert queue.snapshot()["local-gpu"]["active"] == 0
    assert expected.usage == {"input_tokens": 4, "output_tokens": 2}
    assert queue.snapshot()["local-gpu"]["completed"] == 2


def test_actual_provider_serializes_local_calls_but_cloud_overlaps(monkeypatch):
    from agent.core import inference_queue, providers

    queue = InferenceQueue()
    monkeypatch.setattr(inference_queue, "INFERENCE_QUEUE", queue)
    monkeypatch.setattr(providers, "_shared_http_client", lambda: object())
    monkeypatch.setattr(providers, "_stream_request", lambda client, url, payload, *a, **k: payload)
    entered, release, waiting = threading.Event(), threading.Event(), threading.Event()

    def consume(payload, *args):
        if payload["model"] == "first":
            entered.set()
            assert release.wait(3)
            raise RuntimeError("falha no stream")
        return ChatResult(text=payload["model"])

    monkeypatch.setattr(OpenAICompatProvider, "_consume", staticmethod(consume))
    local = OpenAICompatProvider("local", {"base_url": "http://localhost:1234/v1"})
    cloud = OpenAICompatProvider("cloud", {"base_url": "https://api.example.com/v1"})
    with ThreadPoolExecutor(3) as pool:
        first = pool.submit(local.chat, "first", [])
        assert entered.wait(3)
        second = pool.submit(local.chat, "second", [],
                             on_inference_event=lambda e: waiting.set() if e["state"] == "waiting" else None)
        try:
            assert waiting.wait(3)
            assert not second.done()
            assert pool.submit(cloud.chat, "cloud", []).result(timeout=3).text == "cloud"
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="falha no stream"):
            first.result(timeout=3)
        assert second.result(timeout=3).text == "second"
    assert queue.snapshot()["local-gpu"]["active"] == 0


def test_local_parent_releases_slot_before_delegation_and_compaction(brain, monkeypatch):
    from agent.core import agent_loop, inference_queue, providers
    from agent.core.agent_loop import AgentSession, SUMMARY_PROMPT

    queue = InferenceQueue()
    monkeypatch.setattr(inference_queue, "INFERENCE_QUEUE", queue)
    monkeypatch.setattr(providers, "_shared_http_client", lambda: object())
    monkeypatch.setattr(providers, "_stream_request", lambda client, url, payload, *a, **k: payload)
    local = OpenAICompatProvider("local", {"base_url": "http://localhost:1234/v1"})
    monkeypatch.setattr(agent_loop, "get_provider", lambda *args: local)

    def consume(payload, *args):
        assert queue.snapshot()["local-gpu"]["active"] == 1
        if payload["messages"][0]["content"] == SUMMARY_PROMPT:
            return ChatResult(text="resumo")
        last = payload["messages"][-1]
        if last.get("content") == "delegue":
            return ChatResult(tool_calls=[{"id": "d", "name": "delegate_task", "arguments": {
                "tasks": [{"task": "parcela independente", "profile": "programador"}]}}])
        return ChatResult(text="feito")

    monkeypatch.setattr(OpenAICompatProvider, "_consume", staticmethod(consume))
    brain.settings.set("permission_mode", "livre", save=False)
    events = []
    session = AgentSession(brain, brain.profiles.get("geral"), "local", "modelo",
                           events=lambda name, data: events.append((name, data)))
    session.messages = [{"role": "user", "content": "antigo"}, {"role": "assistant", "content": "ok"}]
    assert session._summarize(session.messages) == "resumo"
    session.messages.clear()
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(session.run, "delegue")
        try:
            assert future.result(timeout=5) == "feito"
        finally:
            session.cancel.set()
    assert queue.snapshot()["local-gpu"]["completed"] == 4
    assert any(name == "inference_queue" and data["state"] == "running" for name, data in events)
    assert any(name == "inference_queue" and data["agent"] != "principal" for name, data in events)


def test_precancelled_and_failed_event_callbacks_leave_queue_usable():
    queue = InferenceQueue()
    cancel = threading.Event()
    cancel.set()
    with queue.slot("gpu", cancel=cancel) as acquired:
        assert not acquired

    def broken_callback(event):
        if event["state"] == "running":
            raise RuntimeError("callback falhou")

    with pytest.raises(RuntimeError, match="callback falhou"):
        with queue.slot("gpu", on_event=broken_callback):
            pytest.fail("não deve chegar ao corpo")
    with queue.slot("gpu") as acquired:
        assert acquired
    assert queue.snapshot()["gpu"]["active"] == 0
