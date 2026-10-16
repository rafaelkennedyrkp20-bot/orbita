"""
grok_bridge.py — Ponte MCP entre o Grok Build e o Órbita.

Com o Grok Build como modelo principal, o turno inteiro roda no CLI dele, com as ferramentas DELE: a equipe
do Órbita (delegate_task com DeepSeek, GLM…), as skills, as ferramentas de criação e o check_web_page não
existiam para ele — e ele saía procurando "DeepSeek" e "Blender" pelo PC.

Como funciona:
    - o Órbita abre um servidor local (127.0.0.1, porta aleatória, token) e grava porta+token em
      data/grok_bridge.json; enquanto o Grok roda um turno, a sessão do Órbita fica "anexada";
    - o Grok inicia este módulo como servidor MCP "orbita" (registrado uma vez com `grok mcp add`);
    - cada list_tools/call_tool do Grok vira um pedido ao Órbita, que executa com as permissões e o painel
      ao vivo de sempre. Órbita fechado ou nenhum turno do Grok ativo: a ponte não oferece ferramentas.

Uso pelo Grok:  python -m agent.core.grok_bridge   (stdio MCP)
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from agent.core.config import DATA_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

SERVER_NAME = "orbita"
INFO_FILE = DATA_DIR / "grok_bridge.json"
INFO_ENV = "ORBITA_GROK_BRIDGE_INFO"     # testes apontam para outro arquivo
KEY_ENV = "ORBITA_GROK_BRIDGE_KEY"       # qual sessão do Órbita este processo do Grok representa
# Ferramentas do Órbita que fazem sentido para o Grok (ler/editar/terminal ele já tem as dele).
EXPOSED = ("delegate_task", "use_skill", "toolbox_list", "toolbox_install", "check_web_page")
CALL_TIMEOUT = 4 * 3600                  # uma equipe grande pode levar bastante tempo
TURN_REMINDER = (f"Lembrete do Órbita: equipe/agentes/outros modelos → delegate_task do MCP '{SERVER_NAME}'; "
                 "Blender/Godot/ImageMagick → toolbox_list/toolbox_install. Não procure isso pelo PC.")


# ── Lado do Órbita ───────────────────────────────────────────

class Bridge:
    """Servidor local que recebe os pedidos da ponte e executa na sessão do Grok anexada."""

    def __init__(self, info_file: Path = INFO_FILE):
        self.info_file = info_file
        self.token = secrets.token_urlsafe(24)
        self.sessions: dict[str, Any] = {}     # chave do processo do Grok → sessão do Órbita
        self._server: Optional[socketserver.ThreadingTCPServer] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._server is not None:
            return
        bridge = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    request = json.loads(self.rfile.readline().decode("utf-8") or "{}")
                    reply = bridge.handle(request)
                except Exception as error:   # um pedido ruim nunca derruba o Órbita
                    logger.exception("Ponte do Grok: pedido falhou")
                    reply = {"error": str(error)}
                self.wfile.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))

        socketserver.ThreadingTCPServer.daemon_threads = True
        self._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, name="grok-bridge", daemon=True).start()
        self.info_file.parent.mkdir(parents=True, exist_ok=True)
        self.info_file.write_text(json.dumps({"port": self._server.server_address[1], "token": self.token,
                                              "pid": os.getpid()}), encoding="utf-8")

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        try:
            if json.loads(self.info_file.read_text(encoding="utf-8")).get("token") == self.token:
                self.info_file.unlink()
        except (OSError, ValueError):
            pass

    @contextmanager
    def attached(self, session):
        """Durante o turno do Grok, os pedidos com esta chave vão para esta sessão. A chave segue para o
        processo do Grok pela variável KEY_ENV e dele para a ponte — ajudantes em paralelo não se misturam."""
        key = secrets.token_urlsafe(12)
        with self._lock:
            self.sessions[key] = session
        try:
            yield key
        finally:
            with self._lock:
                self.sessions.pop(key, None)

    def handle(self, request: dict) -> dict:
        if not secrets.compare_digest(str(request.get("token", "")), self.token):
            return {"error": "token inválido"}
        with self._lock:
            session = self.sessions.get(str(request.get("key", "")))
        op = request.get("op")
        if op == "tools":
            return {"tools": session.bridge_tools() if session is not None else []}
        if op == "call":
            if session is None:
                return {"text": "O Órbita não está com um turno do Grok ativo.", "is_error": True}
            result = session.run_bridge_tool(str(request.get("name", "")), request.get("arguments") or {})
            return {"text": result.text, "is_error": bool(result.is_error)}
        return {"error": f"operação desconhecida: {op}"}


_bridge: Optional[Bridge] = None
_registered = False


def get_bridge() -> Bridge:
    global _bridge
    if _bridge is None:
        _bridge = Bridge()
        _bridge.start()
        import atexit

        atexit.register(_bridge.stop)
    return _bridge


def bridge_python() -> str:
    """Python do Órbita em modo console (o pythonw da janela não serve para stdio)."""
    exe = Path(sys.executable)
    if exe.name.lower().startswith("pythonw"):
        console = exe.with_name(exe.name.lower().replace("pythonw", "python"))
        if console.is_file():
            return str(console)
    return str(exe)


def registration_command(grok_exe: str) -> list[str]:
    return [grok_exe, "mcp", "add", SERVER_NAME, "-e", f"PYTHONPATH={PROJECT_ROOT}",
            "--", bridge_python(), "-m", "agent.core.grok_bridge"]


def ensure_registered(grok_exe: str) -> bool:
    """Registra (ou atualiza) o servidor "orbita" no Grok, uma vez por execução do Órbita."""
    global _registered
    if _registered:
        return True
    try:
        done = subprocess.run(registration_command(grok_exe), capture_output=True, text=True, timeout=30,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _registered = done.returncode == 0
        if not _registered:
            logger.warning("Não consegui registrar a ponte no Grok: %s", (done.stderr or done.stdout).strip()[-300:])
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Não consegui registrar a ponte no Grok: %s", error)
    return _registered


def rules_text(team_text: str = "") -> str:
    """Instruções para o Grok: o que ele ganha do Órbita e como usar (vai em --rules)."""
    text = ("## Você está rodando dentro do Órbita\n"
            f"O servidor MCP '{SERVER_NAME}' te dá as ferramentas do Órbita: delegate_task (a equipe de agentes do "
            "Órbita, que pode usar outros modelos/APIs configurados, como DeepSeek e GLM), use_skill (skills do "
            "Órbita, ex.: modelagem-3d, jogos-godot, jogos-web, creative-pipeline), toolbox_list/toolbox_install "
            "(Blender, Godot, ImageMagick, OpenSCAD, FFmpeg) e check_web_page (testa uma página num navegador "
            "invisível). Quando o usuário pedir agentes, equipe, outros modelos ou APIs, use delegate_task — não "
            "procure programas de IA, chaves ou instalações pelo PC. Para Blender/Godot etc., use toolbox_list e "
            "toolbox_install em vez de vasculhar pastas.")
    return text + ("\n\n" + team_text if team_text else "")


# ── Lado do Grok (processo da ponte) ─────────────────────────

def load_info(path: Optional[Path] = None) -> Optional[dict]:
    path = path or Path(os.environ.get(INFO_ENV) or INFO_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if data.get("port") and data.get("token") else None
    except (OSError, ValueError):
        return None


def request(info: Optional[dict], payload: dict, timeout: float = 10) -> dict:
    """Um pedido ao Órbita. Órbita fechado = nenhuma ferramenta."""
    if not info:
        return {"tools": [], "text": "O Órbita não está aberto.", "is_error": True}
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=10) as conn:
            conn.settimeout(timeout)
            message = {"key": os.environ.get(KEY_ENV, ""), **payload, "token": info["token"]}
            conn.sendall((json.dumps(message) + "\n").encode("utf-8"))
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data.decode("utf-8") or "{}")
    except (OSError, ValueError) as error:
        return {"tools": [], "text": f"O Órbita não respondeu ({error}).", "is_error": True}


def main() -> None:
    import anyio
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    async def list_tools(ctx, params):
        reply = await anyio.to_thread.run_sync(lambda: request(load_info(), {"op": "tools"}))
        return types.ListToolsResult(tools=[
            types.Tool(name=t["name"], description=t.get("description", ""),
                       input_schema=t.get("parameters") or {"type": "object", "properties": {}})
            for t in reply.get("tools") or []])

    async def call_tool(ctx, params):
        payload = {"op": "call", "name": params.name, "arguments": params.arguments or {}}
        reply = await anyio.to_thread.run_sync(lambda: request(load_info(), payload, timeout=CALL_TIMEOUT))
        text = reply.get("text") or reply.get("error") or "(sem resposta)"
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                    is_error=bool(reply.get("is_error") or reply.get("error")))

    server = Server(SERVER_NAME, on_list_tools=list_tools, on_call_tool=call_tool,
                    instructions="Ferramentas do Órbita: equipe de agentes, skills e programas de criação.")

    async def run():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)


if __name__ == "__main__":
    main()
