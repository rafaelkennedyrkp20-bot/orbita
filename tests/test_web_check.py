"""check_web_page de verdade (Chromium invisível): erros, links quebrados, celular e script."""

import pytest

pytest.importorskip("PyQt6.QtWebEngineWidgets")

from agent.core.tools import ToolContext  # noqa: E402

PAGE = """<!doctype html><html><head><title>Teste</title><link rel="stylesheet" href="falta.css">
<style>.largo{width:600px} @media (max-width:500px){ body{background:red} }</style></head>
<body><a href="nao-existe.html">x</a><div class="largo" id="w" style="height:20px"></div><button>ok</button>
<script>document.querySelector('#nada').textContent = 1;</script></body></html>"""


def test_reports_errors_broken_links_and_phone_overflow(brain, tmp_path):
    (tmp_path / "index.html").write_text(PAGE, encoding="utf-8")
    result = brain.registry.get("check_web_page").run({"path": "index.html"}, ToolContext(workspace=tmp_path))
    assert result.is_error and "Erros de JavaScript: 1" in result.text
    assert "falta.css" in result.text and "nao-existe.html" in result.text
    assert "Celular (390px): conteúdo vaza" in result.text and "Desktop (1366px): sem vazamento" in result.text


def test_script_and_screenshot_run_at_phone_width(brain, tmp_path):
    (tmp_path / "index.html").write_text("<title>t</title><body>oi</body>", encoding="utf-8")
    result = brain.registry.get("check_web_page").run(
        {"path": "index.html", "width": 390, "screenshot": True,
         "script": "await new Promise(r => setTimeout(r, 50)); return innerWidth"},
        ToolContext(workspace=tmp_path))
    assert "Script: ok → 390" in result.text and result.images
