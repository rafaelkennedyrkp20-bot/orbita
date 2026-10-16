"""Ponte Órbita ↔ Grok Build: o Grok (agente externo) chama a equipe e as ferramentas do Órbita via MCP."""

import asyncio
import json
import os
import sys
from pathlib import Path

from agent.core import grok_bridge
from agent.core.tools import ToolResult

ROOT = Path(__file__).resolve().parents[1]


class FakeSession:
    """O que a ponte usa da AgentSession: ferramentas liberadas e execução com permissão."""

    def __init__(self):
        self.calls = []

    def bridge_tools(self):
        return [{"name": "delegate_task", "description": "Delegar para a equipe",
                 "parameters": {"type": "object", "properties": {"tasks": {"type": "array"}}}}]

    def run_bridge_tool(self, name, args):
        self.calls.append((name, args))
        return ToolResult(text=f"equipe recebeu {len(args.get('tasks', []))} tarefa(s)")


async def _client_roundtrip(info_file: Path, key: str = ""):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client

    env = {**get_default_environment(), "PYTHONPATH": str(ROOT), grok_bridge.INFO_ENV: str(info_file),
           grok_bridge.KEY_ENV: key}
    params = StdioServerParameters(command=sys.executable, args=["-m", "agent.core.grok_bridge"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            result = None
            if tools:
                result = await session.call_tool("delegate_task", {"tasks": [{"task": "fazer o boneco no Blender"}]})
            return [t.name for t in tools], result


def test_bridge_routes_grok_calls_to_the_running_session(tmp_path):
    info = tmp_path / "grok_bridge.json"
    bridge = grok_bridge.Bridge(info_file=info)
    bridge.start()
    try:
        session, other = FakeSession(), FakeSession()
        with bridge.attached(session) as key, bridge.attached(other):
            names, result = asyncio.run(asyncio.wait_for(_client_roundtrip(info, key), 60))
            assert other.calls == []                                 # cada processo do Grok fala com a sua sessão
            assert asyncio.run(asyncio.wait_for(_client_roundtrip(info, "chave-errada"), 60)) == ([], None)
        assert names == ["delegate_task"]
        assert not result.is_error and "equipe recebeu 1 tarefa(s)" in result.content[0].text
        assert session.calls == [("delegate_task", {"tasks": [{"task": "fazer o boneco no Blender"}]})]

        names, result = asyncio.run(asyncio.wait_for(_client_roundtrip(info, key), 60))
        assert names == [] and result is None                       # turno do Grok acabou: nada exposto
    finally:
        bridge.stop()
    assert not info.exists()                                         # Órbita fechado: ponte não aponta para nada


def test_bridge_refuses_wrong_token(tmp_path):
    info = tmp_path / "grok_bridge.json"
    bridge = grok_bridge.Bridge(info_file=info)
    bridge.start()
    try:
        with bridge.attached(FakeSession()) as key:
            data = json.loads(info.read_text(encoding="utf-8"))
            reply = grok_bridge.request({"port": data["port"], "token": "errado"}, {"op": "tools", "key": key})
        assert reply.get("error") and "tools" not in reply
    finally:
        bridge.stop()


def test_closed_orbita_means_no_tools(tmp_path):
    assert grok_bridge.request(None, {"op": "tools"}).get("tools") == []
    assert grok_bridge.load_info(tmp_path / "nao-existe.json") is None


def test_grok_rules_point_to_the_bridge_instead_of_searching_the_pc():
    rules = grok_bridge.rules_text("## Sua equipe (delegate_task)\n- programador → river:deepseek")
    assert "mcp" in rules.lower() and "delegate_task" in rules
    assert "river:deepseek" in rules
    assert "não procure" in rules.lower()


def test_registration_command_runs_the_bridge_module():
    command = grok_bridge.registration_command("C:/grok.exe")
    assert command[:4] == ["C:/grok.exe", "mcp", "add", grok_bridge.SERVER_NAME]
    assert command[-2:] == ["-m", "agent.core.grok_bridge"]
    assert f"PYTHONPATH={ROOT}" in command
    python = command[command.index("--") + 1]
    assert os.path.basename(python).lower().startswith("python") and "pythonw" not in python.lower()
