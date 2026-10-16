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


def test_project_core_skills_are_valid():
    manager = SkillManager()
    expected = {"spec-plan-tdd", "code-review-simplify", "debug-recovery", "creative-pipeline"}
    assert expected.issubset(set(manager.skills.keys()))
    for name in expected:
        body = manager.load(name)
        assert "## When to Use" in body and "## Verification" in body


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
