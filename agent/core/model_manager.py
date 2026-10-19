"""Downloads do Ollama: um job por modelo, cancelável, sem falso concluído.

O contrato do Ollama não oferece pausa. Cancelar fecha a conexão. Se o
Órbita fecha no meio, o job reabre como interrompido — nunca como pronto.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from pathlib import Path

import httpx

from agent.core.config import DATA_DIR

_NAME = re.compile(r"^[A-Za-z0-9_.:/@+-]{1,200}$")
_MANAGER: "ModelManager | None" = None
_MANAGER_LOCK = threading.Lock()


def valid_model_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME.fullmatch(name) or ".." in name or name.startswith(("/", "\\")):
        raise ValueError("Nome de modelo inválido. Use o nome do Ollama, sem espaços.")
    return name


def get_manager() -> "ModelManager":
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = ModelManager(DATA_DIR / "model_jobs.json")
        return _MANAGER


class ModelManager:
    def __init__(self, store: Path | None = None):
        self.path = Path(store) if store else None
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._cancels: dict[str, threading.Event] = {}
        self._streams: dict[str, object] = {}
        self._load()

    def jobs(self) -> list[dict]:
        with self._lock:
            return [dict(job) for job in self._jobs.values()]

    def job(self, model: str) -> dict | None:
        with self._lock:
            found = self._jobs.get(model)
            return dict(found) if found else None

    def start_pull(self, base_url: str, model: str, on_event=None, *, opener=None) -> dict:
        model = valid_model_name(model)
        with self._lock:
            current = self._jobs.get(model)
            if current and current.get("state") == "running":
                return dict(current)
            cancel = threading.Event()
            job = {
                "id": uuid.uuid4().hex[:12],
                "model": model,
                "state": "running",
                "message": "Conectando ao Ollama…",
                "completed": 0,
                "total": 0,
            }
            self._jobs[model] = job
            self._cancels[model] = cancel
            self._save_locked()
            snapshot = dict(job)
        threading.Thread(
            target=self._run, name=f"ollama-pull-{model}", daemon=True,
            args=(base_url, model, cancel, on_event, opener),
        ).start()
        return snapshot

    def cancel(self, model: str) -> bool:
        with self._lock:
            cancel = self._cancels.get(model)
            stream = self._streams.get(model)
        if cancel is None:
            return False
        cancel.set()
        close = getattr(stream, "close", None)
        if close:
            try:
                close()
            except Exception:
                pass
        return True

    def _run(self, base_url: str, model: str, cancel: threading.Event, on_event, opener):
        opener = opener or _open_pull
        state, message = "error", "Falha ao baixar."
        completed = total = 0
        try:
            with opener(base_url, model) as response:
                self._remember_stream(model, response)
                try:
                    for raw in response.iter_lines():
                        if cancel.is_set():
                            state, message = "cancelled", "Download cancelado. Nada foi marcado como pronto."
                            break
                        if not raw or not str(raw).strip():
                            continue
                        try:
                            item = json.loads(raw)
                        except json.JSONDecodeError:
                            state, message = "error", "O Ollama devolveu uma linha inválida."
                            break
                        if not isinstance(item, dict):
                            state, message = "error", "Resposta inesperada do Ollama."
                            break
                        if item.get("error"):
                            state, message = "error", str(item["error"])[:300]
                            break
                        completed = int(item.get("completed") or completed or 0)
                        total = int(item.get("total") or total or 0)
                        message = str(item.get("status") or message)[:180]
                        self._update(model, state="running", message=message, completed=completed, total=total)
                        self._emit(on_event, model, done=False)
                    else:
                        if cancel.is_set():
                            state, message = "cancelled", "Download cancelado. Nada foi marcado como pronto."
                        else:
                            state, message = "done", "concluído"
                finally:
                    self._forget_stream(model)
        except Exception as error:
            if cancel.is_set():
                state, message = "cancelled", "Download cancelado. Nada foi marcado como pronto."
            else:
                state, message = "error", f"Falha ao baixar {model}: {error}"
        self._update(model, state=state, message=message, completed=completed, total=total or completed)
        self._emit(on_event, model, done=True)
        with self._lock:
            self._cancels.pop(model, None)

    def _remember_stream(self, model, response):
        with self._lock:
            self._streams[model] = response

    def _forget_stream(self, model):
        with self._lock:
            self._streams.pop(model, None)

    def _update(self, model, **fields):
        with self._lock:
            job = self._jobs.setdefault(model, {"model": model})
            job.update(fields)
            self._save_locked()

    def _emit(self, on_event, model, *, done: bool):
        if not on_event:
            return
        job = self.job(model) or {"model": model, "state": "error", "message": ""}
        payload = {
            "model": model,
            "status": job.get("message") or "",
            "completed": job.get("completed") or 0,
            "total": job.get("total") or 0,
            "done": done,
            "state": job.get("state"),
        }
        if job.get("state") == "error":
            payload["error"] = job.get("message") or "Falha ao baixar."
        elif job.get("state") == "cancelled":
            payload["cancelled"] = True
        try:
            on_event(payload)
        except Exception:
            pass

    def _load(self):
        if not self.path or not self.path.exists():
            return
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return
        if not isinstance(stored, list):
            return
        changed = False
        for item in stored:
            if not isinstance(item, dict) or not isinstance(item.get("model"), str):
                continue
            job = {
                "id": str(item.get("id") or uuid.uuid4().hex[:12]),
                "model": item["model"],
                "state": item.get("state") or "error",
                "message": str(item.get("message") or "")[:300],
                "completed": int(item.get("completed") or 0),
                "total": int(item.get("total") or 0),
            }
            if job["state"] == "running":
                job["state"] = "interrupted"
                job["message"] = "O download parou porque o Órbita fechou. Comece de novo; nada foi marcado como pronto."
                changed = True
            self._jobs[job["model"]] = job
        if changed:
            self._save_locked()

    def _save_locked(self):
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(list(self._jobs.values()), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            pass


def _open_pull(base_url: str, model: str):
    client = httpx.Client(trust_env=False, follow_redirects=False, timeout=None)
    stream = client.stream("POST", base_url.rstrip("/") + "/api/pull", json={"model": model, "stream": True})
    response = stream.__enter__()

    class _Bound:
        def __enter__(self):
            return response

        def __exit__(self, *args):
            stream.__exit__(*args)
            client.close()

        def iter_lines(self):
            return response.iter_lines()

        def close(self):
            response.close()
            client.close()

    return _Bound()


def ollama_action(base_url: str, model: str, action: str, *, client=None) -> str:
    """Descarrega da memória ou remove o modelo. Não apaga arquivos de outro programa."""
    model = valid_model_name(model)
    if action not in {"unload", "delete"}:
        raise ValueError("Ação desconhecida.")
    owned = client is None
    client = client or httpx.Client(trust_env=False, follow_redirects=False, timeout=60)
    try:
        if action == "unload":
            response = client.post(base_url.rstrip("/") + "/api/generate",
                                   json={"model": model, "keep_alive": 0})
            if response.status_code >= 400:
                raise RuntimeError(f"Ollama recusou descarregar ({response.status_code}).")
            return f"{model} descarregado da memória."
        response = client.request("DELETE", base_url.rstrip("/") + "/api/delete", json={"model": model})
        if response.status_code >= 400:
            raise RuntimeError(f"Ollama recusou remover ({response.status_code}).")
        return f"{model} removido do Ollama."
    finally:
        if owned:
            client.close()
