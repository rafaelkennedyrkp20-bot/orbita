"""Autenticidade de um pacote de atualização.

A chave não mora no repositório. Ela vem de ORBITA_UPDATE_KEY ou do arquivo
apontado por ORBITA_UPDATE_KEY_FILE. O mecanismo é HMAC-SHA256, uma chave
compartilhada, e não uma assinatura de chave pública. Sem a chave certa, ou
com o selo errado, nada é gravado.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path


class UpdateAuthError(RuntimeError):
    """O pacote não foi aceito. Nenhum arquivo do programa foi trocado."""


def canonical(manifest: dict) -> bytes:
    return json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(manifest: dict, key: bytes) -> str:
    _check_key(key)
    return hmac.new(key, canonical(manifest), hashlib.sha256).hexdigest()


def verify_manifest(manifest: dict, signature: str, key: bytes) -> None:
    """Confere o selo. Erro aqui acontece antes de abrir o pacote para gravar."""
    _check_key(key)
    if not isinstance(manifest, dict):
        raise UpdateAuthError("Manifesto inválido. Nada foi alterado.")
    if not isinstance(signature, str) or not signature.strip():
        raise UpdateAuthError("Assinatura ausente. Nada foi alterado.")
    expected = sign_manifest(manifest, key)
    given = signature.strip().lower()
    if len(given) != len(expected) or not hmac.compare_digest(expected, given):
        raise UpdateAuthError("Assinatura inválida. Nada foi alterado.")


def load_key() -> bytes | None:
    """None quando a pessoa não configurou chave. Não inventa uma chave padrão."""
    inline = os.environ.get("ORBITA_UPDATE_KEY", "").strip()
    if inline:
        return inline.encode("utf-8")
    path = os.environ.get("ORBITA_UPDATE_KEY_FILE", "").strip()
    if not path:
        return None
    try:
        data = Path(path).read_bytes().strip()
    except OSError:
        return None
    return data or None


def _check_key(key: bytes) -> None:
    if isinstance(key, str):
        raise UpdateAuthError("A chave local precisa ser bytes. Nada foi alterado.")
    if not isinstance(key, (bytes, bytearray)) or len(key) < 16:
        raise UpdateAuthError("A chave local é curta demais ou está ausente. Nada foi alterado.")
