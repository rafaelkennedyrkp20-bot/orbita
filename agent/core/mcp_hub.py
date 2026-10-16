"""
mcp_hub.py — Cliente MCP (Model Context Protocol) para conectar o agente a qualquer programa.

Configuração em `data/mcp.json`, no MESMO formato do Claude Desktop / Claude Code / Cursor:

    {"mcpServers": {
        "rea": {"command": "npx", "args": ["-y", "rea-agents@6.5.0", "mcp"]},
        "remoto": {"url": "https://exemplo.com/mcp", "headers": {"Authorization": "Bearer ..."}}
    }}

Campos extras deste agente (opcionais, ignorados por outros clientes):
    enabled      false desliga o servidor sem apagar a configuração
    tools_mode   "direct" | "deferred" | "auto" (auto: adia se o servidor tiver mais de 12 ferramentas)
    always_load  ferramentas (nomes originais) sempre visíveis mesmo num servidor adiado — o "kit inicial"
    inherit_env  variáveis do ambiente/.env repassadas ao servidor (aceita curingas: "REA_*")
    risk         "read" | "write" | "exec" — sobrescreve o risco padrão das ferramentas
    description  texto curto mostrado à IA e na interface

Ferramentas "adiadas" não ocupam contexto: a IA usa `find_tools` para ativá-las sob
demanda (essencial para o REA, que expõe 200+ ferramentas).

Todo o MCP roda num event loop asyncio em uma thread própria; a GUI e o loop do agente
chamam de forma síncrona e segura entre threads.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from agent.core.config import DATA_DIR, LOGS_DIR
from agent.core.tools import Tool, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

MCP_CONFIG = DATA_DIR / "mcp.json"
DEFERRED_THRESHOLD = 12
CONNECT_TIMEOUT = 180  # npx pode baixar o pacote na primeira vez
CALL_TIMEOUT = 600

DEFAULT_MCP_CONFIG: dict[str, Any] = {
    "mcpServers": {
        "rea": {
            "description": "REA — engenharia reversa: binários, apps Electron/JS, .NET, Android, sites, firmware",
            "command": "npx",
            "args": ["-y", "rea-agents@6.5.0", "mcp"],
            "enabled": True,
            "tools_mode": "deferred",
            "always_load": ["open_binary", "close_binary", "binary_overview", "inspect_artifact",
                            "list_procedures", "procedure_pseudo_code", "search_strings",
                            "analyze_javascript_application"],
            # Motores de análise nativa (instale o Ghidra e defina GHIDRA_INSTALL_DIR no .env)
            "inherit_env": ["GHIDRA_INSTALL_DIR", "HOPPER_LAUNCHER_PATH", "JAVA_HOME", "REA_*"],
        },
        "playwright": {
            "description": "Controle do navegador (abrir sites, clicar, preencher, capturar)",
            "command": "npx",
            "args": ["-y", "@playwright/mcp@latest"],
            "enabled": False,
            "tools_mode": "auto",
        },
        "windows": {
            "description": "Controle de janelas e apps do Windows (requer uv instalado)",
            "command": "uvx",
            "args": ["windows-mcp"],
            "enabled": False,
            "tools_mode": "auto",
        },
        "filesystem": {
            "description": "Acesso a pastas específicas via servidor MCP oficial",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", str(Path.home() / "Documents")],
            "enabled": False,
        },
    }
}


@dataclass
class ServerState:
    name: str
    cfg: dict
    status: str = "desligado"      # desligado | conectando | conectado | erro
    error: str = ""
    tool_names: list[str] = field(default_factory=list)
    session: Any = None
    stop: Optional[asyncio.Event] = None
    future: Any = None
    generation: int = 0


def _safe_name(server: str, tool: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", f"mcp__{server}__{tool}")
    if len(name) > 64:
        digest = hashlib.sha1(name.encode()).hexdigest()[:6]
        name = f"{name[:57]}_{digest}"
    return name


def _inherited_env(patterns: list[str]) -> dict[str, str]:
    """Repassa só as variáveis pedidas (ex.: "GHIDRA_INSTALL_DIR", "REA_*") — chaves de API ficam de fora."""
    import fnmatch

    return {key: value for key, value in os.environ.items()
            if any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns)}


def _windows_command(command: str, args: list[str]) -> tuple[str, list[str]]:
    """No Windows, `npx`/`uvx` são .cmd/.bat e precisam do cmd.exe para rodar via stdio."""
    if os.name != "nt":
        return command, args
    resolved = shutil.which(command)
    if resolved and resolved.lower().endswith((".cmd", ".bat")):
        return "cmd.exe", ["/d", "/c", resolved, *args]
    return resolved or command, args


class MCPHub:

    def __init__(self, registry: ToolRegistry, config_path: Path = MCP_CONFIG,
                 plugin_configs: Callable[[], list[tuple[str, Path]]] | None = None):
        self.registry = registry
        self.config_path = config_path
        self.plugin_configs = plugin_configs or (lambda: [])
        self.servers: dict[str, ServerState] = {}
        self.listeners: list[Callable[[], None]] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._lock = threading.RLock()

    # ── Configuração ─────────────────────────────────────────

    def load_config(self) -> dict:
        if not self.config_path.exists():
            self.save_config(DEFAULT_MCP_CONFIG)
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            logger.error("mcp.json inválido: %s", error)
            data = {"mcpServers": {}}
        servers = dict(data.get("mcpServers") or {})
        for plugin, path in self.plugin_configs():
            try:
                plugin_data = json.loads(path.read_text(encoding="utf-8"))
                for name, cfg in (plugin_data.get("mcpServers") or plugin_data).items():
                    if isinstance(cfg, dict):
                        servers.setdefault(f"{plugin}-{name}", {**cfg, "plugin": plugin})
            except (OSError, json.JSONDecodeError) as error:
                logger.warning("Plugin %s: .mcp.json inválido (%s)", plugin, error)
        return servers

    def save_config(self, data: dict) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _raw_config(self) -> dict:
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"mcpServers": {}}

    def set_enabled(self, name: str, enabled: bool) -> None:
        data = self._raw_config()
        if name in data.get("mcpServers", {}):
            data["mcpServers"][name]["enabled"] = enabled
            self.save_config(data)
        self.reload()

    def import_external(self) -> list[str]:
        """Copia servidores MCP já configurados em Claude Desktop, Claude Code e Cursor."""
        sources = [
            Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json",
            Path.home() / ".claude.json",
            Path.home() / ".cursor" / "mcp.json",
        ]
        data = self._raw_config()
        current = data.setdefault("mcpServers", {})
        imported = []
        for source in sources:
            try:
                external = json.loads(source.read_text(encoding="utf-8")).get("mcpServers") or {}
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
            for name, cfg in external.items():
                if name not in current and isinstance(cfg, dict) and (cfg.get("command") or cfg.get("url")):
                    current[name] = {**cfg, "enabled": False, "tools_mode": "auto",
                                     "description": f"Importado de {source.name}"}
                    imported.append(name)
        if imported:
            self.save_config(data)
            self.reload()
        return imported

    # ── Ciclo de vida ────────────────────────────────────────

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run_loop, name="mcp-hub", daemon=True)
            self._thread.start()
            self._ready.wait(5)
        self.reload()

    def _run_loop(self) -> None:
        if os.name == "nt":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def reload(self) -> None:
        """Aplica o mcp.json: desconecta removidos/desligados e conecta os ligados."""
        config = self.load_config()
        with self._lock:
            for name in list(self.servers):
                state = self.servers[name]
                new_cfg = config.get(name)
                if new_cfg is None or not new_cfg.get("enabled", True) or new_cfg != state.cfg:
                    self._disconnect(state)
                    if new_cfg is None:
                        del self.servers[name]
            for name, cfg in config.items():
                state = self.servers.get(name)
                if state is None:
                    state = self.servers[name] = ServerState(name, cfg)
                state.cfg = cfg
                if cfg.get("enabled", True) and state.status in ("desligado", "erro"):
                    self._connect(state)
        self._notify()

    def restart(self, name: str) -> None:
        with self._lock:
            state = self.servers.get(name)
            if state:
                self._disconnect(state)
                self._connect(state)

    def shutdown(self) -> None:
        with self._lock:
            for state in self.servers.values():
                self._disconnect(state)
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _connect(self, state: ServerState) -> None:
        if self._loop is None:
            return
        state.status, state.error = "conectando", ""
        state.generation += 1
        state.future = asyncio.run_coroutine_threadsafe(self._serve(state, state.generation), self._loop)

    def _disconnect(self, state: ServerState) -> None:
        if state.stop is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(state.stop.set)
        state.generation += 1
        self.registry.unregister_source(f"mcp:{state.name}")
        state.tool_names, state.session, state.status = [], None, "desligado"

    def _notify(self) -> None:
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:
                logger.debug("listener MCP falhou", exc_info=True)

    async def _serve(self, state: ServerState, generation: int) -> None:
        """Mantém a conexão aberta até `stop` (contextos anyio no mesmo task)."""
        from mcp import ClientSession

        stop = state.stop = asyncio.Event()
        current = lambda: state.generation == generation  # noqa: E731 — conexão ainda é a vigente?
        cfg = state.cfg
        log_file = None
        try:
            async with AsyncExitStack() as stack:
                if cfg.get("url"):
                    from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

                    http = create_mcp_http_client(headers=cfg.get("headers"))
                    await stack.enter_async_context(http)
                    read, write = await stack.enter_async_context(streamable_http_client(cfg["url"], http_client=http))
                else:
                    from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client

                    command, args = _windows_command(cfg["command"], list(cfg.get("args") or []))
                    env = {**get_default_environment(), **_inherited_env(cfg.get("inherit_env") or []),
                           **{k: str(v) for k, v in (cfg.get("env") or {}).items()}}
                    LOGS_DIR.mkdir(parents=True, exist_ok=True)
                    log_file = open(LOGS_DIR / f"mcp-{state.name}.log", "a", encoding="utf-8")
                    params = StdioServerParameters(command=command, args=args, env=env, cwd=cfg.get("cwd"),
                                                   encoding_error_handler="replace")
                    read, write = await stack.enter_async_context(stdio_client(params, errlog=log_file))
                session = await stack.enter_async_context(ClientSession(read, write))
                await asyncio.wait_for(session.initialize(), CONNECT_TIMEOUT)
                tools = await self._list_tools(session)
                if not current():
                    return
                state.session = session
                self._register_tools(state, tools)
                state.status = "conectado"
                logger.info("MCP '%s' conectado (%d ferramentas)", state.name, len(tools))
                self._notify()
                await stop.wait()
        except Exception as error:
            message = str(error) or type(error).__name__
            if hasattr(error, "exceptions"):  # ExceptionGroup do anyio
                message = "; ".join(str(e) or type(e).__name__ for e in error.exceptions)
            logger.error("MCP '%s' falhou: %s", state.name, message)
            if current():
                state.status, state.error = "erro", message[:500]
        finally:
            if current():
                self.registry.unregister_source(f"mcp:{state.name}")
                state.session, state.tool_names = None, []
                if state.status in ("conectado", "conectando"):
                    state.status = "desligado"
            if log_file:
                log_file.close()
            self._notify()

    @staticmethod
    async def _list_tools(session) -> list:
        from mcp import types

        tools, cursor = [], None
        while True:
            params = types.PaginatedRequestParams(cursor=cursor) if cursor else None
            page = await session.list_tools(params=params)
            tools.extend(page.tools)
            cursor = getattr(page, "next_cursor", None)
            if not cursor:
                return tools

    def _register_tools(self, state: ServerState, tools: list) -> None:
        cfg = state.cfg
        mode = cfg.get("tools_mode", "auto")
        deferred = mode == "deferred" or (mode == "auto" and len(tools) > DEFERRED_THRESHOLD)
        names = []
        always = set(cfg.get("always_load") or [])
        for mcp_tool in tools:
            schema = getattr(mcp_tool, "input_schema", None) or getattr(mcp_tool, "inputSchema", None) or {}
            annotations = getattr(mcp_tool, "annotations", None)
            if cfg.get("risk"):
                risk = cfg["risk"]
            elif annotations is not None and getattr(annotations, "read_only_hint", False):
                risk = "read"
            elif annotations is not None and getattr(annotations, "destructive_hint", False):
                risk = "exec"
            else:
                risk = "write"
            name = _safe_name(state.name, mcp_tool.name)
            self.registry.register(Tool(
                name=name,
                description=f"[{state.name}] {(mcp_tool.description or mcp_tool.name).strip()[:1500]}",
                parameters=schema if schema.get("type") == "object" else {"type": "object", "properties": {}},
                func=self._make_caller(state.name, mcp_tool.name),
                risk=risk,
                group="mcp",
                source=f"mcp:{state.name}",
                deferred=deferred and mcp_tool.name not in always,
            ))
            names.append(name)
        state.tool_names = names

    def _make_caller(self, server: str, tool_name: str):
        def call(args: dict, ctx) -> ToolResult:
            return self.call(server, tool_name, args, cancel=getattr(ctx, "cancel", None))
        return call

    # ── Chamadas ─────────────────────────────────────────────

    def call(self, server: str, tool_name: str, args: dict, cancel: Optional[threading.Event] = None) -> ToolResult:
        state = self.servers.get(server)
        if state is None or state.session is None or self._loop is None:
            return ToolResult.error(f"Servidor MCP '{server}' não está conectado.")
        future = asyncio.run_coroutine_threadsafe(state.session.call_tool(tool_name, args or {}), self._loop)
        waited = 0.0
        while True:
            try:
                result = future.result(timeout=0.5)
                break
            except TimeoutError:
                waited += 0.5
                if (cancel is not None and cancel.is_set()) or waited > CALL_TIMEOUT:
                    future.cancel()
                    return ToolResult.error("Chamada MCP cancelada." if cancel and cancel.is_set() else "Chamada MCP excedeu o tempo.")
            except Exception as error:
                return ToolResult.error(f"Erro MCP: {error}")
        return self._convert_result(result)

    @staticmethod
    def _convert_result(result) -> ToolResult:
        from agent.actions.builtin_tools import save_artifact_bytes

        texts, images = [], []
        for item in getattr(result, "content", None) or []:
            kind = getattr(item, "type", "")
            if kind == "text":
                texts.append(item.text)
            elif kind == "image":
                mime = getattr(item, "mime_type", None) or getattr(item, "mimeType", "image/png")
                suffix = mimetypes.guess_extension(mime) or ".png"
                images.append(save_artifact_bytes(base64.b64decode(item.data), suffix))
            elif kind == "resource":
                resource = item.resource
                texts.append(getattr(resource, "text", None) or f"[recurso binário {getattr(resource, 'uri', '')}]")
            elif kind == "resource_link":
                texts.append(f"[link] {getattr(item, 'uri', '')} {getattr(item, 'name', '')}")
            else:
                texts.append(str(item))
        structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
        if structured and not texts:
            texts.append(json.dumps(structured, ensure_ascii=False, indent=1))
        is_error = bool(getattr(result, "is_error", None) or getattr(result, "isError", False))
        return ToolResult(text="\n".join(texts) or "(sem conteúdo)", images=images, is_error=is_error)

    # ── Consulta ─────────────────────────────────────────────

    def status(self) -> list[dict]:
        with self._lock:
            return [{
                "name": s.name,
                "status": s.status,
                "error": s.error,
                "tools": len(s.tool_names),
                "enabled": s.cfg.get("enabled", True),
                "description": s.cfg.get("description", ""),
                "deferred": bool(s.tool_names) and all(
                    (t := self.registry.get(n)) is not None and t.deferred for n in s.tool_names),
            } for s in self.servers.values()]

    def connected(self) -> list[str]:
        return [s.name for s in self.servers.values() if s.status == "conectado"]

    def describe_for_prompt(self, allowed: Optional[set[str]] = None) -> str:
        lines = []
        for item in self.status():
            if item["status"] != "conectado" or (allowed is not None and item["name"] not in allowed):
                continue
            how = "use find_tools para ativar" if item["deferred"] else "ferramentas já disponíveis"
            lines.append(f"- {item['name']} ({item['tools']} ferramentas, {how}): {item['description']}")
        return "\n".join(lines)
