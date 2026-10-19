"""Loop agêntico com um provedor simulado (sem rede)."""

import threading

import pytest

import agent.core.agent_loop as loop
from agent.core.agent_loop import (
    AgentSession, _TagFilter, complete_summary, parse_prompted_tool_calls, tool_pairs_intact,
)
from agent.core.staged_writes import Store
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


def test_summary_keeps_pending_heading_and_tool_pairs():
    text = complete_summary("## Objetivo\nfazer\n## Feito\nnada")
    assert "## Próximos passos" in text and "não apareceu" in text
    assert tool_pairs_intact([
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}, {"id": "2"}]},
        {"role": "tool", "content": "a"},
        {"role": "tool", "content": "b"},
    ])
    assert not tool_pairs_intact([
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]},
        {"role": "user", "content": "no meio"},
        {"role": "tool", "content": "tarde"},
    ])


def test_staged_write_stays_off_disk_and_shell_is_blocked(brain, provider, tmp_path, monkeypatch):
    store = Store(tmp_path / "staged.json")
    monkeypatch.setattr("agent.core.staged_writes.get_store", lambda: store)
    brain.settings.set("staged_writes", "on", save=False)
    brain.settings.set("default_workspace", str(tmp_path), save=False)
    target = tmp_path / "fora.txt"
    marker = tmp_path / "shell.txt"
    provider([
        ChatResult(tool_calls=[call("write_file", path="fora.txt", content="proposta")]),
        ChatResult(tool_calls=[call("run_shell", command=f"Set-Content -Path '{marker}' -Value vazou")]),
        ChatResult(text="não gravei"),
    ])
    chat = session(brain, mode="livre")
    assert chat.run("grave") == "não gravei"
    assert not target.exists() and not marker.exists()
    assert store.read(target) == "proposta"
    texts = [m["content"] for m in chat.messages if m["role"] == "tool"]
    assert any("ainda não está no disco" in text for text in texts)
    assert any("terminal" in text.lower() for text in texts)


def test_local_only_blocks_shell_before_it_runs(brain, provider, tmp_path):
    brain.settings.set("execution_policy", "local_only")
    marker = tmp_path / "ran.txt"
    provider([
        ChatResult(tool_calls=[call("run_shell", command=f"Set-Content -Path '{marker}' -Value vazou")]),
        ChatResult(text="não executei"),
    ])
    chat = session(brain, mode="livre")
    assert chat.run("rode") == "não executei"
    assert not marker.exists()
    tool_msg = next(m for m in chat.messages if m["role"] == "tool")
    assert "somente local" in tool_msg["content"].lower()


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
    assert "Não delegue" in sub_system


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


@pytest.mark.parametrize("steps", [8, 120])
def test_long_turn_fits_local_context(brain, steps):
    # Ollama com 16k: um turno só, sem turno anterior para descartar. Antes ia 6x acima do orçamento.
    s = AgentSession(brain, brain.profiles.get("geral"), "ollama", "qwen3:8b", approve=lambda r: "yes")
    s.messages.append({"role": "user", "content": "analise o projeto"})
    for i in range(steps):
        s.messages.append({"role": "assistant", "content": "",
                           "tool_calls": [{"id": f"r{i}", "name": "read_file", "arguments": {"path": f"f{i}"}}]})
        s.messages.append({"role": "tool", "tool_call_id": f"r{i}", "name": "read_file", "content": "x" * 20000})
    tools = s.visible_tools()
    wire = s._wire_messages(tools)
    assert s._history_size(wire[1:]) <= s._history_budget(tools, wire[0]["content"])
    assert wire[1]["content"].startswith("analise o projeto")
    assert wire[-1]["tool_call_id"] == f"r{steps - 1}"
    assert tool_pairs_intact(wire[1:])
    # Encurta só o excesso, do mais antigo para o mais novo: o resultado mais recente continua útil.
    assert len(wire[-1]["content"]) > 5000


def test_system_note_does_not_start_a_turn(brain):
    # O aviso "(Sistema: ...)" entra como mensagem de usuário, mas o pedido real do turno não pode sumir.
    s = AgentSession(brain, brain.profiles.get("geral"), "ollama", "qwen3:8b", approve=lambda r: "yes")
    s.messages += [{"role": "user", "content": "pedido real"},
                   {"role": "assistant", "content": "vou verificar"},
                   {"role": "user", "content": "(Sistema: você anunciou uma ação mas não chamou nenhuma ferramenta.)"}]
    for i in range(6):
        s.messages.append({"role": "assistant", "content": "",
                           "tool_calls": [{"id": f"r{i}", "name": "read_file", "arguments": {"path": f"f{i}"}}]})
        s.messages.append({"role": "tool", "tool_call_id": f"r{i}", "name": "read_file", "content": "y" * 20000})
    wire = s._wire_messages(s.visible_tools())
    assert wire[1]["content"].startswith("pedido real")


def test_parse_prompted_tool_calls_variants():
    text = ('a <tool_call>{"name": "x", "arguments": {"k": 1}}</tool_call> b '
            '<tool_call>```json\n{"name": "y", "parameters": "{\\"z\\": 2}"}\n```</tool_call>')
    calls = parse_prompted_tool_calls(text)
    assert [c["name"] for c in calls] == ["x", "y"]
    assert calls[0]["arguments"] == {"k": 1} and calls[1]["arguments"] == {"z": 2}


def test_tag_filter_hides_tool_calls_and_flushes_trailing_angle_bracket():
    out = []
    f = _TagFilter(out.append)
    for chunk in ["Olá <tool", '_call>{"name":"x"}</tool_', "call> 2 < 3"]:
        f.feed(chunk)
    f.flush()
    assert "".join(out) == "Olá  2 < 3"


def test_cancelled_turn_does_not_leave_orphan_tool_calls(brain, provider):
    fake = provider([
        ChatResult(text="Parcial", tool_calls=[call("list_dir")], stop_reason="cancelled"),
        ChatResult(text="Turno seguinte ok."),
    ])
    s = session(brain)
    assert s.run("pare") == "Parcial"
    assert all("tool_calls" not in m for m in s.messages)
    assert s.run("continue") == "Turno seguinte ok."
    assert all("tool_calls" not in m for m in fake.calls[1]["messages"])


def test_markdown_render_blocks_local_file_links():
    from agent.ui import render

    html = render.markdown_html("[Abrir](file:///C:/Windows/System32/calc.exe) e [Site](https://example.com)")
    assert "file:" not in html and "calc.exe" not in html
    assert 'href="https://example.com"' in html


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


def test_profile_limits_apply_to_mcp_tools(brain, provider):
    from agent.core.tools import Tool

    ran = []
    for name, server in (("mcp__x__danger", "x"), ("mcp__rea__open", "rea")):
        brain.registry.register(Tool(name, name, {"type": "object"}, lambda a, c, n=name: ran.append(n) or "ok",
                                     risk="exec", group="mcp", source=f"mcp:{server}", deferred=True))
    provider([ChatResult(tool_calls=[call("mcp__x__danger")]), ChatResult(text="fim"),
              ChatResult(tool_calls=[call("mcp__x__danger"), call("mcp__rea__open")]), ChatResult(text="fim")])
    reviewer = session(brain, profile="revisor")          # perfil sem o grupo mcp
    reviewer.run("x")
    reverse = session(brain, profile="engenharia_reversa")  # perfil só com o servidor rea
    reverse.run("y")
    assert ran == ["mcp__rea__open"]   # adiada, mas do servidor liberado: roda pelo nome
    denied = [m["content"] for m in reviewer.messages + reverse.messages if m["role"] == "tool" and m.get("is_error")]
    assert len(denied) == 2 and all("não está liberada" in text for text in denied)


def test_loaded_skill_is_not_masked_in_long_turn(brain, provider, tmp_path):
    from agent.core.skills import Skill

    folder = tmp_path / "longa"
    folder.mkdir()
    body = "PASSO " * 800   # 4.800 caracteres: acima do limite de encurtamento
    (folder / "SKILL.md").write_text(f"---\nname: longa\ndescription: d\n---\n{body}", encoding="utf-8")
    brain.skills.skills = {"longa": Skill("longa", "d", folder / "SKILL.md", "projeto")}
    reads = [ChatResult(tool_calls=[call("list_dir", path=str(tmp_path))]) for _ in range(7)]
    fake = provider([ChatResult(tool_calls=[{"id": "c_skill", "name": "use_skill", "arguments": {"name": "longa"}}]), *reads, ChatResult(text="fim")])
    session(brain).run("siga a skill")
    sent = next(m for m in fake.calls[-1]["messages"] if m.get("name") == "use_skill")
    assert body.strip() in sent["content"]


def test_bridge_tools_obey_local_only_and_staged_writes(brain, tmp_path, monkeypatch):
    # A ponte do Grok passa pela mesma autorização do loop: a próxima ferramenta exposta não herda furo.
    from agent.core import grok_bridge

    monkeypatch.setattr(grok_bridge, "EXPOSED", grok_bridge.EXPOSED + ("run_shell",))
    marker = tmp_path / "ran.txt"
    command = {"command": f"Set-Content -Path '{marker}' -Value vazou"}
    chat = session(brain, mode="livre")
    brain.settings.set("execution_policy", "local_only", save=False)
    local = chat.run_bridge_tool("run_shell", command)
    brain.settings.set("execution_policy", "", save=False)
    brain.settings.set("staged_writes", "on", save=False)
    staged = chat.run_bridge_tool("run_shell", command)
    assert local.is_error and "somente local" in local.text.lower()
    assert staged.is_error and "terminal" in staged.text.lower()
    assert not marker.exists()


def test_delegation_rule_lives_in_one_short_place(brain):
    # Medido no Órbita: equipe custou ~15x mais tokens num site de 4 páginas. O prompt não pode empurrar para ela.
    s = AgentSession(brain, brain.profiles.get("geral"), "anthropic", "claude-opus-5-5", approve=lambda r: "yes")
    prompt = s.system_prompt(s.visible_tools())
    rules = prompt.split("## Sua equipe (delegate_task)\n", 1)[1].split("\n- ", 1)[0]
    assert "paralelismo real" in rules and len(rules) <= 700
    assert prompt.count("paralelismo real") == 1
    assert "Para acelerar" not in prompt and "delegue em paralelo" not in prompt


def test_find_tools_stays_inside_profile_servers(brain):
    from agent.core.tools import Tool

    brain.registry.register(Tool("mcp__x__decompile", "decompile binary", {"type": "object"}, lambda a, c: "ok",
                                 group="mcp", source="mcp:x", deferred=True))
    reverse = session(brain, profile="engenharia_reversa")
    finder = brain.registry.get("find_tools")
    by_query = finder.run({"query": "decompile", "server": "x"}, reverse._context())
    by_name = finder.run({"names": ["mcp__x__decompile"]}, reverse._context())
    assert "mcp__x__decompile" not in reverse.activated
    assert "mcp__x__decompile" not in by_query.text + by_name.text


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


def test_grok_as_main_model_gets_orbita_team_through_the_bridge(brain, monkeypatch, tmp_path):
    """Caso real: Grok como principal pedia "agentes com o DeepSeek" e saía procurando DeepSeek e Blender no PC."""
    from agent.core import grok_bridge

    bridge = grok_bridge.Bridge(info_file=tmp_path / "ponte.json")
    monkeypatch.setattr(grok_bridge, "get_bridge", lambda: bridge)
    seen = []

    class FakeGrok:
        external_agent = True
        supports_native_tools = False

        def bridge_ready(self):
            return True

        def run_agent(self, prompt, **kwargs):
            key = kwargs["env"][grok_bridge.KEY_ENV]               # o processo do Grok recebe a chave da sessão
            tools = bridge.handle({"token": bridge.token, "key": key, "op": "tools"})["tools"]
            denied = bridge.handle({"token": bridge.token, "key": key, "op": "call", "name": "run_shell",
                                    "arguments": {"command": "dir"}})
            seen.append({"prompt": prompt, "rules": kwargs["rules"], "tools": [t["name"] for t in tools],
                         "denied": denied})
            return "feito", "sessao-1", {}

    monkeypatch.setattr(loop, "get_provider", lambda name, settings: FakeGrok())
    s = AgentSession(brain, brain.profiles.get("geral"), "grok", "grok-4.7", approve=lambda r: "no")
    assert s.run("cria um jogo usando agentes com o deepseek") == "feito"
    s.run("e agora?")
    first, second = seen
    assert "delegate_task" in first["tools"] and "run_shell" not in first["tools"]   # ler/editar/terminal: os do Grok
    assert first["denied"]["is_error"]
    assert "MCP 'orbita'" in first["rules"] and "## Sua equipe (delegate_task)" in first["rules"]
    assert grok_bridge.TURN_REMINDER in second["prompt"]                              # regras só vão no 1º turno
    assert bridge.sessions == {}                                                      # turno acabou: desanexada


def test_delegate_structured_contract_and_verify(brain, provider):
    seen_prompts = []

    def worker(messages, tools):
        seen_prompts.append(messages[-1]["content"])
        return ChatResult(text="Status: DONE\nArquivos: a.py")

    from agent.core.tools import Tool, ToolResult
    brain.registry.register(Tool("verify_project", "verify", {"type": "object"},
                                 lambda a, c: ToolResult("Quality Gate: PASS\n[PASS] pyflakes: 0 erros"),
                                 group="arquivos"))
    provider([
        ChatResult(tool_calls=[call("delegate_task", tasks=[{
            "task": "refatore módulo A",
            "profile": "programador",
            "files": ["agent/a.py"],
            "acceptance_criteria": ["0 erros no pyflakes", "função x testada"],
            "verify": True,
        }])]),
        worker,
        ChatResult(text="Tudo validado."),
    ])
    s = session(brain)
    assert s.run("refatore") == "Tudo validado."
    assert "## Contrato da Subtarefa" in seen_prompts[0]
    assert "agent/a.py" in seen_prompts[0] and "0 erros no pyflakes" in seen_prompts[0]
    tool_msg = next(m for m in s.messages if m["role"] == "tool")
    assert "Verificação automática da equipe" in tool_msg["content"]
    assert "Quality Gate: PASS" in tool_msg["content"]


def test_reasoning_kept_in_current_turn_and_pruned_in_old(brain, provider):
    fake = provider([
        ChatResult(text="", reasoning="pensando no passo 1", tool_calls=[call("list_dir")]),
        ChatResult(text="Concluído turno 1."),
        ChatResult(text="Concluído turno 2."),
    ])
    s = session(brain)
    s.run("turno 1")
    # Na segunda chamada do turno 1 (após list_dir), o reasoning deve estar presente no histórico enviado
    assistant_in_turn1 = next(m for m in fake.calls[1]["messages"] if m["role"] == "assistant")
    assert assistant_in_turn1.get("reasoning") == "pensando no passo 1"
    # No turno 2, o reasoning antigo do turno 1 é podado para economizar contexto
    s.run("turno 2")
    old_assistants = [m for m in fake.calls[2]["messages"] if m["role"] == "assistant"]
    assert all("reasoning" not in m for m in old_assistants)


class _Block:
    def __init__(self, **data):
        self.__dict__.update(data)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


class _FakeClaudeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self.message


class _FakeClaude:
    """Cliente Anthropic falso: guarda cada requisição e responde com um bloco de pensamento assinado."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self.messages = self
        self.beta = self

    def stream(self, betas=None, fallbacks=None, **params):
        import copy as copy_module

        self.requests.append(copy_module.deepcopy(params))
        step = len(self.requests) - 1
        blocks = [_Block(type="thinking", thinking="", signature=f"sig{step}")] + self.replies.pop(0)
        usage = _Block(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
        return _FakeClaudeStream(_Block(content=blocks, stop_reason=stop, usage=usage, stop_details=None))


def _long_claude_turn(brain, monkeypatch, tmp_path, reads: int) -> list[dict]:
    """Turno real com o AnthropicProvider e cliente falso: `reads` leituras de 6.000 caracteres e "fim"."""
    from agent.core.providers import AnthropicProvider

    big = tmp_path / "grande.txt"
    big.write_text("linha de dados\n" * 400, encoding="utf-8")   # 6.000 caracteres: acima do encurtamento
    replies = [[_Block(type="tool_use", id=f"r{i}", name="read_file", input={"path": str(big)})]
               for i in range(reads)] + [[_Block(type="text", text="fim")]]
    client = _FakeClaude(replies)
    claude = AnthropicProvider("anthropic", {"type": "anthropic"})
    monkeypatch.setattr(claude, "_sdk", lambda: (None, client))
    monkeypatch.setattr(loop, "get_provider", lambda name, settings: claude)
    brain.settings.set("permission_mode", "livre", save=False)
    s = AgentSession(brain, brain.profiles.get("geral"), "anthropic", "claude-opus-5-5", approve=lambda r: "yes")
    assert s.run("leia o arquivo várias vezes") == "fim"
    assert len(client.requests) == reads + 1
    return client.requests


def _replayed_thinking(requests: list[dict]) -> int:
    """Quantas mensagens do assistente levaram pensamento, somando todos os envios. Cada uma tem de ir com o
    prefixo exato (sistema, ferramentas e mensagens) que a gerou."""
    produced = {f"sig{n}": request for n, request in enumerate(requests)}
    replayed = 0
    for request in requests:
        for i, message in enumerate(request["messages"]):
            for j, block in enumerate(message["content"]):
                if block.get("type") != "thinking":
                    continue
                origin = produced[block["signature"]]
                assert j == 0 and request["messages"][:i] == origin["messages"], \
                    f"{block['signature']} reenviado depois de um trecho editado"
                assert request.get("system") == origin.get("system") and request.get("tools") == origin.get("tools")
                replayed += 1
    return replayed


def test_claude_thinking_is_replayed_only_with_the_prefix_that_produced_it(brain, monkeypatch, tmp_path):
    # Opus 5.5 / Fable 5.1: o bloco de pensamento só vale com o histórico exato que o gerou (contas novas: HTTP
    # 400). O encurtamento do turno longo edita resultados antigos; o pensamento posterior não pode ir junto.
    requests = _long_claude_turn(brain, monkeypatch, tmp_path, reads=13)
    assert _replayed_thinking(requests), "o pensamento continua indo quando o histórico antes dele não mudou"
    assert "encurtado" in str(requests[-1]["messages"])   # o encurtamento aconteceu de fato


def test_long_claude_turn_keeps_most_thinking_and_the_same_system(brain, monkeypatch, tmp_path):
    # Num turno de 32 passos com resultados grandes, o envio deve ser quase só acréscimo: o aviso de passos não
    # muda o sistema (que invalidaria todo pensamento e o cache) e o encurtamento não desliza a cada passo.
    requests = _long_claude_turn(brain, monkeypatch, tmp_path, reads=32)
    replayed = _replayed_thinking(requests)
    systems = len({r.get("system") for r in requests})
    appended = sum(prev.get("system") == cur.get("system") and cur["messages"][:len(prev["messages"])] == prev["messages"]
                   for prev, cur in zip(requests, requests[1:]))
    print(f"\n[medição] envios={len(requests)} pensamento reenviado={replayed} só acréscimo={appended} "
          f"sistemas distintos={systems}")
    # Antes: 39 pensamentos reenviados, 9 sistemas distintos, 6 de 32 envios só acrescentavam.
    assert systems == 1
    last = str(requests[-1]["messages"])
    assert "encurtado" in last and last.count("Aviso do ambiente") == 8   # passos 25 a 32, cópias antigas ficam
    assert replayed >= 120 and appended >= 25



def _project_skills(brain, monkeypatch):
    """Catálogo do projeto, sem skills do usuário (o teste não pode depender da máquina)."""
    import agent.core.skills as skills_module
    from agent.core.skills import SkillManager
    monkeypatch.setattr(skills_module, "USER_SKILL_DIRS", [])
    brain.skills = SkillManager()


def test_research_profile_routes_discovery_without_dumping_it(brain, provider, monkeypatch):
    _project_skills(brain, monkeypatch)
    monkeypatch.setattr(brain, "models_table", lambda: "- openai:gpt-5 ($$): forte em código")
    fake = provider([ChatResult(text="ok")])
    session(brain, profile="pesquisador").run("qual o melhor modelo para código?")
    system = fake.calls[0]["messages"][0]["content"]
    assert "descobrir-agente:" in system
    assert "spec-plan-tdd:" not in system          # pesquisa não herda o índice inteiro
    assert "openai:gpt-5" not in system            # tabela só entra ao carregar a skill
    assert "NÃO configure" not in system
    assert any(t["name"] == "use_skill" for t in fake.calls[0]["tools"])


def test_discovery_skill_receives_models_only_when_loaded(brain, monkeypatch):
    from agent.core.skills import SkillManager
    from agent.core.tools import ToolContext
    brain.skills = SkillManager()  # o fixture zera as skills de propósito
    monkeypatch.setattr(brain, "models_table", lambda: "- ollama:qwen (local/grátis): bom em código")
    ctx = ToolContext(workspace=brain.settings.path.parent, session=type("S", (), {"loaded_skills": set()})())
    loaded = brain.registry.get("use_skill").run({"name": "descobrir-agente"}, ctx)
    assert "ollama:qwen" in loaded.text and "NÃO configure" in loaded.text
    other = brain.registry.get("use_skill").run({"name": "spec-plan-tdd"}, ctx)
    assert "ollama:qwen" not in other.text


def test_handoff_note_rejects_incomplete_partial_and_blocked():
    assert "incompleto" in loop.handoff_note("fiz tudo")
    assert "Verificação" in loop.handoff_note("Status: DONE")
    assert loop.handoff_note("Status: DONE\nVerificação: pytest 62 passed") == ""
    assert "BLOCKED" in loop.handoff_note("Status: BLOCKED\nVerificação: não rodou")
    assert "PARTIAL" in loop.handoff_note("Status: parcial\nVerificação: pytest ok")


def test_handoff_done_requires_a_successful_verification_result():
    assert "Verificação" in loop.handoff_note("Status: DONE\nVerificação: pytest tests -q")
    assert "Verificação" in loop.handoff_note("Status: DONE\nVerificação: pytest tests -q — 2 failed")
    assert loop.handoff_note("**Status**: DONE\n**Verificação**: pytest tests -q — 65 passed") == ""
    assert loop.handoff_note("Status: DONE\nVerificação: 65 passed, 0 failed") == ""
    assert loop.handoff_note("Status: DONE\nVerificação: Quality Gate: [PASS]") == ""


def test_general_profile_has_no_discovery_protocol(brain, provider, monkeypatch):
    _project_skills(brain, monkeypatch)
    fake = provider([ChatResult(text="ok")])
    session(brain).run("oi")
    system = fake.calls[0]["messages"][0]["content"]
    assert "NÃO configure" not in system
    assert "descobrir-agente:" in system          # o roteador aponta; o protocolo não vem junto


def test_team_verification_runs_once_and_respects_permission(brain, provider):
    from agent.core.tools import Tool, ToolResult
    runs = []
    brain.registry.register(Tool("verify_project", "verify", {"type": "object"},
                                 lambda a, c: runs.append(1) or ToolResult("Quality Gate: PASS"),
                                 risk="exec", group="shell"))
    provider([
        ChatResult(tool_calls=[call("delegate_task", tasks=[
            {"task": "parte A", "verify": True}, {"task": "parte B", "verify": True}])]),
        ChatResult(text="A pronta"), ChatResult(text="B pronta"),
        ChatResult(text="fim"),
    ])
    s = session(brain, mode="auto")          # "exec" pede permissão no modo automático
    s.approve = lambda request: "no"
    s.run("divida")
    tool_msg = next(m for m in s.messages if m["role"] == "tool")
    assert runs == [] and "não autorizada" in tool_msg["content"]
