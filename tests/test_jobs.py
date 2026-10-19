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
