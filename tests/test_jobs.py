"""Trabalhos: aguardando não é executando, parar cancela e reinício não repete."""

import json
import threading
import time

from agent.core.jobs import OUTPUT_LIMIT, JobStore


def test_restart_marks_open_jobs_interrupted_and_does_not_run_them(tmp_path):
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps({"jobs": [
        {"id": "aaaabbbbcccc", "state": "running", "prompt": "envie o e-mail", "output": ""},
        {"id": "dddddddddddd", "state": "waiting", "prompt": "ainda não", "output": ""},
        {"id": "eeeeeeeeeeee", "state": "done", "prompt": "pronto", "output": "ok"},
    ]}), encoding="utf-8")
    called = []
    store = JobStore(path, runner=lambda job, cancel: called.append(job))
    assert called == []
    assert store.get("aaaabbbbcccc")["state"] == "interrupted"
    assert store.get("dddddddddddd")["state"] == "interrupted"
    assert "não foi repetido" in store.get("aaaabbbbcccc")["note"]
    assert store.get("eeeeeeeeeeee")["state"] == "done"


def test_waiting_stop_never_becomes_running(tmp_path):
    store = JobStore(tmp_path / "jobs.json", runner=lambda job, cancel: "não devia")
    job = store.start("oi", project="E:/proj", autostart=False)
    assert store.get(job["id"])["state"] == "waiting"
    assert store.get(job["id"])["project"] == "E:/proj"
    store.stop(job["id"])
    assert store.get(job["id"])["state"] == "cancelled"


def test_stop_cancels_a_running_job_and_caps_output(tmp_path):
    started = threading.Event()

    def runner(job, cancel):
        started.set()
        while not cancel.is_set():
            time.sleep(0.01)
        return "x" * (OUTPUT_LIMIT + 50)

    store = JobStore(tmp_path / "jobs.json", runner=runner)
    job = store.start("trabalha")
    assert started.wait(2)
    assert store.get(job["id"])["state"] == "running"
    store.stop(job["id"])
    deadline = time.time() + 2
    while time.time() < deadline and not store.get(job["id"])["output"]:
        time.sleep(0.02)
    saved = store.get(job["id"])
    assert saved["state"] == "cancelled"
    assert saved["output"] == "x" * OUTPUT_LIMIT
    assert saved["cost_usd"] is None


def test_stop_between_runner_start_and_session_run_prevents_all_calls(brain, monkeypatch, tmp_path):
    """#18: AgentSession.run limpava o cancelamento do job; parado antes do início, o agente ainda gravava."""
    import agent.core.agent_loop as loop
    from agent.core.agent_loop import AgentSession
    from agent.core.providers import ChatResult

    calls = []

    class Writer:
        supports_native_tools = True

        def supports_vision(self, model):
            return True

        def chat(self, model, messages, tools=None, **kwargs):
            calls.append(model)
            if not any(m["role"] == "tool" for m in messages):
                return ChatResult(tool_calls=[{"id": "c1", "name": "write_file",
                                               "arguments": {"path": str(tmp_path / "marcador.txt"), "content": "x"}}])
            return ChatResult(text="feito")

    monkeypatch.setattr(loop, "get_provider", lambda name, settings: Writer())
    brain.settings.set("permission_mode", "livre", save=False)
    entered, release = threading.Event(), threading.Event()

    def runner(job, cancel):
        session = AgentSession(brain, brain.profiles.get("geral"), "fake", "m1", label="tarefa", cancel=cancel)
        entered.set()
        release.wait(2)
        return {"output": session.run(job["prompt"]), "tokens": session.turn_tokens}

    store = JobStore(tmp_path / "jobs.json", runner=runner)
    job = store.start("grave o marcador")
    assert entered.wait(2)
    store.stop(job["id"])
    release.set()
    deadline = time.time() + 3
    while time.time() < deadline and threading.active_count() > 1 and not store.get(job["id"])["output"]:
        time.sleep(0.02)
    assert store.get(job["id"])["state"] == "cancelled"
    assert calls == [] and not (tmp_path / "marcador.txt").exists()
