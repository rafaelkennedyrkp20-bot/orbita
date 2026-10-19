"""
grok_cli.py — Integração com o Grok Build (xAI) usando a SUA conta Grok.

O Grok Build é um agente de programação completo da xAI (CLI `grok`, o mesmo que o
Grok Build Desktop empacota). Ele faz login pelo navegador (OAuth em auth.x.ai), guarda a
sessão em ~/.grok/auth.json e renova o token sozinho. Aqui ele é usado de duas formas:

    - como provedor selecionável ("Grok Build (conta xAI)"): cada mensagem vira um turno
      `grok -p ... --resume <sessão>` e a conversa continua do ponto onde parou;
    - como membro da equipe: o agente principal delega tarefas inteiras para ele.

O Grok Build usa as PRÓPRIAS ferramentas (ler/editar arquivos, terminal, web) na pasta de
trabalho do perfil. O token da conta nunca é lido por este programa: só o CLI oficial o usa.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

from agent.core.providers import ChatResult, Provider, ProviderError

logger = logging.getLogger(__name__)

GROK_HOME = Path.home() / ".grok"
INSTALL_COMMAND = "irm https://x.ai/cli/install.ps1 | iex"   # instalador oficial da xAI (Windows)
INSTALL_COMMAND_UNIX = "curl -fsSL https://x.ai/cli/install.sh | bash"   # instalador oficial (Linux/macOS)
# Terminais comuns no Linux: (programa, argumentos antes do comando)
TERMINALS = [("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]), ("kitty", []),
             ("alacritty", ["-e"]), ("xfce4-terminal", ["-x"]), ("tilix", ["-e"]), ("xterm", ["-e"])]
PERMISSION_MAP = {"perguntar": "default", "auto": "auto", "livre": "bypassPermissions"}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def executable() -> Optional[str]:
    found = shutil.which("grok")
    if found:
        return found
    for candidate in (GROK_HOME / "bin" / "grok.exe", Path.home() / ".local" / "bin" / "grok.exe",
                      GROK_HOME / "bin" / "grok", Path.home() / ".local" / "bin" / "grok"):
        if candidate.is_file():
            return str(candidate)
    return None


def is_logged_in() -> bool:
    """Sessão salva pelo `grok login` (o conteúdo não é lido) ou chave XAI_API_KEY."""
    return (GROK_HOME / "auth.json").is_file() or bool(os.environ.get("XAI_API_KEY"))


def status() -> dict:
    exe = executable()
    version = ""
    if exe:
        try:
            version = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=15,
                                     creationflags=_NO_WINDOW).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            version = "?"
    return {"installed": bool(exe), "path": exe or "", "version": version, "logged_in": bool(exe) and is_logged_in()}


def open_console(args: list[str]) -> None:
    """Abre uma janela de console (o login abre o navegador e pode pedir interação)."""
    if os.name == "nt":
        subprocess.Popen(["cmd.exe", "/c", "start", "Grok Build", "cmd.exe", "/k", *args])
        return
    _unix_terminal(shlex.join(args))


def _unix_terminal(command: str) -> None:
    """Roda o comando num terminal do sistema e o deixa aberto para a pessoa ler o resultado."""
    script = f"{command}; echo; read -r -p 'Pressione Enter para fechar…' _"
    if sys.platform == "darwin":
        subprocess.Popen(["osascript", "-e", f'tell application "Terminal" to do script {json.dumps(script)}'])
        return
    for program, flags in TERMINALS:
        if shutil.which(program):
            subprocess.Popen([program, *flags, "bash", "-c", script], start_new_session=True)
            return
    raise ProviderError(f"Nenhum terminal encontrado. Rode no seu terminal: {command}")


def login(device_code: bool = False) -> None:
    exe = executable()
    if not exe:
        raise ProviderError("O CLI do Grok não está instalado.")
    open_console([exe, "login", "--device-auth" if device_code else "--oauth"])


def logout() -> str:
    exe = executable()
    if not exe:
        return "CLI do Grok não instalado."
    result = subprocess.run([exe, "logout"], capture_output=True, text=True, timeout=30, creationflags=_NO_WINDOW)
    return (result.stdout or result.stderr).strip() or "Sessão encerrada."


def install() -> None:
    """Abre um terminal rodando o instalador oficial — só quando o usuário clica em Instalar."""
    if os.name != "nt":
        _unix_terminal(INSTALL_COMMAND_UNIX)
        return
    subprocess.Popen(["cmd.exe", "/c", "start", "Instalar Grok CLI", "powershell", "-NoExit", "-NoProfile",
                      "-ExecutionPolicy", "Bypass", "-Command", INSTALL_COMMAND])


def with_images(text: str, images: Optional[list[str]]) -> str:
    """O CLI do Grok não recebe imagem na linha de comando, mas o read_file dele abre e enxerga o arquivo."""
    found = [str(Path(path)) for path in images or () if Path(path).is_file()]
    if not found:
        return text
    listed = "\n".join(f"- {path}" for path in found)
    return f"{text}\n\n[Imagens anexadas pelo usuário — abra cada uma com read_file para ver:\n{listed}]"


class GrokBuildProvider(Provider):
    """Provedor "agente externo": o Grok Build executa o turno inteiro com as próprias ferramentas."""

    external_agent = True
    supports_native_tools = False

    def supports_vision(self, model: str) -> bool:
        return False

    def bridge_ready(self) -> bool:
        """Servidor MCP "orbita" registrado no Grok (equipe, skills e ferramentas do Órbita — grok_bridge.py)."""
        from agent.core import grok_bridge

        exe = executable()
        return bool(exe) and grok_bridge.ensure_registered(exe)

    def list_models(self) -> list[str]:
        exe = executable()
        if exe:
            try:
                output = subprocess.run([exe, "models"], capture_output=True, text=True, timeout=30,
                                        creationflags=_NO_WINDOW).stdout
                models = re.findall(r"^\s*[-*]\s+([\w.\-:/]+)", output, re.MULTILINE)
                if models:
                    return models
            except (OSError, subprocess.SubprocessError):
                pass
        return super().list_models()

    def chat(self, model, messages, tools=None, **kwargs) -> ChatResult:
        # Uso direto (sem sessão): manda a última mensagem do usuário como um turno isolado.
        last = next((m for m in reversed(messages) if m["role"] == "user"), {})
        prompt = with_images(last.get("content", ""), last.get("images"))
        text, _, usage = self.run_agent(prompt, model=model, cwd=str(Path.home()),
                                        on_text=kwargs.get("on_text"), on_reasoning=kwargs.get("on_reasoning"),
                                        cancel=kwargs.get("cancel"))
        return ChatResult(text=text, usage=usage, stop_reason="end_turn")

    def run_agent(self, prompt: str, *, model: str, cwd: str, session_id: Optional[str] = None,
                  rules: str = "", permission: str = "auto", max_turns: Optional[int] = None,
                  on_text: Optional[Callable[[str], None]] = None,
                  on_reasoning: Optional[Callable[[str], None]] = None,
                  on_tool: Optional[Callable[[str, dict], None]] = None,
                  cancel: Optional[threading.Event] = None,
                  env: Optional[dict] = None) -> tuple[str, Optional[str], dict]:
        """Executa um turno do Grok Build. Devolve (texto, id da sessão, uso de tokens)."""
        from agent.core.local_policy import refusal

        blocked = refusal(self.settings, self.name, self.cfg)
        if blocked:
            raise ProviderError(blocked)
        exe = executable()
        if not exe:
            raise ProviderError("Grok Build não instalado. Abra ⚙ Configurações → Conta Grok → Instalar.")
        if not is_logged_in():
            raise ProviderError("Entre na sua conta Grok: ⚙ Configurações → Conta Grok → Entrar.")
        prompt_file = None
        if len(prompt) > 6000:  # a linha de comando do Windows tem limite: prompts longos vão por arquivo
            import tempfile

            handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
            handle.write(prompt)
            handle.close()
            prompt_file = handle.name
            prompt_args = ["--prompt-file", prompt_file]
        else:
            prompt_args = ["-p", prompt]
        command = [exe, *prompt_args, "--output-format", "streaming-json", "--cwd", cwd,
                   "--permission-mode", PERMISSION_MAP.get(permission, "auto")]
        if model:
            command += ["-m", model]
        if session_id:
            command += ["--resume", session_id]
        elif rules:
            command += ["--rules", rules]
        if max_turns:
            command += ["--max-turns", str(max_turns)]

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                   encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
                                   env={**os.environ, **env} if env else None)
        watcher = None
        if cancel is not None:
            def watch():
                while process.poll() is None:
                    if cancel.wait(0.3):
                        process.kill()
                        return
            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()

        texts, usage, new_session, error = [], {}, session_id, ""
        for line in process.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            data = event.get("data")
            if kind == "text" and isinstance(data, str):
                texts.append(data)
                if on_text:
                    on_text(data)
            elif kind == "thought" and isinstance(data, str) and on_reasoning:
                on_reasoning(data)
            elif kind in ("tool_call", "tool_call_update") and on_tool:
                on_tool(kind, event)
            elif kind == "error":
                error = str(event.get("message") or data or event)
            elif kind == "end":
                new_session = event.get("sessionId") or new_session
                raw = event.get("usage") or {}
                usage = {"input_tokens": raw.get("input_tokens", 0) + raw.get("cache_read_input_tokens", 0),
                         "output_tokens": raw.get("output_tokens", 0) + raw.get("reasoning_tokens", 0),
                         "cost_usd": event.get("total_cost_usd")}
        stderr = process.stderr.read() if process.stderr else ""
        process.wait()
        if prompt_file:
            Path(prompt_file).unlink(missing_ok=True)
        if cancel is not None and cancel.is_set():
            return "".join(texts) or "(interrompido)", new_session, usage
        if process.returncode not in (0, None) and not texts:
            detail = error or stderr.strip()[-600:] or f"código {process.returncode}"
            if "authenticat" in detail.lower() or "login" in detail.lower():
                detail += "\nEntre novamente: ⚙ Configurações → Conta Grok → Entrar."
            raise ProviderError(f"Grok Build falhou: {detail}")
        return "".join(texts), new_session, usage
