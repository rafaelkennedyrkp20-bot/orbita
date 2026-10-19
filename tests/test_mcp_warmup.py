"""Aquecimento proativo do motor (REA/Ghidra) desacoplado da tool call do modelo.

Sessão MCP falsa num event loop de verdade (thread própria, como o hub roda no app).
"""

import asyncio
import json
import threading
import time

import pytest

from agent.core import mcp_hub
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
    """`slow`: ferramentas que esperam o `gate` abrir (motor subindo). `fail`: ferramentas que estouram."""

    def __init__(self, slow=(), fail=None, error_result=()):
        self.slow = set(slow)
        self.fail = dict(fail or {})
        self.error_result = set(error_result)
        self.gate = threading.Event()
        self.calls = []

    async def call_tool(self, name, args=None, progress_callback=None, **kw):
        self.calls.append((name, args))
        if name in self.slow:
            if progress_callback:
                await progress_callback(30, 100, "importando o binário")
            while not self.gate.is_set():
                await asyncio.sleep(0.01)
        if name in self.fail:
            raise self.fail[name]
        return _Result(f"{name} executou", is_error=name in self.error_result)


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_hub, "DETACH_AFTER", 0.3)
    monkeypatch.setattr(mcp_hub, "REPEAT_WAIT", 0.3)
    h = MCPHub(ToolRegistry(), config_path=tmp_path / "mcp.json")
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    h._loop = loop
    yield h
    loop.call_soon_threadsafe(loop.stop)
    thread.join(2)


def _server(hub, session, warm="pronto", ready_check="binary_session"):
    state = ServerState("rea", {"ready_check": ready_check} if ready_check else {})
    state.status, state.session, state.generation, state.warm = "conectado", session, 1, warm
    if warm == "aquecendo":
        state.warm_since = time.monotonic()
    hub.servers["rea"] = state
    return state


def _until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _payload(result):
    return json.loads(result.text.split("\n", 1)[0])


def _timed_call(hub, tool, args=None):
    start = time.monotonic()
    result = hub.call("rea", tool, args or {})
    return result, time.monotonic() - start


# ── Disparo no handshake ────────────────────────────────────

def test_warmup_fires_on_connect_without_blocking(hub):
    session = _Session(slow={"binary_session"})
    state = _server(hub, session, warm="")
    start = time.monotonic()
    hub._start_warmup(state, session, state.generation)
    assert time.monotonic() - start < 0.1             # não segura a conexão nem o loop do agente
    assert state.warm == "aquecendo" and state.warm_since > 0
    assert _until(lambda: session.calls == [("binary_session", {})])
    session.gate.set()
    assert _until(lambda: state.warm == "pronto")
    assert state.status == "conectado"


def test_warmup_skipped_without_ready_check(hub):
    session = _Session()
    state = _server(hub, session, warm="", ready_check=None)
    hub._start_warmup(state, session, state.generation)
    time.sleep(0.05)
    assert state.warm == "" and session.calls == []


def test_warmup_failure_is_error_state_not_disconnect(hub):
    session = _Session(fail={"binary_session": RuntimeError("provider down")})
    state = _server(hub, session, warm="")
    hub._start_warmup(state, session, state.generation)
    assert _until(lambda: state.warm == "erro")
    assert "provider down" in state.warm_note
    assert state.status == "conectado" and state.session is session
    result, _ = _timed_call(hub, "open_binary", {"path": "a.exe"})   # o erro não prende o cliente
    assert not result.is_error and "open_binary executou" in result.text


def test_reconnect_discards_stale_warmup(hub):
    session = _Session(slow={"binary_session"})
    state = _server(hub, session, warm="")
    hub._start_warmup(state, session, state.generation)
    assert _until(lambda: session.calls)
    state.generation += 1                       # reconectou: nova geração
    state.warm, state.warm_note = "", ""
    session.gate.set()
    time.sleep(0.2)
    assert state.warm == "" and state.warm_note == ""   # resultado velho descartado


# ── Chamadas durante o aquecimento ──────────────────────────

def test_call_during_warmup_returns_warming_up_fast(hub):
    session = _Session()
    state = _server(hub, session, warm="aquecendo")
    state.warm_progress, state.warm_note = 40, "importando"
    result, took = _timed_call(hub, "binary_overview", {"path": "a.exe"})
    assert took < 1.0
    assert not result.is_error
    data = _payload(result)
    assert data["status"] == "warming_up" and data["retry_after_ms"] == 5000
    assert data["progress"] == 40 and isinstance(data["elapsed_s"], int)
    assert "aguarde" in result.text.lower()
    assert session.calls == []                  # nada pesado entra enquanto o motor sobe


def test_light_ready_check_call_passes_during_warmup(hub):
    session = _Session()
    _server(hub, session, warm="aquecendo")
    result, took = _timed_call(hub, "binary_session")
    assert took < 1.0 and result.text == "binary_session executou"


def test_after_ready_call_executes_for_real(hub):
    session = _Session()
    state = _server(hub, session, warm="pronto")
    result, _ = _timed_call(hub, "binary_overview", {"path": "a.exe"})
    assert result.text == "binary_overview executou" and not result.is_error
    assert session.calls == [("binary_overview", {"path": "a.exe"})]
    assert state.job is None and state.warm == "pronto"


def test_slow_first_call_detaches_and_retry_reuses_same_execution(hub):
    session = _Session(slow={"open_binary"})
    state = _server(hub, session, warm="pronto")
    args = {"path": "grande.exe"}

    first, took = _timed_call(hub, "open_binary", args)
    assert took < mcp_hub.DETACH_AFTER + 0.7    # devolve logo, não fica minutos presa
    assert _payload(first)["status"] == "warming_up" and not first.is_error
    assert state.warm == "aquecendo"
    assert _until(lambda: state.warm_progress == 30)          # progresso do MCP vai para o estado
    assert state.warm_note == "importando o binário"

    again, took = _timed_call(hub, "open_binary", args)
    assert took < 1.0 and _payload(again)["status"] == "warming_up"
    other, took = _timed_call(hub, "list_procedures", {})
    assert took < 1.0 and _payload(other)["status"] == "warming_up"
    assert [c[0] for c in session.calls] == ["open_binary"]   # uma execução só

    session.gate.set()
    assert _until(lambda: state.warm == "pronto")
    done, took = _timed_call(hub, "open_binary", args)
    assert took < 1.0 and done.text == "open_binary executou"
    assert [c[0] for c in session.calls] == ["open_binary"]   # reaproveitou a execução pendente
    assert state.job is None

    after, _ = _timed_call(hub, "list_procedures", {})
    assert after.text == "list_procedures executou"


def test_repeated_call_waits_for_pending_execution(hub, monkeypatch):
    # O modelo não tem como "aguardar 5 s": repete na hora. A repetição da mesma chamada espera a execução
    # pendente (até REPEAT_WAIT) em vez de gastar um passo do modelo por segundo durante o cold start.
    monkeypatch.setattr(mcp_hub, "REPEAT_WAIT", 3.0)
    session = _Session(slow={"open_binary"})
    _server(hub, session, warm="pronto")
    first, _ = _timed_call(hub, "open_binary", {"path": "x"})
    assert _payload(first)["status"] == "warming_up"
    other, took = _timed_call(hub, "list_procedures", {})       # chamada diferente: resposta imediata
    assert took < 1.0 and _payload(other)["status"] == "warming_up"
    threading.Timer(0.5, session.gate.set).start()
    again, took = _timed_call(hub, "open_binary", {"path": "x"})
    assert again.text == "open_binary executou" and 0.3 < took < 3.0
    assert [c[0] for c in session.calls] == ["open_binary"]


def test_finished_job_not_collected_does_not_block_other_calls(hub):
    session = _Session(slow={"open_binary"})
    state = _server(hub, session, warm="pronto")
    _timed_call(hub, "open_binary", {"path": "x"})
    session.gate.set()
    assert _until(lambda: state.warm == "pronto")
    other, took = _timed_call(hub, "list_procedures", {})   # o modelo seguiu sem repetir open_binary
    assert other.text == "list_procedures executou" and state.job is None


def test_warming_hint_names_the_requested_call(hub):
    session = _Session()
    _server(hub, session, warm="aquecendo")
    result, _ = _timed_call(hub, "binary_overview", {"path": "a.exe"})
    assert "repita a mesma chamada (binary_overview)" in result.text


def test_detached_failure_marks_error_and_returns_it(hub):
    session = _Session(slow={"open_binary"}, error_result={"open_binary"})
    state = _server(hub, session, warm="pronto")
    first, _ = _timed_call(hub, "open_binary", {"path": "x"})
    assert _payload(first)["status"] == "warming_up"
    session.gate.set()
    assert _until(lambda: state.warm == "erro")
    assert "open_binary executou" in state.warm_note
    result, _ = _timed_call(hub, "open_binary", {"path": "x"})
    assert result.is_error and state.status == "conectado"


def test_reconnect_drops_pending_job(hub):
    session = _Session(slow={"open_binary"})
    state = _server(hub, session, warm="pronto")
    _timed_call(hub, "open_binary", {"path": "x"})
    old = state.job
    assert old is not None
    state.generation += 1
    state.warm = "pronto"
    session.slow.clear()
    result, _ = _timed_call(hub, "open_binary", {"path": "x"})
    assert result.text == "open_binary executou"            # nova execução na conexão nova
    session.gate.set()
    assert _until(old.done)
    assert state.warm == "pronto"                            # o fim da execução velha não mexe no estado


def test_status_exposes_backend_warm_state(hub):
    session = _Session()
    state = _server(hub, session, warm="aquecendo")
    state.warm_since = time.monotonic() - 12
    state.warm_progress, state.warm_note = 55, "analisando"
    state.cfg["description"] = "REA"
    row = hub.status()[0]
    assert row["warm"] == "aquecendo" and row["warm_elapsed"] >= 12
    assert row["warm_progress"] == 55 and row["warm_note"] == "analisando" and row["warmable"] is True


def test_prompt_has_no_retry_patch_phrase(hub):
    _server(hub, _Session())
    text = hub.describe_for_prompt()
    assert "rea" in text and "não repita" not in text


# ── Servidor comum (sem aquecimento) ────────────────────────

def test_plain_server_call_longer_than_poll_still_returns_result(hub):
    class Slow(_Session):
        async def call_tool(self, name, args=None, progress_callback=None, **kw):
            await asyncio.sleep(0.8)   # mais que o passo de 0,5 s da espera
            return _Result("feito")
    _server(hub, Slow(), ready_check=None)
    result, _ = _timed_call(hub, "qualquer")
    assert result.text == "feito" and not result.is_error


def test_progress_callback_emits_backend_elapsed(hub):
    got = []
    state = _server(hub, _Session())
    cb = hub._progress_callback(lambda kind, data: got.append((kind, data)), state, "binary_overview", "call-9",
                                started=time.monotonic() - 7)
    asyncio.run(cb(1.0, None, "importando"))
    kind, data = got[0]
    assert kind == "mcp_progress"
    assert data["id"] == "call-9" and data["tool"] == "binary_overview" and data["server"] == "rea"
    assert data["message"] == "importando" and data["elapsed"] >= 7
    assert state.warm_note == "importando"
