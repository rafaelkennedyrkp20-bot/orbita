"""Trabalhos em segundo plano. Fechar o app não repete o que ficou pelo meio.

Estado `waiting` não é `running`. Parar cancela. Um trabalho que estava
rodando ou na fila quando o processo abre de novo fica `interrupted`.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from agent.core.config import DATA_DIR

OUTPUT_LIMIT = 8000
_OPEN = {"waiting", "running"}
_STORE: "JobStore | None" = None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class JobStore:
    def __init__(self, path: Path, runner=None, on_change=None):
        self.path = Path(path)
        self.runner = runner
        self.on_change = on_change
        self._lock = threading.RLock()
        self._cancel: dict[str, threading.Event] = {}
        self._jobs = self._load()

    def _load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            return []
        changed = False
        for job in jobs:
            if isinstance(job, dict) and job.get("state") in _OPEN:
                job["state"] = "interrupted"
                job["note"] = "O app fechou. Este trabalho não foi repetido."
                job["updated"] = _now()
                changed = True
        if changed:
            self._write(jobs)
        return [job for job in jobs if isinstance(job, dict)]

    def _write(self, jobs: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"jobs": jobs}, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)
        callback = self.on_change
        if callback is not None:
            try:
                callback()
            except Exception:
                pass

    def _find(self, job_id: str) -> dict | None:
        for job in self._jobs:
            if job.get("id") == job_id:
                return job
        return None

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(job) for job in self._jobs]

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._find(job_id)
            return dict(job) if job else None

    def start(self, prompt: str, *, project: str = "", conversation_id: str = "", autostart: bool = True) -> dict:
        job = {
            "id": uuid.uuid4().hex[:12],
            "prompt": (prompt or "")[:4000],
            "project": project,
            "conversation_id": conversation_id,
            "state": "waiting",
            "output": "",
            "error": "",
            "note": "",
            "cost_usd": None,
            "tokens": None,
            "created": _now(),
            "updated": _now(),
        }
        cancel = threading.Event()
        with self._lock:
            self._jobs.append(job)
            self._cancel[job["id"]] = cancel
            self._write(self._jobs)
            snapshot = dict(job)
        if autostart:
            threading.Thread(target=self._run, args=(job["id"],), name=f"job-{job['id']}", daemon=True).start()
        return snapshot

    def _run(self, job_id: str) -> None:
        cancel = self._cancel.get(job_id) or threading.Event()
        with self._lock:
            job = self._find(job_id)
            if job is None or job.get("state") != "waiting" or cancel.is_set():
                if job and job.get("state") == "waiting":
                    job["state"] = "cancelled"
                    job["note"] = "Parado antes de começar."
                    job["updated"] = _now()
                    self._write(self._jobs)
                return
            job["state"] = "running"
            job["updated"] = _now()
            self._write(self._jobs)
            snapshot = dict(job)
        text, cost, tokens, error = "", None, None, ""
        state = "done"
        try:
            result = self.runner(snapshot, cancel) if self.runner else ""
            if isinstance(result, dict):
                text = str(result.get("output") or "")
                cost = result.get("cost_usd")
                tokens = result.get("tokens")
            else:
                text = str(result or "")
            if cancel.is_set():
                state = "cancelled"
        except Exception as error_obj:
            state = "cancelled" if cancel.is_set() else "error"
            error = str(error_obj)
        with self._lock:
            job = self._find(job_id)
            if job is None:
                return
            if job.get("state") in {"cancelled", "interrupted"}:
                if text and not job.get("output"):
                    job["output"] = text[:OUTPUT_LIMIT]
                self._write(self._jobs)
                return
            job["state"] = state
            job["output"] = text[:OUTPUT_LIMIT]
            job["error"] = error[:500]
            job["cost_usd"] = cost if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
            job["tokens"] = tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None
            job["updated"] = _now()
            self._write(self._jobs)

    def stop(self, job_id: str) -> None:
        cancel = self._cancel.get(job_id)
        if cancel:
            cancel.set()
        with self._lock:
            job = self._find(job_id)
            if job and job.get("state") in _OPEN:
                job["state"] = "cancelled"
                job["note"] = "Parado."
                job["updated"] = _now()
                self._write(self._jobs)

    def shutdown(self) -> None:
        """O processo está fechando. Não deixa um trabalho aberto parecer concluído."""
        for cancel in self._cancel.values():
            cancel.set()
        with self._lock:
            for job in self._jobs:
                if job.get("state") in _OPEN:
                    job["state"] = "interrupted"
                    job["note"] = "O app fechou. Este trabalho não foi repetido."
                    job["updated"] = _now()
            self._write(self._jobs)


def job_session(brain, job: dict, provider: str, model: str, *, cancel, events=None, approve=None):
    """Sessão do trabalho presa ao projeto salvo nele. Trocar de projeto depois não muda o destino."""
    from agent.core.agent_loop import AgentSession

    project = (job.get("project") or "").strip()
    folder = Path(project).expanduser() if project else None
    if folder is None or not folder.is_dir():
        raise ValueError(f"O projeto deste trabalho não existe mais: {project or '(nenhum)'}. Nada foi feito.")
    profile = replace(brain.profile, workspace=str(folder.resolve()))   # cópia: set_workspace não a alcança
    return AgentSession(brain, profile, provider, model, events=events, approve=approve,
                        label="tarefa", cancel=cancel)


def get_store(runner=None) -> JobStore:
    global _STORE
    if _STORE is None:
        _STORE = JobStore(DATA_DIR / "jobs.json", runner=runner)
    elif runner is not None and _STORE.runner is None:
        _STORE.runner = runner
    return _STORE
