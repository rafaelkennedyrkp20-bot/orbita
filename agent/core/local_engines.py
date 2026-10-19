"""Sondas limitadas a loopback; descobrir um motor nunca muda preferências."""

from __future__ import annotations

import ipaddress
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx


def is_loopback_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return False
        host = parsed.hostname or ""
        return host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def probe_engine(name: str, cfg: dict, *, client=None, cancel=None, timeout: float = 1.5) -> dict:
    base = cfg.get("base_url", "").rstrip("/")
    row = {"id": name, "label": cfg.get("label", name), "base_url": base, "models": [],
           "status": "offline", "message": "Não respondeu. Abra o motor e ative seu servidor local."}
    if not is_loopback_url(base):
        return {**row, "status": "incompatible", "message": "A descoberta aceita somente endereços deste computador."}
    if cancel is not None and cancel.is_set():
        return {**row, "status": "cancelled", "message": "Busca cancelada."}
    ollama = cfg.get("type") == "ollama"
    url = (base.removesuffix("/v1") + "/api/tags") if ollama else base + "/models"
    owned = client is None
    client = client or httpx.Client(trust_env=False, follow_redirects=False)
    try:
        started = time.monotonic()
        with client.stream("GET", url, timeout=timeout, follow_redirects=False) as response:
            if response.status_code in (401, 403):
                return {**row, "status": "auth_required", "message": "Motor protegido por chave. Configure a chave na API manual."}
            if response.status_code != 200:
                return {**row, "status": "incompatible", "message": f"Resposta HTTP {response.status_code}; confira a API e a porta."}
            body = bytearray()
            for chunk in response.iter_bytes():
                if cancel is not None and cancel.is_set():
                    return {**row, "status": "cancelled", "message": "Busca cancelada."}
                body.extend(chunk)
                if len(body) > 65536 or time.monotonic() - started > timeout:
                    raise ValueError("Resposta excedeu o limite da sonda.")
        payload = json.loads(body)
        items = payload.get("models" if ollama else "data") if isinstance(payload, dict) else None
        key = "name" if ollama else "id"
        if not isinstance(items, list) or any(not isinstance(item, dict) or not isinstance(item.get(key), str)
                                              or not item[key].strip() for item in items):
            raise ValueError("Formato de modelos incompatível.")
        models = sorted({item[key].strip() for item in items})[:500]
        return {**row, "models": models, "status": "available" if models else "no_models",
                "message": f"{len(models)} modelo(s) disponível(is)." if models else "Motor acessível, sem modelos. Baixe um modelo no motor."}
    except httpx.HTTPError:
        return row
    except (ValueError, TypeError):
        return {**row, "status": "incompatible", "message": "O serviço não retornou uma lista de modelos compatível."}
    finally:
        if owned:
            client.close()


def detect_local_engines(providers: dict, *, cancel: threading.Event | None = None, client=None,
                         timeout: float = 1.5) -> list[dict]:
    targets = [(name, cfg) for name, cfg in providers.items() if cfg.get("type") in ("ollama", "openai")
               and is_loopback_url(cfg.get("base_url", ""))][:16]
    if not targets or (cancel is not None and cancel.is_set()):
        return []
    with ThreadPoolExecutor(max_workers=min(4, len(targets)), thread_name_prefix="local-probe") as pool:
        futures = [pool.submit(probe_engine, name, cfg, client=client, cancel=cancel, timeout=timeout)
                   for name, cfg in targets]
        return [result for future in futures if (result := future.result())["status"] != "cancelled"]
