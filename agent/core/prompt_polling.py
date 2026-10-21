"""Recebe pedidos de uma fila HTTP explícita e usa o loop normal do Órbita.

A API da Cassandra devolve uma lista de {id, prompt}; alguns gateways a
embrulham em {body: JSON}. Sem protocolo de ACK, a deduplicação é limitada
a esta execução. A fila deve remover pedidos concluídos entre reinícios.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from collections import deque
from urllib.parse import urlsplit

import requests

from agent.core.local_policy import local_only

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PROMPT_CHARS = 128_000
MAX_PENDING_ITEMS = 100
MAX_COMPLETED = 1000


class PollingError(RuntimeError):
    """Fila indisponível ou resposta inválida; não contém credenciais."""


def validate_polling(url: str, delay: float) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as error:
        raise ValueError("Endereço da fila inválido.") from error
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment or (port is not None and port < 1)):
        raise ValueError("A fila precisa de um endereço HTTP/HTTPS sem usuário, senha ou fragmento.")
    if not math.isfinite(delay) or delay < .5:
        raise ValueError("O intervalo da fila deve ser finito e de pelo menos 0,5 segundo.")


def _fetch(url: str, api_key: str) -> list[dict]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = requests.get(url, headers=headers, timeout=(5, 30), stream=True, allow_redirects=False)
        try:
            if 300 <= response.status_code < 400:
                raise PollingError("A fila redirecionou. Configure o endereço final explicitamente.")
            response.raise_for_status()
            if int(response.headers.get("Content-Length", 0)) > MAX_RESPONSE_BYTES:
                raise PollingError("A resposta da fila passou do limite de 2 MB.")
            raw = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise PollingError("A resposta da fila passou do limite de 2 MB.")
            payload = json.loads(raw)
        finally:
            response.close()
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise PollingError("A fila informou que a consulta está indisponível.")
        if isinstance(payload, dict) and isinstance(payload.get("body"), str):
            payload = json.loads(payload["body"])
        if not isinstance(payload, list):
            raise PollingError("A fila precisa devolver uma lista de pedidos {id, prompt}.")
        if len(payload) > MAX_PENDING_ITEMS:
            raise PollingError("A fila passou do limite de 100 pedidos por consulta.")
        return [item for item in payload if isinstance(item, dict)]
    except PollingError:
        raise
    except Exception as error:
        # Requests inclui cabeçalhos/URLs em algumas exceções; nunca os devolva.
        logger.warning("Consulta à fila falhou (%s).", type(error).__name__)
        raise PollingError("Fila indisponível ou resposta inválida. Confira o endereço e a autenticação.") from None


def _execute(brain, prompt: str, stop: threading.Event, approve, events) -> bool:
    finished = threading.Event()
    failed = False

    def watch_stop():
        while not finished.wait(.1):
            if stop.is_set():
                brain.stop()
                return

    def report(kind, data):
        nonlocal failed
        failed = failed or kind == "error"
        events(kind, data)

    brain.new_conversation()
    watcher = threading.Thread(target=watch_stop, name="orbita-poll-stop", daemon=True)
    watcher.start()
    try:
        brain.run_turn(prompt, approve=approve, events=report)
        session = getattr(brain, "session", None)
        cancelled = getattr(session, "cancel", None)
        return not failed and not stop.is_set() and not (cancelled and cancelled.is_set())
    except Exception as error:
        logger.warning("Pedido da fila falhou (%s).", type(error).__name__)
        events("status", {"text": "O pedido da fila falhou; ele poderá ser tentado na próxima consulta."})
        return False
    finally:
        finished.set()
        watcher.join(timeout=.5)


def run_polling(brain, url: str, delay: float = 30.0, *, stop: threading.Event | None = None,
                once: bool = False, approve=None, events=None, api_key: str = "") -> int:
    """Processa a fila até Parar/Ctrl+C; devolve quantos pedidos foram concluídos.

    O chamador escolhe o endpoint completo e fornece a chave separada. Permissões
    continuam no AgentSession; sem callback, confirmações recebem sempre "no".
    Cada pedido começa uma conversa e a espera entre consultas pode ser cancelada.
    """
    validate_polling(url, delay)
    stop = stop or threading.Event()
    approve = approve or (lambda _request: "no")
    events = events or (lambda _kind, _data: None)
    completed, order, count = set(), deque(), 0
    while not stop.is_set():
        if local_only(brain.settings):
            raise PollingError("Modo somente local: a consulta à fila HTTP está bloqueada.")
        try:
            pending = _fetch(url, api_key)
        except PollingError:
            if once:
                raise
            events("status", {"text": "Fila indisponível; nova consulta após o intervalo configurado."})
            pending = []
        for item in pending:
            if stop.is_set():
                break
            prompt = item.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
                continue
            item_id = item.get("id")
            key = ("id:" + hashlib.sha256(str(item_id).encode("utf-8")).hexdigest()) if isinstance(item_id, (str, int)) else (
                "prompt:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest())
            if key in completed:
                continue
            if _execute(brain, prompt, stop, approve, events):
                completed.add(key)
                order.append(key)
                count += 1
                if len(order) > MAX_COMPLETED:
                    completed.remove(order.popleft())
        if once or stop.wait(delay):
            break
    return count
