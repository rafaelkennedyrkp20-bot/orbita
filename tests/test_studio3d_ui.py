"""Estúdio 3D na página real, sem depender de motores instalados ou alterar preferências."""

import json

import pytest

pytest.importorskip("PyQt6.QtWebEngineWidgets")

from PyQt6.QtCore import QEventLoop, QObject, QTimer, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication

from agent.gui import WEB_INDEX

# QtWebEngine não permite recriar QApplication no mesmo processo. A referência
# permanece viva para os próximos módulos gráficos da suíte.
_qt_app = None


def wait(ms=120):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js(view, code):
    result, loop = [], QEventLoop()
    view.page().runJavaScript(code, lambda value: (result.append(value), loop.quit()))
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    return result[0] if result else None


class StudioApi(QObject):
    message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.saved = None

    @pyqtSlot(result=str)
    def getState(self):
        return json.dumps({
            "settings": {"onboarded": True, "theme": "dark", "permission_mode": "auto"},
            "profile": {"id": "geral", "name": "Assistente Geral"}, "model_label": "Moonshot · Kimi",
            "providers": [], "team": [], "mcp": [], "conversations": [], "toolbox": [],
            "skills": [{"name": "modelagem-3d", "description": "Cena e materiais", "origin": "projeto"},
                       {"name": "revisão", "description": "Código", "origin": "projeto"}],
            "studio3d": {"unreal": {"enabled": False, "url": "http://127.0.0.1:30010",
                                     "state": "disabled", "message": "Integração desligada."},
                         "blender": {"path": "", "state": "missing", "message": "Não encontrado."}},
        })

    @pyqtSlot(str, result=str)
    def studio3dConfigure(self, raw):
        self.saved = json.loads(raw)
        return json.dumps({"accepted": True})

    @pyqtSlot(result=str)
    def studio3dProbe(self):
        return json.dumps({"accepted": True})


def test_studio_controls_keep_drafts_escape_status_and_submit(tmp_path):
    global _qt_app
    _qt_app = QApplication.instance() or QApplication(["orbita-studio-test"])
    app = _qt_app
    view = QWebEngineView()
    channel = QWebChannel(view.page())
    api = StudioApi()
    channel.registerObject("api", api)
    view.page().setWebChannel(channel)
    view.resize(1280, 900)
    loaded = QEventLoop()
    view.loadFinished.connect(lambda _ok: loaded.quit())
    view.load(QUrl.fromLocalFile(str(WEB_INDEX)))
    view.show()
    QTimer.singleShot(15000, loaded.quit)
    loaded.exec()
    wait(400)
    try:
        js(view, "go('connections')")
        assert js(view, "document.querySelector('#studio-unreal-url') !== null")
        js(view, "document.querySelector('#studio-unreal-url').value='http://127.0.0.1:30123';"
                 "document.querySelector('#studio-unreal-url').dispatchEvent(new Event('input'));")
        js(view, "onEvent({type:'mcp',servers:[]})")
        assert js(view, "document.querySelector('#studio-unreal-url').value") == "http://127.0.0.1:30123"
        js(view, "document.querySelector('#studio-unreal-enabled').checked=true;"
                 "document.querySelector('#studio-unreal-enabled').dispatchEvent(new Event('change'));"
                 "document.querySelector('#studio-save').click();")
        wait()
        assert api.saved == {"unreal": {"enabled": True, "url": "http://127.0.0.1:30123"},
                             "blender": {"path": ""},
                             "unity": {"enabled": False, "url": "http://127.0.0.1:30012", "project_path": ""}}
        assert js(view, "document.querySelector('#studio-save').disabled")
        js(view, "onEvent({type:'studio3d',status:{unreal:{enabled:true,url:'http://127.0.0.1:30123',"
                 "state:'available',message:'<img src=x onerror=alert(1)>'},blender:{path:'',state:'missing'}}})")
        assert js(view, "document.querySelector('#studio-save').disabled") is False
        assert js(view, "document.querySelector('#studio-panel').textContent.includes('<img src=x')")
        assert js(view, "document.querySelectorAll('#studio-panel img').length") == 0
        js(view, "document.querySelector('[data-conn-tab=skills]').click();"
                 "document.querySelector('#conn-search').value='modelagem';"
                 "document.querySelector('#conn-search').dispatchEvent(new Event('input'));")
        assert js(view, "document.querySelectorAll('#skills-grid .tile:not([hidden])').length") == 1
        js(view, "document.querySelector('[data-conn-tab=studio]').click();")
        wait(350)
        assert js(view, "document.querySelector('#page-connections').classList.contains('active')")
        assert js(view, "getComputedStyle(document.querySelector('#conn-studio')).display") != "none"
        assert js(view, "document.querySelectorAll('#studio-panel article:not([hidden])').length") == 4
        assert js(view, "document.querySelector('#conn-search').closest('.search').hidden")
        assert view.grab().save(str(tmp_path / "studio-dark.png"))
        js(view, "applyTheme('light')")
        wait(350)
        assert view.grab().save(str(tmp_path / "studio-light.png"))
        view.resize(720, 780)
        wait()
        assert js(view, "document.querySelector('#conn-body').scrollWidth <= document.querySelector('#conn-body').clientWidth")
    finally:
        view.close()
        app.processEvents()


def test_diagnostics_bridge_runs_off_ui_and_rejects_overlap(monkeypatch):
    import threading
    from types import SimpleNamespace
    from agent import gui

    started, release, delivered = threading.Event(), threading.Event(), threading.Event()
    events = []

    def probe():
        started.set()
        assert release.wait(3)
        return {"unreal": {"state": "available"}}

    def push(payload):
        events.append(payload)
        delivered.set()

    monkeypatch.setattr(gui.studio3d, "get_studio3d", lambda: SimpleNamespace(probe=probe))
    api = SimpleNamespace(win=SimpleNamespace(busy=False), _studio_lock=threading.Lock(), push=push)
    result = gui.Api._studio_work(api)
    assert json.loads(result)["accepted"]
    try:
        assert started.wait(1)
        assert "error" in json.loads(gui.Api._studio_work(api))
    finally:
        release.set()
    assert delivered.wait(2)
    assert events == [{"type": "studio3d", "status": {"unreal": {"state": "available"}}}]
    api.win.busy = True
    assert "error" in json.loads(gui.Api._studio_work(api))
