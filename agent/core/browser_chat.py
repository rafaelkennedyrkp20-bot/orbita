"""Chat local no navegador com o mesmo Brain, permissões e loop da janela."""

from __future__ import annotations

import hmac
import ipaddress
import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent.ui.render import markdown_html

MAX_BODY_BYTES = 1024 * 1024
MAX_MESSAGE_CHARS = 80_000
MAX_ATTACHMENTS = 40
MAX_ATTACHMENT_BYTES = 100_000
MAX_ATTACHMENT_TOTAL_BYTES = 500_000
APPROVAL_TIMEOUT = 120
_PAGE = Path(__file__).resolve().parents[1] / "ui" / "browser.html"
_SECRET_NAMES = {"credentials", "credentials.json", "secrets", "secrets.json", "id_rsa", "id_ed25519"}
_BINARY_SUFFIXES = {".exe", ".dll", ".so", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".docx", ".xlsx", ".pyc", ".wasm", ".pem", ".key", ".p12", ".pfx"}


def _chat_text(payload: dict) -> str:
    text = payload.get("message", "")
    attachments = payload.get("attachments", [])
    if not isinstance(text, str) or len(text) > MAX_MESSAGE_CHARS:
        raise ValueError("Mensagem inválida ou grande demais.")
    if not isinstance(attachments, list) or len(attachments) > MAX_ATTACHMENTS:
        raise ValueError("Anexe no máximo 40 arquivos de texto.")
    parts, total = [text.strip()], 0
    for item in attachments:
        if not isinstance(item, dict):
            raise ValueError("Anexo inválido.")
        name, content = item.get("name"), item.get("content")
        if not isinstance(name, str) or not name or len(name) > 500 or not isinstance(content, str):
            raise ValueError("Nome ou conteúdo do anexo inválido.")
        path = Path(name.replace("\\", "/"))
        segments = name.replace("\\", "/").lower().split("/")
        if (path.is_absolute() or ".." in segments or any(
                segment.startswith(".env") or segment in _SECRET_NAMES or segment in {".git", ".ssh"}
                for segment in segments) or path.suffix.lower() in _BINARY_SUFFIXES or "\x00" in content):
            raise ValueError("Anexo recusado: arquivo binário ou potencial segredo.")
        size = len(content.encode("utf-8"))
        total += size
        if size > MAX_ATTACHMENT_BYTES or total > MAX_ATTACHMENT_TOTAL_BYTES:
            raise ValueError("Anexos excedem 100 KB por arquivo ou 500 KB no total.")
        parts.append(f"[Arquivo anexado pelo usuário: {name}]\n{content}\n[Fim do arquivo]")
    result = "\n\n".join(parts).strip()
    if not result:
        raise ValueError("Digite uma mensagem ou anexe um arquivo de texto.")
    return result


class BrowserChatServer:
    def __init__(self, brain, *, host: str = "127.0.0.1", port: int = 8080):
        host = "127.0.0.1" if host == "localhost" else host
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise ValueError("O chat no navegador aceita somente um endereço local loopback.") from None
        if not address.is_loopback:
            raise ValueError("O chat no navegador aceita somente um endereço local loopback.")
        self.brain = brain
        self.token = secrets.token_urlsafe(32)
        self._task = threading.Lock()
        self._state = threading.Lock()
        self._approvals: dict[str, dict] = {}
        self._clear_on_idle = False
        self._cancel = threading.Event()
        self._closed = threading.Event()
        self._thread = None
        server_type = type("_LocalServer", (ThreadingHTTPServer,), {"address_family": socket.AF_INET6 if address.version == 6 else socket.AF_INET})
        self._httpd = server_type((host, port), _Handler)
        self._httpd.chat = self

    @property
    def address(self) -> tuple:
        return self._httpd.server_address

    @property
    def url(self) -> str:
        host, port = self.address[:2]
        authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        return f"http://{authority}/#token={self.token}"

    def start(self) -> "BrowserChatServer":
        if self._closed.is_set():
            raise RuntimeError("O servidor já foi encerrado.")
        if self._thread is None:
            self._thread = threading.Thread(target=self._httpd.serve_forever, name="orbita-browser", daemon=True)
            self._thread.start()
        return self

    def wait(self, timeout: float | None = None) -> bool:
        """True quando encerrado; permite ao chamador tratar Ctrl+C no terminal."""
        return self._closed.wait(timeout)

    def cancel(self) -> None:
        with self._state:
            self._cancel_task()

    def _cancel_task(self) -> None:
        """O chamador mantém _state para não cancelar um turno que começou depois."""
        self._cancel.set()
        for approval in self._approvals.values():
            approval["answer"] = "no"
            approval["ready"].set()
        if self._task.locked():
            self.brain.stop()

    def close_temporary(self) -> None:
        """Recebido pagehide: limpa já ou agenda sem aguardar o turno terminar."""
        with self._state:
            if not getattr(self.brain, "temporary", False):
                return
            if not self._task.acquire(blocking=False):
                self._clear_on_idle = True
                self._cancel_task()
                return
            try:
                self.brain.new_conversation()
            finally:
                self._task.release()

    def finish_task(self) -> None:
        with self._state:
            try:
                if self._clear_on_idle:
                    self._clear_on_idle = False
                    if getattr(self.brain, "temporary", False):
                        self.brain.new_conversation()
            finally:
                self._task.release()

    def stop(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self.cancel()
        if self._thread is not None:
            self._httpd.shutdown()
            self._thread.join(timeout=3)
        self._httpd.server_close()
        if self._task.acquire(timeout=3):
            self._task.release()

    def state(self) -> dict:
        provider, model = self.brain.current_model
        profiles = getattr(self.brain, "profiles", None)
        settings = getattr(self.brain, "settings", None)
        with self._state:
            approvals = [{"id": key, "request": entry["request"]} for key, entry in self._approvals.items()]
        return {"busy": self._task.locked(), "provider": provider, "model": model,
                "temporary": bool(getattr(self.brain, "temporary", False)),
                "profile": {"id": self.brain.profile.id, "name": self.brain.profile.name},
                "profiles": [{"id": p.id, "name": p.name} for p in profiles.list()] if profiles else [],
                "providers": [{"id": key, "label": cfg.get("label", key), "models": cfg.get("models", [])}
                              for key, cfg in settings.providers().items()] if settings else [],
                "approvals": approvals}

    def configure(self, payload: dict) -> None:
        """Valida antes de alterar. Só o chamador que detém _task pode configurar."""
        if set(payload) - {"provider", "model", "profile", "temporary"}:
            raise ValueError("Opção de configuração desconhecida.")
        profile = payload.get("profile")
        if "profile" in payload:
            profiles = getattr(self.brain, "profiles", None)
            if not isinstance(profile, str) or profiles is None or profile not in {p.id for p in profiles.list()}:
                raise ValueError("Perfil inexistente.")
        if "provider" in payload or "model" in payload:
            provider, model = payload.get("provider"), payload.get("model")
            settings = getattr(self.brain, "settings", None)
            catalog = settings.providers() if settings else {}
            if (not isinstance(provider, str) or not isinstance(model, str) or provider not in catalog
                    or model not in catalog[provider].get("models", [])):
                raise ValueError("Escolha um modelo e provedor disponíveis no catálogo do Órbita.")
        if "temporary" in payload and type(payload["temporary"]) is not bool:
            raise ValueError("A opção de conversa temporária precisa ser verdadeira ou falsa.")
        if profile is not None:
            self.brain.select_profile(profile)
        if "model" in payload:
            self.brain.select_model(payload["provider"], payload["model"])
        if "temporary" in payload:
            self.brain.set_temporary(payload["temporary"])

    def approve(self, request: dict, emit, interactive: bool) -> str:
        if not interactive or self._cancel.is_set() or self._closed.is_set():
            emit("approval_denied", {"message": "Ação recusada: confirmação interativa indisponível."})
            return "no"
        key = secrets.token_urlsafe(18)
        entry = {"request": request, "answer": "no", "ready": threading.Event()}
        with self._state:
            if self._cancel.is_set() or self._closed.is_set():
                return "no"
            self._approvals[key] = entry
        try:
            emit("approval", {"id": key, "request": request})
            entry["ready"].wait(APPROVAL_TIMEOUT)
            return "no" if self._cancel.is_set() or self._closed.is_set() else entry["answer"]
        finally:
            with self._state:
                self._approvals.pop(key, None)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # O token e o conteúdo do usuário não entram no log HTTP.

    @property
    def chat(self) -> BrowserChatServer:
        return self.server.chat

    def _allowed(self, authenticated=True) -> bool:
        host = self.headers.get("Host", "")
        authority = self.chat.url.partition("//")[2].split("/")[0]
        aliases = {authority}
        if self.chat.address[0] == "127.0.0.1":
            aliases.add(f"localhost:{self.chat.address[1]}")
        origin = self.headers.get("Origin")
        if (host not in aliases or (origin is not None and origin != "http://" + host)
                or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            self._json(403, {"error": "Origem ou endereço recusado."})
            return False
        given = self.headers.get("Authorization", "").encode("utf-8")
        expected = ("Bearer " + self.chat.token).encode("utf-8")
        if authenticated and not hmac.compare_digest(given, expected):
            self._json(401, {"error": "Abra o endereço completo mostrado pelo Órbita neste computador."})
            return False
        return True

    def _headers(self, status, content_type, length=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        if length is not None:
            self.send_header("Content-Length", str(length))

    def _json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(raw))
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if not self._allowed(authenticated=path != "/"):
            return
        if path == "/":
            nonce = secrets.token_urlsafe(18)
            page = _PAGE.read_text(encoding="utf-8").replace("__NONCE__", nonce).encode("utf-8")
            self._headers(200, "text/html; charset=utf-8", len(page))
            self.send_header("Content-Security-Policy", "default-src 'none'; "
                             f"script-src 'nonce-{nonce}'; style-src 'unsafe-inline'; connect-src 'self'; "
                             "img-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(page)
            self.close_connection = True
        elif path == "/api/state":
            self._json(200, self.chat.state())
        else:
            self._json(404, {"error": "Caminho inexistente."})

    def _payload(self):
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            self._json(415, {"error": "Envie JSON."})
            return None
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = -1
        if self.headers.get("Transfer-Encoding") or size < 0 or size > MAX_BODY_BYTES:
            self._json(413, {"error": "Pedido excede o limite de 1 MB ou tamanho inválido."})
            return None
        self.connection.settimeout(10)
        try:
            raw = self.rfile.read(size)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, UnicodeError, OSError):
            self._json(400, {"error": "JSON inválido."})
            return None

    def do_POST(self):
        if not self._allowed():
            return
        payload = self._payload()
        if payload is None:
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/stop":
            self.chat.cancel()
            self._json(200, {"ok": True})
        elif path == "/api/close":
            self.chat.close_temporary()
            self._json(200, {"ok": True})
        elif path == "/api/approve":
            self._approval(payload)
        elif path in {"/api/chat", "/api/new", "/api/config"}:
            with self.chat._state:
                accepted = not self.chat._closed.is_set() and self.chat._task.acquire(blocking=False)
                if accepted:
                    self.chat._cancel.clear()
            if not accepted:
                self._json(409, {"error": "O Órbita está trabalhando. Aguarde ou clique em Parar."})
                return
            try:
                if path == "/api/config":
                    try:
                        self.chat.configure(payload)
                        self._json(200, self.chat.state())
                    except (ValueError, KeyError) as error:
                        self._json(400, {"error": str(error)})
                elif path == "/api/new":
                    self.chat.brain.new_conversation()
                    self._json(200, {"ok": True})
                else:
                    self._run(payload)
            finally:
                self.chat.finish_task()
        else:
            self._json(404, {"error": "Caminho inexistente."})

    def _approval(self, payload):
        key, answer = payload.get("id"), payload.get("answer")
        if not isinstance(key, str) or not isinstance(answer, str) or answer not in {"yes", "no"}:
            self._json(400, {"error": "Confirme ou recuse esta ação."})
            return
        with self.chat._state:
            approval = self.chat._approvals.get(key)
            if approval is not None and not approval["ready"].is_set():
                approval["answer"] = answer
                approval["ready"].set()
            else:
                approval = None
        self._json(200 if approval else 404, {"ok": bool(approval)})

    def _run(self, payload):
        try:
            text = _chat_text(payload)
        except ValueError as error:
            self._json(400, {"error": str(error)})
            return
        self._headers(200, "application/x-ndjson; charset=utf-8")
        self.end_headers()
        self.close_connection = True
        write_lock = threading.Lock()

        def emit(kind, data):
            raw = json.dumps({"type": kind, **data}, ensure_ascii=False, default=str).encode("utf-8") + b"\n"
            with write_lock:
                self.wfile.write(raw)
                self.wfile.flush()

        try:
            result = "Interrompido." if self.chat._cancel.is_set() else self.chat.brain.run_turn(
                text, events=emit, approve=lambda request: self.chat.approve(
                    request, emit, payload.get("interactive_approval") is True))
            emit("done", {"text": result, "html": markdown_html(result)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.chat.cancel()
        except Exception as error:
            try:
                emit("error", {"message": str(error)})
            except OSError:
                self.chat.cancel()
