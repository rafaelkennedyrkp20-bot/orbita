"""Acesso de outro aparelho na rede local. Desligado por padrão.

O pareamento expira, erra no máximo cinco vezes e a revogação vale na hora.
O aparelho pareado não aprova execução nem controle do PC, e não lê o
projeto de outro aparelho. Não escuta em 0.0.0.0.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent.core.local_api import LocalApiError, _messages

CODE_TTL = 300
MAX_ATTEMPTS = 5


class PairError(RuntimeError):
    pass


class Pairing:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._active: dict | None = None
        self._devices: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return
        devices = data.get("devices") if isinstance(data, dict) else None
        if isinstance(devices, dict):
            self._devices = {key: value for key, value in devices.items() if isinstance(value, dict)}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"devices": self._devices}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def issue(self, project: str, now: float | None = None, code: str | None = None) -> str:
        stamp = time.time() if now is None else now
        chosen = code or f"{secrets.randbelow(1_000_000):06d}"
        if not isinstance(chosen, str) or len(chosen) != 6 or not chosen.isdigit():
            raise PairError("O código de pareamento tem 6 dígitos.")
        with self._lock:
            self._active = {"code": chosen, "expires": stamp + CODE_TTL, "attempts": 0,
                            "project": str(project or "")}
        return chosen

    def pair(self, code: str, now: float | None = None) -> dict:
        stamp = time.time() if now is None else now
        with self._lock:
            active = self._active
            if active is None or stamp >= active["expires"]:
                raise PairError("Código expirado ou inexistente.")
            if active["attempts"] >= MAX_ATTEMPTS:
                self._active = None
                raise PairError("Tentativas esgotadas.")
            given = code if isinstance(code, str) else ""
            if len(given) != len(active["code"]) or not hmac.compare_digest(given, active["code"]):
                active["attempts"] += 1
                if active["attempts"] >= MAX_ATTEMPTS:
                    self._active = None
                raise PairError("Código recusado.")
            token = secrets.token_urlsafe(24)
            device_id = uuid.uuid4().hex[:12]
            self._devices[device_id] = {
                "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "project": active["project"],
                "revoked": False,
            }
            self._active = None
            self._save()
        return {"device_id": device_id, "token": token, "project": self._devices[device_id]["project"]}

    def authorize(self, token: str) -> dict | None:
        if not isinstance(token, str) or not token:
            return None
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            for device_id, device in self._devices.items():
                if device.get("revoked"):
                    continue
                stored = str(device.get("token_hash") or "")
                if len(stored) == len(digest) and hmac.compare_digest(stored, digest):
                    return {"id": device_id, "project": device.get("project") or ""}
        return None

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            device = self._devices.get(device_id)
            if not device:
                return False
            device["revoked"] = True
            self._save()
        return True

    def public_devices(self) -> list[dict]:
        with self._lock:
            return [{"id": device_id, "project": device.get("project") or "",
                     "revoked": bool(device.get("revoked"))}
                    for device_id, device in self._devices.items()]


def allowed_host(host: str) -> bool:
    if host == "127.0.0.1":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private and not address.is_loopback and not address.is_unspecified
                and not address.is_multicast and not address.is_reserved)


def lan_address() -> str | None:
    """Endereço privado desta máquina, sem abrir serviço e sem enviar pacote."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        host = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    return host if allowed_host(host) else None


class RemoteServer:
    def __init__(self, pairing: Pairing, chat, *, host: str = "127.0.0.1", port: int = 0):
        if not allowed_host(host):
            raise PairError("Endereço recusado. O acesso remoto não escuta em todas as interfaces.")
        self.pairing = pairing
        self.chat = chat
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._httpd.remote = self

    @property
    def address(self) -> tuple:
        return self._httpd.server_address

    def start(self) -> "RemoteServer":
        threading.Thread(target=self._httpd.serve_forever, name="orbita-remote", daemon=True).start()
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


def open_remote(settings, pairing: Pairing, chat=None, host: str = "127.0.0.1") -> RemoteServer | None:
    """None com a opção desligada. Não cria soquete nesse caso."""
    if settings is None or settings.get("remote_access") != "on":
        return None
    return RemoteServer(pairing, chat, host=host).start()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    @property
    def remote(self) -> RemoteServer:
        return self.server.remote

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        body = self._body()
        if body is None:
            return
        try:
            payload = json.loads(body or b"{}")
        except (UnicodeError, json.JSONDecodeError):
            self._send(400, {"error": "JSON inválido."})
            return
        if not isinstance(payload, dict):
            self._send(400, {"error": "O pedido precisa ser um objeto."})
            return
        if path == "/pair":
            self._pair(payload)
            return
        device = self._device()
        if device is None:
            self._send(401, {"error": "Aparelho não pareado ou revogado."})
            return
        if path in {"/v1/approve", "/approve"}:
            self._send(403, {"error": "Cliente remoto não aprova execução nem controle do PC."})
            return
        if path != "/v1/chat/completions":
            self._send(404, {"error": "Caminho não disponível."})
            return
        if "tools" in payload or "tool_choice" in payload:
            self._send(403, {"error": "Cliente remoto não executa ferramentas nem controla o PC."})
            return
        asked = payload.get("project")
        if asked is not None and str(asked) != device["project"]:
            self._send(403, {"error": "Este aparelho não acessa outro projeto."})
            return
        try:
            messages = _messages(payload.get("messages"))
        except LocalApiError as error:
            self._send(error.status, {"error": str(error)})
            return
        if self.remote.chat is None:
            self._send(503, {"error": "O chat remoto não está ligado."})
            return
        text = self.remote.chat(messages, device["project"])
        response_id = "chatcmpl-" + uuid.uuid4().hex[:24]
        self._send(200, {"id": response_id, "model": "remote", "project": device["project"],
                         "choices": [{"message": {"role": "assistant", "content": text or ""}}]})

    def do_GET(self):
        if self.path.split("?", 1)[0] != "/v1/project":
            self._send(404, {"error": "Caminho não disponível."})
            return
        device = self._device()
        if device is None:
            self._send(401, {"error": "Aparelho não pareado ou revogado."})
            return
        self._send(200, {"project": device["project"]})

    def _pair(self, payload: dict) -> None:
        try:
            granted = self.remote.pairing.pair(str(payload.get("code") or ""))
        except PairError as error:
            self._send(403, {"error": str(error)})
            return
        self._send(200, granted)

    def _device(self):
        header = self.headers.get("Authorization") or ""
        token = header[7:] if header.startswith("Bearer ") else ""
        return self.remote.pairing.authorize(token)

    def _body(self):
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 256_001
        if length < 0 or length > 256_000:
            self._send(413, {"error": "Pedido grande demais."})
            return None
        return self.rfile.read(length)

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass
