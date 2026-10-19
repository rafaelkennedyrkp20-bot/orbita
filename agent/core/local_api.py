"""API local opcional, no formato /v1, só em 127.0.0.1.

Desligada por padrão. Só escuta com local_api=on e ORBITA_LOCAL_API_TOKEN
no ambiente (16 caracteres ou mais). Não recebe ferramenta, não aprova
controle do PC e não devolve chave de provedor.
"""

from __future__ import annotations

import hmac
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_BODY = 256_000
_ROLES = {"user", "assistant", "system"}


class LocalApiError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class LocalApi:
    def __init__(self, settings, chat, *, token: str, host: str = "127.0.0.1", port: int = 0):
        if host != "127.0.0.1":
            raise LocalApiError("A API local só escuta em 127.0.0.1.", 400)
        if not isinstance(token, str) or len(token) < 16:
            raise LocalApiError("ORBITA_LOCAL_API_TOKEN precisa ter pelo menos 16 caracteres.", 400)
        self.settings = settings
        self.chat = chat
        self.token = token
        self.releases = 0
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._httpd.api = self
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple:
        return self._httpd.server_address

    def start(self) -> "LocalApi":
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="orbita-local-api", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def model_list(self) -> dict:
        rows = []
        for name, cfg in self.settings.providers().items():
            if cfg.get("type") == "grok_cli":  # agente externo: default_chat recusa
                continue
            for model in cfg.get("models") or []:
                if isinstance(model, str) and model.strip():
                    rows.append({"id": f"{name}:{model}", "object": "model", "owned_by": "orbita"})
        return {"object": "list", "data": rows}

    def complete(self, provider: str, model: str, messages: list, cancel: threading.Event, on_text) -> str:
        from agent.core.inference_queue import INFERENCE_QUEUE
        from agent.core.local_policy import data_destination

        cfg = self.settings.provider(provider)
        resource = "local-gpu" if data_destination(provider, cfg) == "local" else None
        with INFERENCE_QUEUE.slot(resource, cancel=cancel) as acquired:
            if not acquired:
                raise LocalApiError("Geração cancelada.", 499)
            try:
                return self.chat(provider, model, messages, cancel, on_text) or ""
            finally:
                self.releases += 1


def maybe_start(settings, chat=None) -> LocalApi | None:
    """None quando a opção está desligada. Não abre porta nenhuma nesse caso."""
    import os

    if settings.get("local_api") != "on":
        return None
    token = os.environ.get("ORBITA_LOCAL_API_TOKEN", "").strip()
    if len(token) < 16:
        raise LocalApiError(
            "A API local está ligada, mas falta ORBITA_LOCAL_API_TOKEN no .env "
            "(mínimo de 16 caracteres). Nada está escutando."
        )
    if chat is None:
        def chat(provider, model, messages, cancel, on_text, _settings=settings):
            return default_chat(_settings, provider, model, messages, cancel, on_text)
    return LocalApi(settings, chat, token=token).start()


def default_chat(settings, provider: str, model: str, messages: list, cancel: threading.Event, on_text) -> str:
    """Fala com o provedor sem entregar ferramentas. Uma chamada de ferramenta é ignorada."""
    from agent.core.local_policy import refusal
    from agent.core.providers import get_provider

    cfg = settings.provider(provider)
    blocked = refusal(settings, provider, cfg, what="a API local")
    if blocked:
        raise LocalApiError(blocked, 403)
    adapter = get_provider(provider, settings)
    # Um agente externo (Grok Build) roda o turno com as próprias ferramentas: tools=None não o contém.
    if getattr(adapter, "external_agent", False):
        raise LocalApiError("Esse modelo é um agente externo com ferramentas próprias. "
                            "O chat sem ferramentas não o inicia; escolha outro modelo.", 403)
    result = adapter.chat(model, messages, tools=None, cancel=cancel, on_text=on_text)
    return result.text or ""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    @property
    def api(self) -> LocalApi:
        return self.server.api

    def do_GET(self):
        if not self._gate():
            return
        if self.path.split("?", 1)[0] != "/v1/models":
            self._send(404, {"error": "Caminho não disponível."})
            return
        self._send(200, self.api.model_list())

    def do_POST(self):
        if not self._gate():
            return
        path = self.path.split("?", 1)[0]
        if path in {"/v1/approve", "/approve", "/v1/tools"}:
            self._send(403, {"error": "A API local não aprova execução nem controla o PC."})
            return
        if path != "/v1/chat/completions":
            self._send(404, {"error": "Caminho não disponível."})
            return
        body = self._body()
        if body is None:
            return
        try:
            payload = json.loads(body)
        except (UnicodeError, json.JSONDecodeError):
            self._send(400, {"error": "JSON inválido."})
            return
        if not isinstance(payload, dict):
            self._send(400, {"error": "O pedido precisa ser um objeto."})
            return
        if "tools" in payload or "tool_choice" in payload:
            self._send(403, {"error": "A API local não executa ferramentas nem controla o PC."})
            return
        provider, model = _split_model(payload.get("model"))
        if not provider:
            self._send(400, {"error": "Informe o modelo como provedor:modelo, igual ao id da lista."})
            return
        try:
            messages = _messages(payload.get("messages"))
        except LocalApiError as error:
            self._send(error.status, {"error": str(error)})
            return
        known = {row["id"] for row in self.api.model_list()["data"]}
        full_model = f"{provider}:{model}"
        if full_model not in known:
            self._send(404, {"error": "Esse modelo não está na lista. Nada foi enviado ao provedor."})
            return
        response_id = "chatcmpl-" + uuid.uuid4().hex[:24]
        cancel = threading.Event()
        try:
            if payload.get("stream"):
                self._stream(provider, model, messages, cancel, response_id, full_model)
            else:
                text = self.api.complete(provider, model, messages, cancel, None)
                self._send(200, _completion(response_id, full_model, text))
        except LocalApiError as error:
            if not payload.get("stream"):
                self._send(error.status, {"error": str(error)})

    def _stream(self, provider, model, messages, cancel, response_id, full_model):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def on_text(piece):
            if cancel.is_set() or not piece:
                return
            event = {"id": response_id, "object": "chat.completion.chunk", "model": full_model,
                     "choices": [{"index": 0, "delta": {"content": piece}}]}
            try:
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            except OSError:
                cancel.set()

        try:
            self.api.complete(provider, model, messages, cancel, on_text)
        except LocalApiError:
            cancel.set()
        if not cancel.is_set():
            try:
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except OSError:
                cancel.set()

    def _gate(self) -> bool:
        if not _origin_ok(self.headers.get("Origin")):
            self._send(403, {"error": "Origem recusada. A API local só aceita este computador."})
            return False
        header = self.headers.get("Authorization") or ""
        token = header[7:] if header.startswith("Bearer ") else ""
        if not token or len(token) != len(self.api.token) or not hmac.compare_digest(token, self.api.token):
            self._send(401, {"error": "Autenticação necessária."})
            return False
        return True

    def _body(self):
        raw_length = self.headers.get("Content-Length") or "0"
        try:
            length = int(raw_length)
        except ValueError:
            length = MAX_BODY + 1
        if length < 0 or length > MAX_BODY:
            self._send(413, {"error": "Pedido grande demais."})
            return None
        data = self.rfile.read(length)
        if len(data) > MAX_BODY:
            self._send(413, {"error": "Pedido grande demais."})
            return None
        return data

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass


def _origin_ok(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        host = urlsplit(origin).hostname
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def _split_model(value) -> tuple[str, str]:
    if not isinstance(value, str) or ":" not in value:
        return "", ""
    provider, _, model = value.partition(":")
    if not provider.strip() or not model.strip():
        return "", ""
    return provider.strip(), model.strip()


def _messages(value) -> list[dict]:
    if not isinstance(value, list) or not value or len(value) > 40:
        raise LocalApiError("Envie de 1 a 40 mensagens.")
    clean = []
    for item in value:
        if not isinstance(item, dict) or item.get("role") not in _ROLES:
            raise LocalApiError("Cada mensagem precisa de um papel user, assistant ou system.")
        content = item.get("content")
        if not isinstance(content, str) or len(content) > 32_000:
            raise LocalApiError("O texto da mensagem é inválido.")
        clean.append({"role": item["role"], "content": content})
    return clean


def _completion(response_id: str, model: str, text: str) -> dict:
    return {
        "id": response_id,
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }
