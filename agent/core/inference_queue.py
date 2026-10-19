"""Uma inferência por recurso local; ferramentas e serviços de nuvem ficam livres."""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from urllib.parse import urlsplit


def inference_resource(cfg: dict, name: str = "") -> str | None:
    """Só motores locais conhecidos usam a GPU compartilhada automaticamente.

    `inference_resource` permite agrupar outros motores na mesma placa ou desligar
    a coordenação com False/"". Um gateway local pode servir modelos de nuvem.
    """
    if "inference_resource" in cfg:
        value = cfg["inference_resource"]
        return value.strip() if isinstance(value, str) and value.strip() else None
    kind = cfg.get("type", "openai")
    default = "http://127.0.0.1:11434" if kind == "ollama" else ""
    try:
        endpoint = urlsplit(cfg.get("base_url") or default)
        local = endpoint.hostname in {"localhost", "127.0.0.1", "::1"}
        known = kind == "ollama" or name.lower() == "lmstudio" or endpoint.port in {11434, 1234}
    except (ValueError, TypeError):
        return None
    return "local-gpu" if local and known else None


class InferenceQueue:
    """Fila FIFO por chamada, sem identidade de sessão e sem lock reentrante."""

    def __init__(self):
        self._condition = threading.Condition()
        self._resources: dict[str, dict] = {}

    def snapshot(self) -> dict[str, dict]:
        """Estado e tempos acumulados, sem prompts, nomes de modelos ou segredos."""
        with self._condition:
            return {key: {**{k: v for k, v in state.items() if k != "tickets"},
                          "waiting": len(state["tickets"])}
                    for key, state in self._resources.items()}

    @contextmanager
    def slot(self, resource: str | None, *, cancel=None, on_event=None):
        if resource is None:
            yield not (cancel is not None and cancel.is_set())
            return
        started = time.monotonic()
        ticket = object()
        acquired = False
        running_at = None

        def emit(state):
            if on_event:
                now = time.monotonic()
                on_event({"resource": resource, "state": state,
                          "wait_seconds": (running_at or now) - started,
                          "duration_seconds": now - running_at if running_at is not None else 0})

        with self._condition:
            state = self._resources.setdefault(resource, {"tickets": deque(), "active": 0,
                                                         "completed": 0, "cancelled": 0,
                                                         "wait_seconds": 0.0, "duration_seconds": 0.0})
            state["tickets"].append(ticket)
            waiting = bool(state["active"] or len(state["tickets"]) > 1)
        try:
            if waiting:
                emit("waiting")
            with self._condition:
                while not (cancel is not None and cancel.is_set()):
                    if not state["active"] and state["tickets"][0] is ticket:
                        state["tickets"].popleft()
                        state["active"] = 1
                        acquired = True
                        running_at = time.monotonic()
                        break
                    self._condition.wait(0.05)
            if acquired:
                emit("running")
            else:
                emit("cancelled")
            yield acquired
        finally:
            now = time.monotonic()
            with self._condition:
                if acquired:
                    state["active"] = 0
                    state["completed"] += 1
                    state["wait_seconds"] += running_at - started
                    state["duration_seconds"] += now - running_at
                else:
                    state["tickets"].remove(ticket)
                    state["cancelled"] += 1
                self._condition.notify_all()
            if acquired:
                emit("finished")


INFERENCE_QUEUE = InferenceQueue()
