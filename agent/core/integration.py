"""
integration.py — Confere se as partes feitas pela equipe se encaixam (sites: HTML × CSS × JS).

Agentes em paralelo sem um contrato combinado inventam nomes diferentes para as mesmas coisas
(o HTML usa `.site-header`, o CSS estiliza `.header`). Depois da delegação, esta checagem compara
os arquivos que mudaram e devolve ao agente principal o que não bate, para ele corrigir na hora.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

SKIP = {"node_modules", ".git", "venv", ".venv", "dist", "build", "__pycache__", "AppData", "Application Data",
        "Library", "site-packages"}   # "data/" e "assets/" são comuns em sites: entram na checagem
HTML_CLASS = re.compile(r"""\bclass\s*=\s*["']([^"']+)["']""", re.I)
HTML_ID = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""", re.I)
CSS_BLOCK = re.compile(r"/\*.*?\*/", re.S)
CSS_SELECTOR_PART = re.compile(r"([^{}]+)\{")
CSS_CLASS = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
CSS_ID = re.compile(r"#(-?[_a-zA-Z][\w-]*)")
JS_CLASS = re.compile(r"""(?:classList\.(?:add|toggle|remove|contains)\(\s*|className\s*[+]?=\s*)["'`]([^"'`]+)["'`]""")
JS_QUERY = re.compile(r"""(?:querySelector(?:All)?|closest|matches)\(\s*["'`]([^"'`]+)["'`]""")
JS_ID = re.compile(r"""getElementById\(\s*["'`]([^"'`]+)["'`]""")
# Elementos que o próprio JS cria: el.id = "x" / setAttribute("id", "x") / HTML montado em string.
JS_ID_ASSIGN = re.compile(r"""(?:\.id\s*=\s*|setAttribute\(\s*["']id["']\s*,\s*)["'`]([\w-]+)["'`]""")
MAX_LIST = 25


def changed_web_files(root: Path, since: float, max_depth: int = 4, budget: float = 2.0,
                      max_files: int = 30000) -> dict[str, list[Path]]:
    """Arquivos web alterados desde `since`. Limitado (profundidade, tempo, quantidade): sem projeto
    aberto a pasta de trabalho é a pasta do usuário inteira."""
    import time
    found: dict[str, list[Path]] = {"html": [], "css": [], "js": []}
    deadline, seen, root_depth = time.time() + budget, 0, len(Path(root).parts)
    for base, dirs, files in os.walk(root):
        depth = len(Path(base).parts) - root_depth
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".") and depth < max_depth]
        seen += len(files)
        if seen > max_files or time.time() > deadline:
            break
        for name in files:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            kind = {"html": "html", "htm": "html", "css": "css", "js": "js", "mjs": "js"}.get(ext)
            if not kind or name.endswith(".min.js") or name.endswith(".min.css"):
                continue
            path = Path(base) / name
            try:
                if path.stat().st_mtime >= since:
                    found[kind].append(path)
            except OSError:
                continue
    return found


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _js_selectors(text: str) -> tuple[set[str], set[str]]:
    classes, ids = set(), set()
    for match in JS_CLASS.finditer(text):
        classes.update(match.group(1).split())
    for match in JS_QUERY.finditer(text):
        classes.update(CSS_CLASS.findall(match.group(1)))
        ids.update(CSS_ID.findall(match.group(1)))
    ids.update(JS_ID.findall(text))
    return classes, ids


def check(html: list[Path], css: list[Path], js: list[Path]) -> str:
    """Relatório curto do que não se encaixa; vazio se estiver tudo coerente (ou se não houver HTML+CSS)."""
    if not html or not css:
        return ""
    html_classes, html_ids = set(), set()
    for path in html:
        text = _read(path)
        for match in HTML_CLASS.finditer(text):
            if "{{" in match.group(1) or "${" in match.group(1):
                continue   # classes geradas por template
            html_classes.update(match.group(1).split())
        html_ids.update(m.strip() for m in HTML_ID.findall(text))
    css_classes, css_ids = set(), set()
    for path in css:
        text = CSS_BLOCK.sub("", _read(path))
        for selector in CSS_SELECTOR_PART.findall(text):
            if selector.strip().startswith("@"):
                continue
            selector = re.sub(r"url\([^)]*\)", "", selector)
            css_classes.update(CSS_CLASS.findall(selector))
            css_ids.update(CSS_ID.findall(selector))
    js_classes, js_ids, built_classes, built_ids = set(), set(), set(), set()
    for path in js:
        text = _read(path)
        c, i = _js_selectors(text)
        js_classes |= c
        js_ids |= i
        for match in HTML_CLASS.finditer(text):   # HTML montado em template string (cardJogo...)
            built_classes.update(w for w in match.group(1).split() if re.fullmatch(r"-?[_a-zA-Z][\w-]*", w))
        built_ids.update(m.strip() for m in HTML_ID.findall(text) if re.fullmatch(r"[\w-]+", m.strip()))
        built_ids.update(JS_ID_ASSIGN.findall(text))

    page_classes = html_classes | built_classes   # classes que aparecem na página
    used = page_classes | js_classes
    unstyled = sorted(c for c in page_classes - css_classes if not c.startswith(("js-", "is-", "has-")))
    dead = sorted(css_classes - used)
    js_missing_ids = sorted(js_ids - html_ids - built_ids)
    js_missing_classes = sorted(c for c in js_classes - page_classes - css_classes)

    problems = []
    if unstyled and len(unstyled) >= 3:
        problems.append(f"- {len(unstyled)} classes do HTML sem nenhum estilo no CSS: {_fmt(unstyled)}")
    # CSS com variantes que a página ainda não usa (.btn-secundario...) é normal; só vira problema
    # junto com classes do HTML sem estilo — aí é sinal de que cada lado usou um nome.
    if dead and len(dead) >= 3 and len(unstyled) >= 3:
        problems.append(f"- {len(dead)} classes do CSS que não aparecem no HTML nem no JS: {_fmt(dead)}")
    if js_missing_ids:
        problems.append(f"- IDs que o JS procura e não existem no HTML: {_fmt(js_missing_ids, '#')}")
    if js_missing_classes:
        problems.append(f"- Classes que o JS usa e não existem em lugar nenhum: {_fmt(js_missing_classes)}")
    if not problems:
        return ""
    overlap = len(html_classes & css_classes)
    hint = (" Parece que HTML e CSS usaram nomes diferentes para os mesmos componentes: escolha UM contrato "
            "(o do CSS, se ele já estiver completo) e alinhe o outro arquivo a ele." if overlap < len(unstyled) else "")
    files = ", ".join(p.name for p in html + css + js)
    return ("## Checagem automática de integração (HTML × CSS × JS)\n"
            f"Arquivos alterados pela equipe: {files}.\n" + "\n".join(problems) + "\n"
            "Corrija antes de declarar pronto." + hint)


def _fmt(items: list[str], prefix: str = ".") -> str:
    shown = ", ".join(prefix + i for i in items[:MAX_LIST])
    return shown + (f" … (+{len(items) - MAX_LIST})" if len(items) > MAX_LIST else "")


def check_workspace(root: Path, since: float) -> str:
    files = changed_web_files(root, since)
    return check(files["html"], files["css"], files["js"])
