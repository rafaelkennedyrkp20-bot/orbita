"""Galeria persistente das imagens e clipes gerados.

O índice fica em data/ e sobrevive ao reinício. Um arquivo que sumiu do disco
continua na lista, marcado como ausente. Esquecer tira só a referência.
Apagar remove o arquivo daquela entrada e nada de outro projeto.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from agent.core.config import DATA_DIR

_SECRET = re.compile(r"\b(?:sk|sk-ant|sk-or|gsk|xai|ghp|hf_|pplx|r8_|AIza)[-_A-Za-z0-9]{12,}\b")
_LIMIT = 400
_LOCK = threading.Lock()
_GALLERY: Gallery | None = None


def project_key(path) -> str:
    """Uma pasta, em um formato só, para comparar projetos."""
    return str(path or "").strip().replace("\\", "/").rstrip("/").lower()


def _clean(text: str, limit: int) -> str:
    return _SECRET.sub("[removido]", str(text or ""))[:limit]


class Gallery:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._items = self._load()

    def _load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return []
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict) and item.get("id")]

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"items": self._items[-_LIMIT:]}, ensure_ascii=False, indent=2)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)
        self._items = self._items[-_LIMIT:]

    def add(self, *, path: str, prompt: str, model: str, backend: str, project: str,
            kind: str = "image", seed=None, size: str = "", device: str = "",
            conversation_id: str = "") -> dict:
        item = {
            "id": uuid.uuid4().hex[:12],
            "path": str(path),
            "prompt": _clean(prompt, 2000),
            "model": _clean(model, 300),
            "backend": _clean(backend, 40) or "api",
            "project": project_key(project),
            "kind": "clip" if kind == "clip" else "image",
            "seed": seed if isinstance(seed, int) and not isinstance(seed, bool) else None,
            "size": _clean(size, 40),
            "device": _clean(device, 200),
            "conversation_id": _clean(conversation_id, 40),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            self._items.append(item)
            self._write()
        return dict(item)

    def list(self, project: str, query: str = "") -> list[dict]:
        key = project_key(project)
        words = [word for word in (query or "").lower().split() if word]
        with self._lock:
            rows = []
            for item in self._items:
                if project_key(item.get("project")) != key:
                    continue
                prompt = (item.get("prompt") or "").lower()
                if words and not all(word in prompt for word in words):
                    continue
                file_path = Path(item.get("path") or "")
                try:
                    exists = file_path.is_file()
                except OSError:
                    exists = False
                rows.append({**item, "exists": exists})
        return rows

    def _owned(self, item_id: str, project: str) -> tuple[dict | None, str | None]:
        key = project_key(project)
        for item in self._items:
            if item.get("id") != item_id:
                continue
            if project_key(item.get("project")) != key:
                return None, "Esta entrada é de outro projeto."
            return item, None
        return None, "Não encontrei esta entrada na galeria."

    def forget(self, item_id: str, *, project: str) -> str | None:
        """Tira a referência. O arquivo no disco fica onde está."""
        with self._lock:
            item, error = self._owned(item_id, project)
            if error:
                return error
            self._items = [row for row in self._items if row.get("id") != item.get("id")]
            self._write()
        return None

    def delete_file(self, item_id: str, *, project: str) -> str | None:
        """Apaga o arquivo desta entrada e tira a referência. Não mexe em outro projeto."""
        with self._lock:
            item, error = self._owned(item_id, project)
            if error:
                return error
            file_path = Path(item.get("path") or "")
            try:
                is_file = file_path.is_file()
            except OSError:
                is_file = False
            if is_file:
                try:
                    file_path.unlink()
                except OSError as failure:
                    return f"Não consegui apagar o arquivo: {failure.strerror or failure}"
            self._items = [row for row in self._items if row.get("id") != item.get("id")]
            self._write()
        return None


def get_gallery() -> Gallery:
    global _GALLERY
    with _LOCK:
        if _GALLERY is None:
            _GALLERY = Gallery(DATA_DIR / "gallery.json")
        return _GALLERY
