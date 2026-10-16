"""
render.py — Markdown → HTML seguro para a interface web, e texto limpo para a voz.

Segurança: a página tem ponte com o Python (QWebChannel). Por isso HTML cru vindo do modelo,
de páginas web ou de MCP é sempre ESCAPADO (os processadores de HTML do Markdown são removidos),
links `javascript:` são neutralizados e a página ainda roda com Content-Security-Policy restrita.
"""

from __future__ import annotations

import re
from html import escape

import markdown as _markdown
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name, guess_lexer
from pygments.util import ClassNotFound

_FENCE = re.compile(r"```([\w+#.-]*)[^\n]*\n(.*?)(?:```|\Z)", re.DOTALL)
_FORMATTER = HtmlFormatter(nowrap=True, classnames="hl")
_UNSAFE_HREF = re.compile(r'(href|src)="\s*(javascript|vbscript|data):[^"]*"', re.IGNORECASE)


def pygments_css() -> str:
    return HtmlFormatter(style="github-dark").get_style_defs(".code pre")


def _md_engine() -> _markdown.Markdown:
    engine = _markdown.Markdown(extensions=["tables", "sane_lists", "nl2br"], output_format="html")
    engine.preprocessors.deregister("html_block")     # HTML cru vira texto
    engine.inlinePatterns.deregister("html")
    return engine


_ENGINE = _md_engine()


def _md(text: str) -> str:
    if not text.strip():
        return ""
    _ENGINE.reset()
    html = _ENGINE.convert(text)
    html = _UNSAFE_HREF.sub(r'\1="#"', html)
    return html.replace("<a href=", '<a target="_blank" href=')


def _code_html(code: str, lang: str) -> str:
    try:
        lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
    except ClassNotFound:
        lexer = TextLexer()
    body = highlight(code.rstrip("\n"), lexer, _FORMATTER)
    return (f'<div class="code"><div class="code-h"><span>{escape(lang or "código")}</span>'
            f'<button class="copy" data-copy>Copiar</button></div><pre><code>{body}</code></pre></div>')


def markdown_html(text: str) -> str:
    """Markdown → HTML (aceita bloco de código não fechado durante o streaming)."""
    pieces, last = [], 0
    for match in _FENCE.finditer(text or ""):
        pieces.append(_md(text[last:match.start()]))
        pieces.append(_code_html(match.group(2), match.group(1).lower()))
        last = match.end()
    pieces.append(_md((text or "")[last:]))
    return "".join(pieces)


def speech_text(markdown_text: str, limit: int = 700) -> str:
    """Texto adequado para falar: sem código, links ou marcações; curto."""
    text = _FENCE.sub(" (código mostrado na tela) ", markdown_text or "")
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[`*_#>|\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        cut = text[:limit]
        text = cut[:cut.rfind(".") + 1] or cut
    return text
