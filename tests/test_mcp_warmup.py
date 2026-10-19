"""Check-in de prontidão após conectar e barra de aquecimento do MCP (feature REA/Ghidra)."""

import asyncio

from agent.core.mcp_hub import MCPHub, ServerState
from agent.core.tools import ToolRegistry


class _Text:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Result:
    def __init__(self, text="ok", is_error=False):
        self.content = [_Text(text)]
        self.isError = is_error
        self.structuredContent = None


class _Session:
    def __init__(self, result=None, raises=None):
        self._result = result if result is not None else _Result()
        self._raises = raises
        self.calls = []

    async def call_tool(self, name, args=None, **kw):
        self.calls.append((name, args))
        if self._raises:
            raise self._raises
        return self._result


def _hub():
    return MCPHub(ToolRegistry())


def test_progress_callback_emits_mcp_progress():
    got = []
    cb = _hub()._progress_callback(lambda kind, data: got.append((kind, data)),
                                   "rea", "binary_overview", "call-9")
    asyncio.run(cb(1.0, None, "importando"))
    assert len(got) == 1
    kind, data = got[0]
    assert kind == "mcp_progress"
    assert data["id"] == "call-9" and data["tool"] == "binary_overview" and data["server"] == "rea"
    assert data["message"] == "importando" and isinstance(data["elapsed"], int)


def test_ready_check_ok_sets_ready():
    hub = _hub()
    state = ServerState("rea", {"ready_check": "binary_session"})
    state.generation = 3
    session = _Session(_Result("provider: ghidra available"))
    asyncio.run(hub._ready_check(state, session, 3))
    assert state.ready is True
    assert "ghidra" in state.ready_note
    assert session.calls == [("binary_session", {})]


def test_ready_check_error_marks_degraded_not_disconnected():
    hub = _hub()
    state = ServerState("rea", {"ready_check": "binary_session"})
    state.generation = 1
    session = _Session(raises=RuntimeError("provider down"))
    asyncio.run(hub._ready_check(state, session, 1))
    assert state.ready is False and "provider down" in state.ready_note


def test_ready_check_skipped_without_config():
    hub = _hub()
    state = ServerState("x", {})
    session = _Session()
    asyncio.run(hub._ready_check(state, session, 0))
    assert state.ready is None and session.calls == []


def test_ready_check_ignores_stale_generation():
    hub = _hub()
    state = ServerState("rea", {"ready_check": "binary_session"})
    state.generation = 5
    session = _Session(_Result("tarde demais"))
    asyncio.run(hub._ready_check(state, session, 4))   # geração antiga: resultado é descartado
    assert state.ready is None and state.ready_note == ""


def test_status_and_prompt_expose_readiness():
    hub = _hub()
    state = ServerState("rea", {"ready_check": "binary_session", "description": "REA"})
    state.status = "conectado"
    state.ready, state.ready_note = True, "ok"
    hub.servers["rea"] = state
    row = hub.status()[0]
    assert row["warm"] is True and row["ready"] is True and row["ready_note"] == "ok"
    assert "aquece o motor" in hub.describe_for_prompt()
