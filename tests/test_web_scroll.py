"""Rolagem do chat na página real (QtWebEngine), com eventos de mouse do Qt."""

import json

import pytest

pytest.importorskip("PyQt6.QtWebEngineWidgets")

from PyQt6.QtCore import QEvent, QEventLoop, QObject, QPoint, QPointF, Qt, QTimer, QUrl  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWebChannel import QWebChannel  # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from agent.gui import WEB_INDEX  # noqa: E402


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _js(view: QWebEngineView, code: str):
    result, loop = [], QEventLoop()
    view.page().runJavaScript(code, lambda r: (result.append(r), loop.quit()))
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    return result[0] if result else None


def _mouse(view: QWebEngineView, kind: QEvent.Type, x: int, y: int) -> None:
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.MiddleButton
    held = Qt.MouseButton.MiddleButton if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton
    QApplication.sendEvent(view.focusProxy(), QMouseEvent(kind, QPointF(x, y), QPointF(view.mapToGlobal(QPoint(x, y))),
                                                          button, held, Qt.KeyboardModifier.NoModifier))


def test_middle_click_does_not_fling_the_conversation_to_the_top():
    """Caso real: clique na roda ligava a autorrolagem do Chromium; ao mexer o mouse a conversa ia para o topo e a
    roda parava de responder ("rolagem travada lá em cima")."""
    app = QApplication.instance() or QApplication(["orbita-test"])   # sem argv[0] o Chromium cai no Windows
    view = QWebEngineView()
    channel = QWebChannel(view.page())
    stub = QObject()
    channel.registerObject("api", stub)   # a página real só liga os eventos quando o canal existe
    view.page().setWebChannel(channel)
    view.resize(1200, 800)
    loaded = QEventLoop()
    view.loadFinished.connect(lambda ok: loaded.quit())
    view.load(QUrl.fromLocalFile(str(WEB_INDEX)))
    view.show()
    QTimer.singleShot(15000, loaded.quit)
    loaded.exec()
    _wait(500)

    top = _js(view, "(() => { const m = document.querySelector('#messages'); m.innerHTML = '<div style=\"height:20000px\"></div>';"
                    " m.scrollTop = 10000; return Math.round(m.scrollTop); })()")
    assert top == 10000
    box = _js(view, "JSON.stringify(document.querySelector('#messages').getBoundingClientRect())")
    assert box
    rect = json.loads(box)
    x, y = int(rect["x"] + rect["width"] / 2), int(rect["y"] + rect["height"] / 2)
    _mouse(view, QEvent.Type.MouseButtonPress, x, y)
    _mouse(view, QEvent.Type.MouseButtonRelease, x, y)
    for dy in (20, 150, 250):
        _mouse(view, QEvent.Type.MouseMove, x, y - dy)
        _wait(300)
    assert _js(view, "Math.round(document.querySelector('#messages').scrollTop)") == 10000
    view.close()
    app.processEvents()
