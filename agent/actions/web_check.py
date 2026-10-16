"""
web_check.py — Testa uma página web num navegador invisível (Chromium do Qt, fora da tela do usuário).

Roda como processo separado (`python -m agent.actions.web_check ...`) porque o Qt só aceita um
navegador por aplicação e as ferramentas do agente rodam em outras threads. Devolve JSON com erros
de JavaScript, arquivos que não carregaram, links locais quebrados, conteúdo vazando para os lados
(desktop e celular), o resultado de um script opcional (ex.: clicar em "adicionar ao carrinho") e,
se pedido, uma captura pequena.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROBE = """(() => {
  const broken = [...document.querySelectorAll('link[rel=stylesheet]')].filter(l => !l.sheet).map(l => l.getAttribute('href'))
    .concat([...document.querySelectorAll('img')].filter(i => i.complete && i.naturalWidth === 0 && i.getAttribute('src')).map(i => i.getAttribute('src')));
  const links = [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))
    .filter(h => h && !/^(https?:|mailto:|tel:|#|javascript:)/i.test(h));
  return JSON.stringify({title: document.title, overflowX: Math.max(0, document.documentElement.scrollWidth - innerWidth),
    brokenResources: broken, localLinks: [...new Set(links)].slice(0, 60),
    textChars: document.body ? document.body.innerText.length : 0,
    buttons: document.querySelectorAll('button, .btn, [role=button]').length});
})()"""


def run(target: str, script: str = "", shot: str = "", widths=(1366, 390)) -> dict:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    from PyQt6.QtCore import QTimer, QUrl
    from PyQt6.QtWebEngineCore import QWebEnginePage
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWidgets import QApplication

    url = QUrl(target) if target.startswith(("http://", "https://")) else QUrl.fromLocalFile(str(Path(target).resolve()))
    base = None if target.startswith(("http://", "https://")) else Path(target).resolve().parent
    result: dict = {"target": target, "console_errors": [], "views": {}}
    app = QApplication.instance() or QApplication(sys.argv)

    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):  # type: ignore[override]
            if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
                name = Path(QUrl(source).toLocalFile()).name or source
                result["console_errors"].append(f"{name}:{line} {message}"[:300])

    view = QWebEngineView()
    page = Page(view)
    view.setPage(page)
    queue = list(widths)

    def next_view():
        if not queue:
            app.quit()
            return
        width = queue.pop(0)
        view.resize(width, 900)
        view.show()
        page.load(url)

    def loaded(ok):
        width = view.width()
        if not ok:
            result["views"][str(width)] = {"loaded": False}
            QTimer.singleShot(10, next_view)
            return

        def after_probe(raw):
            data = json.loads(raw) if raw else {}
            data["loaded"] = True
            result["views"][str(width)] = data
            first = width == widths[0]
            if first and script:
                # runJavaScript não espera Promises: o script guarda o resultado na página e a gente consulta.
                page.runJavaScript("window.__orbita = null; (async () => { " + script + " })().then("
                                   "v => window.__orbita = JSON.stringify({ok: true, value: v === undefined ? null : v}),"
                                   " e => window.__orbita = JSON.stringify({ok: false, error: String(e)}));")
                poll(0)
            else:
                finish_view()

        def poll(tries):
            def got(raw):
                if raw:
                    result["script"] = json.loads(raw)
                    QTimer.singleShot(300, finish_view)
                elif tries >= 50:
                    result["script"] = {"ok": False, "error": "o script não terminou em 10 s"}
                    finish_view()
                else:
                    QTimer.singleShot(200, lambda: poll(tries + 1))
            page.runJavaScript("window.__orbita", got)

        def finish_view():
            if shot and width == widths[0]:
                view.grab().scaledToWidth(min(width, 1000)).save(shot)
                result["screenshot"] = shot
            QTimer.singleShot(10, next_view)

        QTimer.singleShot(900, lambda: page.runJavaScript(PROBE, after_probe))

    page.loadFinished.connect(loaded)
    QTimer.singleShot(20000, app.quit)   # trava de segurança
    QTimer.singleShot(10, next_view)
    app.exec()
    if base is not None:
        links = set()
        for data in result["views"].values():
            links.update(data.get("localLinks") or [])
        result["broken_links"] = sorted(h for h in links
                                        if not (base / h.split("#")[0].split("?")[0]).exists())
    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("target")
    parser.add_argument("--script", default="")
    parser.add_argument("--shot", default="")
    args = parser.parse_args()
    print(json.dumps(run(args.target, args.script, args.shot), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
