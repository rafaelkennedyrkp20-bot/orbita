"""Propostas de escrita. O arquivo no disco só muda quando a pessoa aplica.

Duas edições do mesmo arquivo se acumulam na proposta. Uma mudança externa
entre propor e aplicar vira conflito: nada é sobrescrito.
"""

from __future__ import annotations

import difflib
import json
import os
from datetime import datetime
from pathlib import Path

from agent.core.config import DATA_DIR

MAX_CHARS = 1_000_000
_STORE: "Store | None" = None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_disk(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), "cp1252"


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.is_file():
            return {"proposals": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"proposals": {}}
        if not isinstance(data.get("proposals"), dict):
            return {"proposals": {}}
        return data

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)

    def get(self, path: Path) -> dict | None:
        return self._data["proposals"].get(str(Path(path).resolve()))

    def propose_write(self, path: Path, content: str) -> dict:
        if len(content) > MAX_CHARS:
            raise ValueError("A proposta passa de 1 milhão de caracteres.")
        path = Path(path).resolve()
        key = str(path)
        current = self._data["proposals"].get(key)
        if current:
            current["proposed"] = content
            current["updated"] = _now()
            self._save()
            return current
        record = self._snapshot(path)
        record["proposed"] = content
        self._data["proposals"][key] = record
        self._save()
        return record

    def propose_edit(self, path: Path, old: str, new: str, replace_all: bool = False) -> str | None:
        path = Path(path).resolve()
        key = str(path)
        current = self._data["proposals"].get(key)
        if current:
            text, encoding = current["proposed"], current.get("encoding") or "utf-8"
        elif path.is_file():
            if b"\0" in path.read_bytes()[:4096]:
                return "Arquivo binário não entra na revisão."
            text, encoding = _read_disk(path)
        else:
            return f"Arquivo não encontrado: {path}"
        count = text.count(old)
        if count == 0:
            return "old_string não encontrado. Leia o arquivo de novo e copie o trecho exato."
        if count > 1 and not replace_all:
            return f"old_string aparece {count} vezes. Inclua mais contexto ou use replace_all."
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        if len(updated) > MAX_CHARS:
            return "A proposta passa de 1 milhão de caracteres."
        if current:
            current["proposed"] = updated
            current["updated"] = _now()
        else:
            record = self._snapshot(path)
            record["encoding"] = encoding
            record["proposed"] = updated
            self._data["proposals"][key] = record
        self._save()
        return None

    def _snapshot(self, path: Path) -> dict:
        exists = path.is_file()
        stat = path.stat() if exists else None
        text, encoding = ("", "utf-8")
        if exists and b"\0" not in path.read_bytes()[:4096]:
            text, encoding = _read_disk(path)
        return {
            "path": str(path),
            "encoding": encoding,
            "base_exists": exists,
            "base_mtime_ns": stat.st_mtime_ns if stat else None,
            "base_size": stat.st_size if stat else None,
            "base_text": text,
            "proposed": "",
            "created": _now(),
            "updated": _now(),
        }

    def diff(self, path: Path) -> str:
        record = self.get(path)
        if record is None:
            return ""
        before = (record.get("base_text") or "").splitlines()
        after = (record.get("proposed") or "").splitlines()
        lines = difflib.unified_diff(before, after, fromfile="disco", tofile="proposta", lineterm="")
        return "\n".join(list(lines)[:250])

    def read(self, path: Path) -> str | None:
        record = self.get(path)
        return None if record is None else record.get("proposed") or ""

    def list_for(self, workspace: Path) -> list[dict]:
        root = Path(workspace).resolve()
        rows = []
        for record in self._data["proposals"].values():
            try:
                Path(record["path"]).resolve().relative_to(root)
            except (OSError, ValueError):
                continue
            rows.append({
                "path": record["path"],
                "created": record.get("created") or "",
                "chars": len(record.get("proposed") or ""),
                "diff": self.diff(Path(record["path"]))[:4000],
            })
        return rows

    def apply(self, path: Path) -> str | None:
        path = Path(path).resolve()
        record = self._data["proposals"].get(str(path))
        if record is None:
            return "Não há proposta para este arquivo."
        if not self._matches_base(path, record):
            return "O arquivo mudou no disco desde a proposta. Nada foi sobrescrito."
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.get("proposed") or "", encoding=record.get("encoding") or "utf-8", newline="")
        self._data["proposals"].pop(str(path), None)
        self._save()
        return None

    def reject(self, path: Path) -> str | None:
        path = Path(path).resolve()
        if self._data["proposals"].pop(str(path), None) is None:
            return "Não há proposta para este arquivo."
        self._save()
        return None

    @staticmethod
    def _matches_base(path: Path, record: dict) -> bool:
        exists = path.is_file()
        if not record.get("base_exists"):
            return not exists
        if not exists:
            return False
        stat = path.stat()
        return stat.st_mtime_ns == record.get("base_mtime_ns") and stat.st_size == record.get("base_size")


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store(DATA_DIR / "staged_writes.json")
    return _STORE


def staged_block(settings, tool) -> str | None:
    """Terminal e MCP gravam por fora. Com a revisão ligada, esses caminhos ficam fechados."""
    if settings is None or settings.get("staged_writes") != "on":
        return None
    source = str(getattr(tool, "source", "") or "")
    if getattr(tool, "name", "") == "run_shell" or source.startswith("mcp:"):
        return ("A revisão antes de gravar está ligada. O terminal e o MCP ficam bloqueados "
                "porque podem alterar arquivos sem passar pela proposta.")
    return None
