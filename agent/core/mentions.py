"""
mentions.py — `@arquivo` na mensagem: autocompletar e anexar o conteúdo citado.

Apontar o arquivo dá resposta melhor e mais barata do que deixar o modelo procurar: o
conteúdo já vai junto da mensagem e economiza uma rodada de ferramenta (o que mais pesa
em modelo local). Arquivo grande ou binário só tem o caminho citado.

Sintaxe: `@caminho/relativo.py` ou `@"pasta com espaço/arquivo.txt"`.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from agent.core.checkpoints import EXCLUDES

MAX_LISTED = 20000
INLINE_FILE_CHARS = 12000
INLINE_TOTAL_CHARS = 30000
_SKIP = {d.rstrip("/") for d in EXCLUDES if d.endswith("/")}
_MENTION = re.compile(r'(?<![\w/\\])@(?:"([^"\n]+)"|([^\s"@]+))')
_cache: dict[str, tuple[float, list[tuple[str, float]]]] = {}


def list_files(workspace: Path, ttl: float = 20.0) -> list[tuple[str, float]]:
    """(caminho relativo com '/', data de modificação) de todos os arquivos, com cache curto."""
    key = str(workspace)
    cached = _cache.get(key)
    if cached and time.time() - cached[0] < ttl:
        return cached[1]
    files: list[tuple[str, float]] = []
    for base, dirs, names in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP and not d.startswith(".")]
        for name in names:
            path = os.path.join(base, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            files.append((os.path.relpath(path, workspace).replace("\\", "/"), mtime))
            if len(files) >= MAX_LISTED:
                break
        if len(files) >= MAX_LISTED:
            break
    _cache[key] = (time.time(), files)
    return files


def search(workspace: Path, query: str, limit: int = 12) -> list[str]:
    """Melhores caminhos para o que foi digitado depois do @ (vazio = mais recentes)."""
    files = list_files(workspace)
    query = query.strip().lower().replace("\\", "/")
    if not query:
        return [path for path, _ in sorted(files, key=lambda f: -f[1])[:limit]]
    scored = []
    for path, mtime in files:
        low = path.lower()
        name = low.rsplit("/", 1)[-1]
        if name.startswith(query):
            rank = 0
        elif query in name:
            rank = 1
        elif query in low:
            rank = 2
        else:
            continue
        scored.append((rank, len(path), -mtime, path))
    return [item[3] for item in sorted(scored)[:limit]]


def _inside(workspace: Path, rel: str) -> Path | None:
    try:
        root = workspace.resolve()
        target = (root / rel).resolve()
    except (OSError, ValueError):
        return None
    if target != root and root not in target.parents:
        return None
    return target if target.exists() else None


def _read_text(path: Path) -> str | None:
    try:
        raw = path.read_bytes()[: INLINE_FILE_CHARS * 4 + 1]
    except OSError:
        return None
    if b"\0" in raw[:4096]:
        return None
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def expand(text: str, workspace: Path) -> str:
    """Anexa ao fim da mensagem o conteúdo dos arquivos citados com @ (texto do usuário intacto)."""
    seen: list[tuple[str, Path]] = []
    for match in _MENTION.finditer(text):
        rel = (match.group(1) or match.group(2)).rstrip(".,;:!?)")
        target = _inside(workspace, rel)
        if target is not None and all(target != p for _, p in seen):
            seen.append((rel.replace("\\", "/"), target))
    if not seen:
        return text
    blocks, listed, used = [], [], 0
    for rel, target in seen:
        if target.is_dir():
            listed.append(f"- {rel}/ (pasta)")
            continue
        content = _read_text(target)
        if content is None or len(content) > INLINE_FILE_CHARS or used + len(content) > INLINE_TOTAL_CHARS:
            listed.append(f"- {rel} (não anexado: grande ou binário — leia com read_file se precisar)")
            continue
        used += len(content)
        fence = "````" if "```" in content else "```"
        blocks.append(f"### {rel}\n{fence}{target.suffix.lstrip('.')}\n{content.rstrip()}\n{fence}")
    parts = [text, "", "---", "Arquivos citados pelo usuário (caminhos relativos à pasta do projeto"
             + (", conteúdo atual já anexado abaixo — não precisa ler de novo):" if blocks else "):")]
    parts += listed + blocks
    return "\n".join(parts)
