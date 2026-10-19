"""Índice pequeno de símbolos; arquivos do projeto continuam sendo dados externos."""

from __future__ import annotations

import ast
import fnmatch
import itertools
import json
import os
import re
import time
from pathlib import Path

_EXCLUDED = {"data", "models", "venv", "env", "node_modules", "__pycache__", "build", "dist"}
_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".ts", ".tsx"}
_SYMBOL = re.compile(r"(?:\b(?:function|class|interface|type|enum)\s+|\b(?:const|let)\s+)([A-Za-z_$][\w$]*)")
_IMPORT = re.compile(r"(?:\bfrom\s*|\bimport\s*|\brequire\s*\()['\"]([\w./@-]+)['\"]")


def _linked(path: Path) -> bool:
    """Junctions do Windows também são reparse points, mesmo sem is_symlink()."""
    stat = path.lstat()
    return path.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400)


def _symbols(source: str, suffix: str) -> tuple[list[str], list[str]]:
    if suffix == ".py":
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError):
            return [], []
        symbols, imports = [], []
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(node.name)
            elif isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return sorted(set(symbols))[:20], sorted(set(imports))[:12]
    return sorted(set(_SYMBOL.findall(source)))[:20], sorted(set(_IMPORT.findall(source)))[:12]


def _ignored(relative: str, rules: list[tuple[str, str]], directory: bool) -> bool:
    ignored = False
    for base, rule in rules:
        if base and not relative.startswith(base + "/"):
            continue
        value = relative[len(base) + 1:] if base else relative
        negate = rule.startswith("!")
        pattern = rule[1:] if negate else rule
        if pattern.endswith("/") and not directory:
            continue
        pattern = pattern.rstrip("/")
        target = value if "/" in pattern.lstrip("/") or pattern.startswith("/") else value.rsplit("/", 1)[-1]
        if fnmatch.fnmatchcase(target, pattern.lstrip("/")):
            ignored = not negate
    return ignored


class RepoMap:
    """Cache por sessão: revalida metadados, relê somente fontes alteradas.

    Limites também valem para entradas ignoradas, bytes em cache e arquivos grandes.
    .gitignore suporta globs, padrões relativos, diretórios e negação simples.
    """

    def __init__(self, root: Path, *, max_files=160, max_bytes=512_000, max_seconds=0.15):
        self.root = Path(root).resolve()
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.max_seconds = max_seconds
        self._cache: dict[str, tuple[tuple, dict]] = {}

    def _index(self) -> list[dict]:
        deadline = time.monotonic() + self.max_seconds
        cache, records = {}, []
        stack = [(self.root, [])]
        visited = used_bytes = 0
        while stack and visited < 3000 and len(records) < self.max_files:
            if time.monotonic() >= deadline:
                break
            folder, inherited = stack.pop()
            rules = list(inherited)
            try:
                ignore = folder / ".gitignore"
                if ignore.is_file() and not _linked(ignore):
                    with ignore.open(encoding="utf-8", errors="replace") as handle:
                        lines = handle.read(16_384).splitlines()
                    base = folder.relative_to(self.root).as_posix()
                    base = "" if base == "." else base
                    rules.extend((base, line.strip()) for line in lines if line.strip() and not line.startswith("#"))
                with os.scandir(folder) as entries:
                    items = sorted(itertools.islice(entries, 3000 - visited), key=lambda entry: entry.name)
            except OSError:
                continue
            directories = []
            for entry in items:
                visited += 1
                if time.monotonic() >= deadline or len(records) >= self.max_files:
                    break
                path = Path(entry.path)
                name = entry.name.lower()
                if name.startswith((".", "secrets", "credentials")) or name in _EXCLUDED:
                    continue
                try:
                    if _linked(path) or not path.resolve().is_relative_to(self.root):
                        continue
                    directory = entry.is_dir(follow_symlinks=False)
                    relative = path.relative_to(self.root).as_posix()
                    if _ignored(relative, rules, directory):
                        continue
                    if directory:
                        directories.append((path, rules))
                        continue
                    if path.suffix.lower() not in _SUFFIXES or not entry.is_file(follow_symlinks=False):
                        continue
                    stat = path.stat()
                    if stat.st_size > 64_000 or used_bytes + stat.st_size > self.max_bytes:
                        continue
                    used_bytes += stat.st_size
                    signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
                    old = self._cache.get(relative)
                    if old is not None and old[0] == signature:
                        record = old[1]
                    else:
                        # Revalida o caminho imediatamente antes da leitura.
                        if _linked(path) or not path.resolve().is_relative_to(self.root):
                            continue
                        with path.open("rb") as handle:
                            raw = handle.read(min(64_000, self.max_bytes - used_bytes + stat.st_size) + 1)
                        if len(raw) > stat.st_size or len(raw) > 64_000:
                            continue
                        symbols, imports = _symbols(raw.decode("utf-8", errors="replace"), path.suffix.lower())
                        record = {"path": relative, "symbols": symbols, "imports": imports}
                    cache[relative] = (signature, record)
                    records.append(record)
                except (OSError, ValueError):
                    continue
            stack.extend(reversed(directories))
        self._cache = cache
        return records

    def render(self, *, query="", max_chars=2200) -> str:
        records = self._index()
        words = set(re.findall(r"[a-zA-Z]{3,}", query.lower().replace("_", " ")))
        imported = {value.rsplit("/", 1)[-1].rsplit(".", 1)[-1] for row in records for value in row["imports"]}

        def rank(row):
            text = " ".join([row["path"], *row["symbols"]]).lower()
            return (-sum(word in text for word in words), -int(Path(row["path"]).stem in imported), row["path"])

        selected = []
        for record in sorted(records, key=rank):
            candidate = json.dumps([*selected, record], ensure_ascii=True, separators=(",", ":"))
            if len(candidate) <= max_chars:
                selected.append(record)
        return json.dumps(selected, ensure_ascii=True, separators=(",", ":")) if selected else ""
