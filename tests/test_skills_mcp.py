"""Skills (SKILL.md) e um servidor MCP real via stdio."""

import json
import sys
import textwrap
import time


from agent.core.mcp_hub import MCPHub, _safe_name
from agent.core.skills import SkillManager, parse_skill_file
from agent.core.tools import ToolRegistry


def test_skill_frontmatter_and_loading(tmp_path, monkeypatch):
    folder = tmp_path / "minha-skill"
    folder.mkdir()
    (folder / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: minha-skill
        description: Faz algo útil quando o usuário pede X.
        ---
        # Instruções
        Passo 1.
        """), encoding="utf-8")
    (folder / "ref.md").write_text("detalhe", encoding="utf-8")
    meta, body = parse_skill_file(folder / "SKILL.md")
    assert meta["name"] == "minha-skill" and "Passo 1" in body

    import agent.core.skills as skills_module
    monkeypatch.setattr(skills_module, "USER_SKILL_DIRS", [])
    monkeypatch.setattr(skills_module, "PROJECT_SKILLS", tmp_path)
    manager = SkillManager()
    assert "minha-skill: Faz algo útil" in manager.index_text()
    assert "Passo 1" in manager.load("minha-skill") and "ref.md" in manager.load("minha-skill")
    assert manager.load("minha-skill", "ref.md") == "detalhe"
    assert "não encontrado" in manager.load("minha-skill", "../../etc")


def test_safe_tool_names():
    assert _safe_name("rea", "open binary!") == "mcp__rea__open_binary_"
    assert len(_safe_name("servidor", "x" * 100)) == 64


def test_cassandra_catalog_routes_and_attack_skills_stay_out(monkeypatch):
    import agent.core.skills as skills_module
    from agent.core.profiles import DEFAULT_PROFILES

    monkeypatch.setattr(skills_module, "USER_SKILL_DIRS", [])
    monkeypatch.setattr(skills_module, "PLUGINS_DIR", skills_module.PROJECT_SKILLS / "nao-existe")
    profile = next(item for item in DEFAULT_PROFILES if item.id == "cassandra")
    prompt = profile.system_prompt.lower()
    assert profile.in_team and profile.provider == "" and profile.model == ""
    assert "regra 0" not in prompt and "nunca me nego" not in prompt
    assert "cassandra-catalogo" in profile.system_prompt

    manager = SkillManager()
    banned = {
        "benchmark", "computer-use", "blocked-page-recovery", "web-search", "soul",
        "standard-exploit-web-sqli", "cassandra-anti-censor", "decepticon-exploit",
    }
    assert banned.isdisjoint(manager.skills)
    assert manager.skills["cassandra-catalogo"].when
    assert manager.skills["humanizer"].when == ""
    router = manager.router_text()
    assert "cassandra-catalogo:" in router
    assert router.count("\n- ") < 20
    for skill in skills_module.PROJECT_SKILLS.glob("*/SKILL.md"):
        text = skill.read_text(encoding="utf-8", errors="replace").lower()
        assert "regra 0" not in text and "nunca me nego" not in text


def test_project_core_skills_are_valid():
    manager = SkillManager()
    expected = {"spec-plan-tdd", "code-review-simplify", "debug-recovery", "creative-pipeline",
                "descobrir-agente"}
    assert expected.issubset(set(manager.skills.keys()))
    for name in expected:
        body = manager.load(name)
        assert "## When to Use" in body and "## Verification" in body
        assert manager.skills[name].when, name
    assert "verify_cmd" not in manager.load("spec-plan-tdd")


def test_router_uses_when_and_index_does_not_duplicate(tmp_path, monkeypatch):
    import agent.core.skills as skills_module
    monkeypatch.setattr(skills_module, "USER_SKILL_DIRS", [])
    monkeypatch.setattr(skills_module, "PROJECT_SKILLS", tmp_path)
    for name, when in (("com-when", "quando o pedido for X"), ("sem-when", "")):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Descrição de {name}.\nwhen: {when}\n---\nCorpo.\n",
            encoding="utf-8")
    manager = SkillManager()
    router = manager.router_text()
    index = manager.index_text()
    assert "com-when: quando o pedido for X" in router
    assert "sem-when" not in router
    assert "sem-when" in index and "com-when" not in index


SERVER = textwrap.dedent("""
    from mcp.server.mcpserver import MCPServer
    server = MCPServer("teste")

    @server.tool()
    def somar(a: int, b: int) -> str:
        \"\"\"Soma dois números.\"\"\"
        return str(a + b)

    server.run("stdio")
""")


def test_mcp_stdio_roundtrip(tmp_path):
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"teste": {
        "command": sys.executable, "args": [str(script)], "tools_mode": "direct"}}}), encoding="utf-8")
    registry = ToolRegistry()
    hub = MCPHub(registry, config_path=config)
    hub.start()
    try:
        deadline = time.time() + 60
        while time.time() < deadline and hub.status()[0]["status"] != "conectado":
            time.sleep(0.3)
        status = hub.status()[0]
        assert status["status"] == "conectado", status
        tool = registry.get("mcp__teste__somar")
        assert tool is not None and not tool.deferred
        result = tool.run({"a": 2, "b": 3}, type("Ctx", (), {"cancel": None})())
        assert not result.is_error and result.text.strip() == "5"
        hub.set_enabled("teste", False)
        assert registry.get("mcp__teste__somar") is None
    finally:
        hub.shutdown()


def _hub_with(tmp_path, servers):
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
    return MCPHub(ToolRegistry(), config_path=config)


def test_missing_program_says_what_to_install_instead_of_errno(tmp_path, monkeypatch):
    """Caso real (Linux sem Node.js): aparecia "[Errno 2] Arquivo ou diretório inexistente: 'npx'"."""
    import agent.core.mcp_hub as hub_module

    monkeypatch.setattr(hub_module.shutil, "which", lambda cmd: None)
    hub = _hub_with(tmp_path, {"rea": {"command": "npx", "args": ["-y", "rea-agents"]},
                               "py": {"command": "uvx", "args": ["algo"]},
                               "meu": {"command": "programa-que-nao-existe"}})
    hub.reload()                                       # sem start(): nada pode ter sido agendado
    by_name = {s["name"]: s for s in hub.status()}
    assert by_name["rea"]["status"] == "falta" and "Node.js" in by_name["rea"]["error"]
    assert by_name["py"]["status"] == "falta" and "uv" in by_name["py"]["error"]
    assert by_name["meu"]["status"] == "falta" and "programa-que-nao-existe" in by_name["meu"]["error"]
    assert all(s.future is None for s in hub.servers.values())
    assert not any(s["status"] == "erro" for s in hub.status())   # não acende o alerta vermelho


def test_windows_only_server_is_unavailable_elsewhere(tmp_path, monkeypatch):
    import agent.core.mcp_hub as hub_module

    monkeypatch.setattr(hub_module, "current_platform", lambda: "linux")
    hub = _hub_with(tmp_path, {"windows": {"command": "uvx", "args": ["windows-mcp"], "enabled": True},
                               "novo": {"command": "x", "platforms": ["windows", "macos"]}})
    hub.reload()
    for item in hub.status():
        assert item["status"] == "indisponivel" and "Windows" in item["error"], item
    assert all(s.future is None for s in hub.servers.values())
    monkeypatch.setattr(hub_module, "current_platform", lambda: "windows")
    assert hub_module.platform_problem({"command": "uvx", "args": ["windows-mcp"]}) == ""


def test_nested_exception_groups_show_the_real_error():
    import agent.core.mcp_hub as hub_module

    class Group(Exception):                            # mesmo formato do ExceptionGroup do anyio (3.10 não tem)
        def __init__(self, message, exceptions):
            super().__init__(message)
            self.exceptions = exceptions

    error = Group("unhandled errors in a TaskGroup", [Group("interno", [ConnectionError("servidor fechou a conexão")])])
    assert hub_module.error_text(error) == "servidor fechou a conexão"
