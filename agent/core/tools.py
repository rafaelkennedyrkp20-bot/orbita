"""
tools.py — Registro de ferramentas que a IA pode chamar.

Cada ferramenta tem um JSON Schema (formato aceito por todos os provedores), um grupo
(para perfis liberarem/bloquearem conjuntos inteiros) e um nível de risco usado pelo
sistema de permissões:

    read   → só lê/consulta (nunca pede confirmação)
    write  → altera arquivos/memória (confirma no modo "perguntar")
    exec   → executa programas, comandos ou controla mouse/teclado
             (confirma nos modos "perguntar" e "auto")
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

MAX_TOOL_OUTPUT_CHARS = 24000


@dataclass
class ToolResult:
    text: str
    images: list[str] = field(default_factory=list)
    is_error: bool = False

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        return cls(text=message, is_error=True)


@dataclass
class ToolContext:
    """O que uma ferramenta recebe ao ser executada."""

    workspace: Path
    session: Any = None                  # AgentSession que chamou (para subagentes)
    cancel: Optional[threading.Event] = None
    emit: Callable[[str, dict], None] = lambda kind, data: None

    def resolve(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        return candidate.resolve()

    def reject_write(self, path: Path) -> str | None:
        """No escopo de projeto, escrita fora da pasta (inclusive via link) é recusada."""
        session = self.session
        settings = getattr(session, "settings", None)
        if settings is None or settings.get("file_scope") != "project":
            return None
        root = Path(getattr(session, "workspace", self.workspace)).resolve()
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return f"Escopo do projeto: escrita recusada fora de {root}."
        return None


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[[dict, ToolContext], Any]
    risk: str = "read"
    group: str = "geral"
    source: str = "builtin"
    deferred: bool = False   # só fica visível após `find_tools` (servidores MCP grandes)

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        missing = [key for key in self.parameters.get("required", []) if key not in args]
        if "__invalid_json__" in args:
            return ToolResult.error("Argumentos inválidos (JSON malformado). Envie um objeto JSON válido.")
        if missing:
            return ToolResult.error(f"Parâmetros obrigatórios ausentes: {', '.join(missing)}")
        try:
            output = self.func(args, ctx)
        except Exception as error:  # a IA precisa ver o erro para se corrigir
            logger.exception("Ferramenta %s falhou", self.name)
            return ToolResult.error(f"{type(error).__name__}: {error}")
        result = output if isinstance(output, ToolResult) else ToolResult(text=str(output))
        if len(result.text) > MAX_TOOL_OUTPUT_CHARS:
            cut = len(result.text) - MAX_TOOL_OUTPUT_CHARS
            result.text = result.text[:MAX_TOOL_OUTPUT_CHARS] + f"\n\n[... saída truncada: mais {cut} caracteres]"
        return result


class ToolRegistry:
    """Coleção thread-safe de ferramentas (embutidas + MCP)."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._lock = threading.RLock()

    def register(self, tool: Tool) -> None:
        with self._lock:
            self._tools[tool.name] = tool

    def unregister_source(self, source: str) -> None:
        with self._lock:
            for name in [n for n, t in self._tools.items() if t.source == source]:
                del self._tools[name]

    def get(self, name: str) -> Optional[Tool]:
        with self._lock:
            return self._tools.get(name)

    def all(self) -> list[Tool]:
        with self._lock:
            return list(self._tools.values())

    def visible(self, groups: Optional[set[str]] = None, activated: Optional[set[str]] = None,
                mcp_servers: Optional[set[str]] = None) -> list[Tool]:
        """Ferramentas oferecidas ao modelo neste passo."""
        activated = activated or set()
        chosen = []
        for tool in self.all():
            if tool.source.startswith("mcp:"):
                server = tool.source[4:]
                if mcp_servers is not None and server not in mcp_servers:
                    continue
                if groups is not None and "mcp" not in groups:
                    continue
                if tool.deferred and tool.name not in activated:
                    continue
            elif groups is not None and tool.group not in groups:
                continue
            chosen.append(tool)
        return chosen

    def search(self, query: str, limit: int = 8, mcp_servers: Optional[set[str]] = None) -> list[Tool]:
        """Busca simples por palavras em nome/descrição (para ferramentas adiadas)."""
        # Radicais de 5 letras toleram variações ("decompile"/"decompilation", "engineering"/"engineer").
        words = {w[:5] if len(w) > 5 else w for w in query.lower().replace("_", " ").replace("-", " ").split()
                 if len(w) > 2}
        scored = []
        for tool in self.all():
            if not tool.deferred:
                continue
            if mcp_servers is not None and tool.source[4:] not in mcp_servers:
                continue
            name = tool.name.lower().replace("_", " ")
            desc = tool.description.lower()
            score = sum(3 for w in words if w in name) + sum(1 for w in words if w in desc)
            if score:
                scored.append((score, tool.name, tool))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [tool for _, _, tool in scored[:limit]]


def tool(registry: ToolRegistry, name: str, description: str, properties: dict | None = None,
         required: list[str] | None = None, risk: str = "read", group: str = "geral"):
    """Decorador curto para registrar ferramentas embutidas."""

    def decorator(func):
        registry.register(Tool(
            name=name,
            description=description,
            parameters={"type": "object", "properties": properties or {}, "required": required or []},
            func=func,
            risk=risk,
            group=group,
        ))
        return func

    return decorator
