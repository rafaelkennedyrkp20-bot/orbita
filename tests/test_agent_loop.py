"""Loop agêntico com um provedor simulado (sem rede)."""

import threading

import pytest

import agent.core.agent_loop as loop
from agent.core.agent_loop import AgentSession, _TagFilter, parse_prompted_tool_calls
from agent.core.providers import ChatResult, ToolsUnsupported


class ScriptedProvider:
    """Devolve respostas pré-programadas e registra o que recebeu."""

    supports_native_tools = True

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.lock = threading.Lock()

    def supports_vision(self, model):
        return True

    def chat(self, model, messages, tools=None, **kwargs):
        with self.lock:
            self.calls.append({"model": model, "messages": messages, "tools": tools})
            step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            step = step(messages, tools)
        if kwargs.get("on_text") and step.text:
            kwargs["on_text"](step.text)
        return step


@pytest.fixture
def provider(monkeypatch):
    holder = {}

    def install(script):
        holder["p"] = ScriptedProvider(script)
        monkeypatch.setattr(loop, "get_provider", lambda name, settings: holder["p"])
        return holder["p"]

    return install


def session(brain, mode="livre", profile="geral"):
    brain.settings.set("permission_mode", mode, save=False)
    return AgentSession(brain, brain.profiles.get(profile), "fake", "m1", approve=lambda r: "no")


def call(name, **args):
    return {"id": f"c_{name}", "name": name, "arguments": args}


def test_tool_loop_executes_and_finishes(brain, provider, tmp_path):
    target = tmp_path / "out.txt"
    fake = provider([
        ChatResult(text="Vou criar.", tool_calls=[call("write_file", path=str(target), content="oi")]),
        ChatResult(text="Arquivo criado."),
    ])
    s = session(brain)
    assert s.run("crie out.txt") == "Arquivo criado."
    assert target.read_text() == "oi"
    roles = [m["role"] for m in s.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    # A segunda chamada recebeu o resultado da ferramenta
    assert any(m["role"] == "tool" for m in fake.calls[1]["messages"])


def test_denied_permission_returns_error_to_model(brain, provider, tmp_path):
    provider([
        ChatResult(tool_calls=[call("run_shell", command="echo 1")]),
        ChatResult(text="Ok, não executei."),
    ])
    s = session(brain, mode="auto")
    s.run("rode echo")
    tool_msg = next(m for m in s.messages if m["role"] == "tool")
    assert tool_msg.get("is_error") and "NEGOU" in tool_msg["content"]


def test_always_allow_skips_future_prompts(brain, provider, tmp_path):
    asked = []
    provider([
        ChatResult(tool_calls=[call("run_shell", command="Write-Output 1")]),
        ChatResult(tool_calls=[call("run_shell", command="Write-Output 2")]),
        ChatResult(text="feito"),
    ])
    s = session(brain, mode="auto")
    s.approve = lambda r: asked.append(r) or "always"
    s.run("rode duas vezes")
    assert len(asked) == 1


def test_unknown_tool_is_reported(brain, provider):
    provider([ChatResult(tool_calls=[call("nao_existe")]), ChatResult(text="ok")])
    s = session(brain)
    s.run("x")
    assert "não existe" in next(m for m in s.messages if m["role"] == "tool")["content"]


def test_fallback_to_prompted_tools(brain, provider, tmp_path):
    target = tmp_path / "p.txt"
    text_call = f'Certo.\n<tool_call>\n{{"name": "write_file", "arguments": {{"path": "{target.as_posix()}", "content": "x"}}}}\n</tool_call>'
    fake = provider([ToolsUnsupported("no tools"), ChatResult(text=text_call), ChatResult(text="Pronto.")])
    s = session(brain)
    assert s.run("crie") == "Pronto."
    assert target.read_text() == "x"
    assert s.prompted_tools
    assert fake.calls[1]["tools"] is None
    assert "<tool_call>" in fake.calls[1]["messages"][0]["content"]  # instruções no prompt de sistema
    assert any("<tool_result" in (m.get("content") or "") for m in fake.calls[2]["messages"])


def test_nudge_when_model_announces_without_acting(brain, provider, tmp_path):
    (tmp_path / "f.txt").write_text("a")
    provider([
        ChatResult(tool_calls=[call("list_dir", path=str(tmp_path))]),
        ChatResult(text="Agora vou verificar o arquivo f.txt."),
        ChatResult(text="O arquivo contém 'a'."),
    ])
    s = session(brain)
    assert s.run("veja") == "O arquivo contém 'a'."


def test_delegate_runs_subagents_in_parallel(brain, provider):
    def worker(messages, tools):
        task = messages[-1]["content"]
        return ChatResult(text=f"relatório de {task}")

    fake = provider([
        ChatResult(tool_calls=[call("delegate_task", tasks=[
            {"task": "parte A", "profile": "programador", "model": "outro:modelo-x"},
            {"task": "parte B", "profile": "revisor"}])]),
        worker, worker,
        ChatResult(text="Integrado."),
    ])
    s = session(brain)
    assert s.run("divida") == "Integrado."
    tool_msg = next(m for m in s.messages if m["role"] == "tool")
    assert "relatório de parte A" in tool_msg["content"] and "relatório de parte B" in tool_msg["content"]
    models = {c["model"] for c in fake.calls}
    assert "modelo-x" in models  # cada subagente pode usar outro modelo
    sub_system = next(c for c in fake.calls if c["model"] == "modelo-x")["messages"][0]["content"]
    assert "subagente" in sub_system and "Programador" in sub_system


def test_budget_brake_pauses(brain, provider):
    brain.settings.set("turn_token_budget", 10, save=False)
    provider([ChatResult(tool_calls=[call("list_dir")], usage={"input_tokens": 50, "output_tokens": 5}),
              ChatResult(text="nunca chega")])
    s = session(brain)
    assert "Pausado" in s.run("x")


def test_context_trimming_keeps_recent_turns(brain, provider):
    brain.settings.set("economy_mode", "maximo", save=False)
    s = session(brain)
    for i in range(40):
        s.messages.append({"role": "user", "content": f"pergunta {i} " + "x" * 4000})
        s.messages.append({"role": "assistant", "content": f"resposta {i}"})
    wire = s._wire_messages([])
    assert wire[0]["role"] == "system" and wire[1]["role"] == "user"
    assert "pergunta 39" in wire[-2]["content"]
    assert len(wire) < 81 and not any("pergunta 0 " in (m.get("content") or "") for m in wire)
    assert sum(len(m["content"]) for m in wire) / 3.5 < 24_000


def test_parse_prompted_tool_calls_variants():
    text = ('a <tool_call>{"name": "x", "arguments": {"k": 1}}</tool_call> b '
            '<tool_call>```json\n{"name": "y", "parameters": "{\\"z\\": 2}"}\n```</tool_call>')
    calls = parse_prompted_tool_calls(text)
    assert [c["name"] for c in calls] == ["x", "y"]
    assert calls[0]["arguments"] == {"k": 1} and calls[1]["arguments"] == {"z": 2}


def test_tag_filter_hides_tool_calls_while_streaming():
    out = []
    f = _TagFilter(out.append)
    for chunk in ["Olá <tool", '_call>{"name":"x"}</tool_', "call> fim"]:
        f.feed(chunk)
    f.feed("")
    assert "".join(out) == "Olá  fim"


def test_mcp_tools_run_in_order_not_parallel(brain, provider):
    from agent.core.tools import Tool, ToolResult

    order = []

    def make(name, delay):
        def run(args, ctx):
            import time
            time.sleep(delay)
            order.append(name)
            return ToolResult(name)
        return run

    for name, delay in (("mcp__s__open", 0.2), ("mcp__s__overview", 0.0)):
        brain.registry.register(Tool(name, name, {"type": "object"}, make(name, delay), source="mcp:s", group="mcp"))
    provider([ChatResult(tool_calls=[call("mcp__s__open"), call("mcp__s__overview")]), ChatResult(text="ok")])
    session(brain).run("x")
    assert order == ["mcp__s__open", "mcp__s__overview"]


def test_loop_detector_warns_on_repeated_failure(brain, provider):
    provider([ChatResult(tool_calls=[call("read_file", path="nao_existe.txt")]),
              ChatResult(tool_calls=[call("read_file", path="nao_existe.txt")]),
              ChatResult(text="desisto")])
    s = session(brain)
    s.run("leia")
    tool_msgs = [m for m in s.messages if m["role"] == "tool"]
    assert "NÃO repita" not in tool_msgs[0]["content"] and "NÃO repita" in tool_msgs[1]["content"]


def test_salvage_json_tool_call_from_text(brain, provider, tmp_path):
    (tmp_path / "a.txt").write_text("conteúdo")
    text = f'Vou ler:\n```json\n{{"name": "read_file", "arguments": {{"path": "{(tmp_path / "a.txt").as_posix()}"}}}}\n```'
    provider([ChatResult(text=text), ChatResult(text="Li o arquivo.")])
    s = session(brain)
    assert s.run("leia") == "Li o arquivo."
    assert "conteúdo" in next(m for m in s.messages if m["role"] == "tool")["content"]


def test_external_agent_keeps_session_and_rules(brain, monkeypatch):
    calls = []

    class FakeGrok:
        external_agent = True
        supports_native_tools = False

        def run_agent(self, prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            kwargs["on_text"]("resposta")
            return "resposta", "sessao-1", {"input_tokens": 10, "output_tokens": 2}

    monkeypatch.setattr(loop, "get_provider", lambda name, settings: FakeGrok())
    s = session(brain, profile="grok_build")
    s.messages = [{"role": "user", "content": "antes"}, {"role": "assistant", "content": "ok"}]
    assert s.run("primeiro") == "resposta"
    assert s.run("segundo") == "resposta"
    assert calls[0]["session_id"] is None and "Contexto da conversa" in calls[0]["prompt"]
    assert "estilo do projeto" in calls[0]["rules"]
    assert calls[1]["session_id"] == "sessao-1" and calls[1]["prompt"] == "segundo"
    assert calls[1]["permission"] == "livre"
