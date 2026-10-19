"""Auditoria de políticas: modo somente local (#11) e risco do clipboard (#13)."""

import subprocess

from agent.core.agent_loop import AgentSession
from agent.core.local_policy import tool_block


def _session(brain, approve, mode="auto"):
    brain.settings.set("permission_mode", mode, save=False)
    return AgentSession(brain, brain.profiles.get("geral"), "fake", "m1", approve=approve)


def _last_tool_message(session):
    return [m for m in session.messages if m.get("role") == "tool"][-1]


# ── #11: check_web_page no modo somente local ────────────────


def test_local_only_blocks_check_web_page(brain):
    brain.settings.set("execution_policy", "local_only", save=False)
    assert tool_block(brain.settings, brain.registry.get("check_web_page"))
    brain.settings.set("execution_policy", "open", save=False)
    assert tool_block(brain.settings, brain.registry.get("check_web_page")) is None


def test_local_only_never_starts_browser_for_remote_page(brain, monkeypatch):
    started = []

    def fake_browser(*args, **kwargs):
        started.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=b'{"ok": true}', stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_browser)
    monkeypatch.setattr(subprocess, "Popen", fake_browser)
    brain.settings.set("execution_policy", "local_only", save=False)
    session = _session(brain, approve=lambda r: "yes", mode="livre")
    session._execute([{"id": "c1", "name": "check_web_page",
                       "arguments": {"path": "https://example.com/",
                                     "script": "await fetch('https://example.org/x'); return 1"}}])
    message = _last_tool_message(session)
    assert started == []
    assert message.get("is_error") and "somente local" in message["content"]


def test_local_only_blocks_local_html_too(brain, monkeypatch, tmp_path):
    """Página local também pode carregar subrecursos e scripts externos: bloqueia tudo."""
    started = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: started.append(a))
    page = tmp_path / "index.html"
    page.write_text('<script src="https://example.org/a.js"></script>', encoding="utf-8")
    brain.settings.set("execution_policy", "local_only", save=False)
    session = _session(brain, approve=lambda r: "yes", mode="livre")
    session._execute([{"id": "c1", "name": "check_web_page", "arguments": {"path": str(page)}}])
    assert started == []
    assert _last_tool_message(session).get("is_error")


# ── #13: escrita no clipboard passa pela autorização ─────────


class _FakeClipboard:
    def __init__(self):
        self.content = "conteudo original"
        self.writes = []

    def get_clipboard(self):
        return self.content

    def copy_to_clipboard(self, text):
        self.writes.append(text)
        self.content = text
        return f"Copiado para clipboard: '{text[:50]}'"


def _clip_session(brain, answer):
    brain.system = _FakeClipboard()
    requests = []

    def approve(request):
        requests.append(request)
        return answer

    return _session(brain, approve, mode="perguntar"), requests


def test_clipboard_read_needs_no_approval(brain):
    session, requests = _clip_session(brain, "no")
    session._execute([{"id": "c1", "name": "clipboard", "arguments": {}}])
    assert brain.registry.get("clipboard").risk == "read"
    assert requests == []
    assert _last_tool_message(session)["content"] == "conteudo original"


def test_clipboard_text_argument_never_writes(brain):
    """Ferramenta de leitura não grava, mesmo que o modelo mande `text`."""
    session, requests = _clip_session(brain, "no")
    session._execute([{"id": "c1", "name": "clipboard", "arguments": {"text": "conteudo indevido"}}])
    assert brain.system.writes == []
    assert brain.system.content == "conteudo original"


def test_clipboard_write_denied_or_plan_mode_does_not_write(brain):
    # Modo plano = permission_mode "perguntar" + approve que nega toda ferramenta (gui._plan_mode).
    session, requests = _clip_session(brain, "no")
    session._execute([{"id": "c1", "name": "set_clipboard", "arguments": {"text": "conteudo indevido"}}])
    assert brain.registry.get("set_clipboard").risk == "write"
    assert [r["tool"] for r in requests] == ["set_clipboard"] and requests[0]["risk"] == "write"
    assert brain.system.writes == []
    assert _last_tool_message(session).get("is_error")


def test_clipboard_write_approved_works(brain):
    session, requests = _clip_session(brain, "yes")
    session._execute([{"id": "c1", "name": "set_clipboard", "arguments": {"text": "ok autorizado"}}])
    assert len(requests) == 1
    assert brain.system.writes == ["ok autorizado"]
    assert not _last_tool_message(session).get("is_error")
