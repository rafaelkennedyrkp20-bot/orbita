"""
conversations.py — Conversas salvas e reabríveis (lista lateral da interface).

Cada conversa é um JSON em `data/conversations/<id>.json` com as mensagens no formato interno
(ver providers.py), o perfil/modelo usados, o resumo da compactação e a sessão do Grok Build.
A interface reconstrói o chat a partir das mensagens.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent.core.config import DATA_DIR

CONVERSATIONS_DIR = DATA_DIR / "conversations"
_ID = re.compile(r"^[a-f0-9]{12}$")
_TOOL_CALL = re.compile(r"<tool_call>.*?(?:</tool_call>|$)", re.DOTALL)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def title_from(text: str) -> str:
    line = " ".join((text or "").split())
    return (line[:57] + "…") if len(line) > 58 else (line or "Nova conversa")


class ConversationStore:

    def __init__(self, directory: Path = CONVERSATIONS_DIR):
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self._meta_cache: dict[str, tuple[int, int, dict]] = {}
        self._last_loaded: Optional[tuple[str, int, int, dict]] = None

    def _path(self, conversation_id: str) -> Optional[Path]:
        return self.dir / f"{conversation_id}.json" if _ID.match(conversation_id or "") else None

    @staticmethod
    def _extract_meta(data: dict, fallback_id: str) -> dict:
        return {
            "id": data.get("id", fallback_id),
            "title": data.get("title", "Conversa"),
            "updated": data.get("updated", ""),
            "profile": data.get("profile", ""),
            "model": data.get("model", ""),
        }

    def save(self, data: dict) -> None:
        path = self._path(data["id"])
        if path is None:
            return
        data["updated"] = datetime.now().isoformat(timespec="seconds")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        try:
            st = path.stat()
            self._meta_cache[path.name] = (st.st_mtime_ns, st.st_size, self._extract_meta(data, path.stem))
            self._last_loaded = (data["id"], st.st_mtime_ns, st.st_size, dict(data))
        except OSError:
            pass

    def load(self, conversation_id: str) -> Optional[dict]:
        path = self._path(conversation_id)
        if path is None:
            return None
        try:
            st = path.stat()
        except OSError:
            return None
        if self._last_loaded and self._last_loaded[0] == conversation_id \
                and self._last_loaded[1] == st.st_mtime_ns and self._last_loaded[2] == st.st_size:
            return dict(self._last_loaded[3])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        self._meta_cache[path.name] = (st.st_mtime_ns, st.st_size, self._extract_meta(data, path.stem))
        self._last_loaded = (conversation_id, st.st_mtime_ns, st.st_size, dict(data))
        return data

    def delete(self, conversation_id: str) -> bool:
        path = self._path(conversation_id)
        if path is None or not path.exists():
            return False
        path.unlink()
        self._meta_cache.pop(path.name, None)
        if self._last_loaded and self._last_loaded[0] == conversation_id:
            self._last_loaded = None
        return True

    def rename(self, conversation_id: str, title: str) -> bool:
        data = self.load(conversation_id)
        if not data:
            return False
        data["title"] = title.strip()[:80] or data.get("title", "")
        data["pinned_title"] = True
        self.save(data)
        return True

    def list(self, limit: int = 200) -> list[dict]:
        items = []
        seen_names: set[str] = set()
        try:
            entries = list(os.scandir(self.dir))
        except OSError:
            return []
        for entry in entries:
            if not entry.name.endswith(".json") or not entry.is_file():
                continue
            seen_names.add(entry.name)
            try:
                st = entry.stat()
            except OSError:
                continue
            cached = self._meta_cache.get(entry.name)
            if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
                items.append(dict(cached[2]))
                continue
            try:
                data = json.loads(Path(entry.path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            stem = entry.name[:-5]
            meta = self._extract_meta(data, stem)
            self._meta_cache[entry.name] = (st.st_mtime_ns, st.st_size, meta)
            items.append(dict(meta))
        if len(self._meta_cache) > len(seen_names):
            for stale in set(self._meta_cache) - seen_names:
                self._meta_cache.pop(stale, None)
        items.sort(key=lambda item: item["updated"], reverse=True)
        return items[:limit]


def to_ui_blocks(messages: list[dict]) -> list[dict]:
    """Converte mensagens internas nos blocos que a interface desenha (para reabrir conversas)."""
    blocks: list[dict] = []
    results = {m.get("tool_call_id"): m for m in messages if m["role"] == "tool"}
    for msg in messages:
        role = msg["role"]
        if role == "user":
            if (msg.get("content") or "").startswith("(Sistema:"):
                continue
            blocks.append({"kind": "user", "text": msg.get("content", ""), "images": msg.get("images") or []})
        elif role == "assistant":
            for call in msg.get("tool_calls") or []:
                result = results.get(call["id"], {})
                blocks.append({"kind": "tool", "name": call["name"], "args": call.get("arguments", {}),
                               "status": "error" if result.get("is_error") else "ok",
                               "result": (result.get("content") or "")[:1500], "images": result.get("images") or []})
            text = _TOOL_CALL.sub("", msg.get("content") or "").strip()
            if text:
                blocks.append({"kind": "assistant", "md": text})
    return blocks
