"""Rolagem do chat na página real (QtWebEngine), com eventos de mouse do Qt."""

import json

import pytest

pytest.importorskip("PyQt6.QtWebEngineWidgets")

from PyQt6.QtCore import QEvent, QEventLoop, QObject, QPoint, QPointF, Qt, QTimer, QUrl, pyqtSignal, pyqtSlot  # noqa: E402
from PyQt6.QtGui import QMouseEvent  # noqa: E402
from PyQt6.QtWebChannel import QWebChannel  # noqa: E402
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from agent.gui import WEB_INDEX  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    # QtWebEngine não aceita destruir e recriar QApplication no mesmo processo.
    return QApplication.instance() or QApplication(["orbita-test"])


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


def test_middle_click_does_not_fling_the_conversation_to_the_top(qt_app):
    """Caso real: clique na roda ligava a autorrolagem do Chromium; ao mexer o mouse a conversa ia para o topo e a
    roda parava de responder ("rolagem travada lá em cima")."""
    app = qt_app
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


def test_cassandra_controls_in_real_desktop_page(tmp_path, qt_app):
    """Anexos distintos, modo temporário e login usam os contratos visíveis da página real."""
    class ApiStub(QObject):
        message = pyqtSignal(str)

        @pyqtSlot(result=str)
        def getState(self):
            return json.dumps({"settings": {"onboarded": True, "permission_mode": "auto", "theme": "dark"},
                               "profile": {"id": "geral", "name": "Assistente Geral"}, "temporary": True,
                               "providers": [], "team": [], "mcp": [], "conversations": []})

        @pyqtSlot(str, result=str)
        def openConversation(self, conversation_id):
            return json.dumps({"id": conversation_id, "title": "Conversa salva", "temporary": False,
                               "blocks": []})

    app = qt_app
    view = QWebEngineView()
    channel = QWebChannel(view.page())
    stub = ApiStub()
    channel.registerObject("api", stub)
    view.page().setWebChannel(channel)
    view.resize(1440, 900)
    loaded = QEventLoop()
    view.loadFinished.connect(lambda _ok: loaded.quit())
    view.load(QUrl.fromLocalFile(str(WEB_INDEX)))
    view.show()
    QTimer.singleShot(15000, loaded.quit)
    loaded.exec()
    _wait(600)
    assert _js(view, "document.querySelector('#temporary-btn').getAttribute('aria-pressed')") == "true"
    assert _js(view, "document.querySelector('#temporary-btn svg path').getAttribute('d').length") > 10
    _js(view, "addAttachments(['C:/projeto/nota.txt', 'C:/projeto/foto.png', 'C:/projeto/pasta']);")
    assert _js(view, "document.querySelectorAll('#attachments .att').length") == 3
    assert _js(view, "document.querySelectorAll('#attachments img').length") == 1
    assert _js(view, "document.querySelector('#input').value") == ""
    _js(view, "openConversation('antiga');")
    _wait(200)
    assert _js(view, "document.querySelector('#temporary-btn').getAttribute('aria-pressed')") == "false"
    assert _js(view, "document.querySelector('#conv-title').textContent") == "Conversa salva"
    _js(view, "settingsSection='deepseek'; go('settings');")
    _wait(200)
    assert _js(view, "document.querySelector('#deepseek-login').textContent.includes('Entrar')")
    assert _js(view, "document.querySelector('#page-settings').classList.contains('active')")
    assert view.grab().save(str(tmp_path / "cassandra-desktop.png"))
    view.close()
    app.processEvents()
