"""
open_apps.py — Abre programas e aplicativos no Windows.
Suporta nome comum, executável ou pesquisa no PATH.
"""

import logging
import os
import subprocess
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

# Mapeamento de nomes comuns para executáveis/comandos no Windows
APP_ALIASES: dict[str, str | list] = {
    # Produtividade
    "bloco de notas": "notepad.exe",
    "notepad": "notepad.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe",
    "onenote": "onenote.exe",

    # Navegadores
    "chrome": ["chrome.exe", "google chrome"],
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "brave": "brave.exe",

    # Adobe
    "photoshop": "photoshop.exe",
    "illustrator": "illustrator.exe",
    "premiere": "premiere.exe",
    "after effects": "afterfx.exe",
    "acrobat": "acrobat.exe",

    # Desenvolvimento
    "vscode": "code.exe",
    "visual studio code": "code.exe",
    "vs code": "code.exe",
    "pycharm": "pycharm64.exe",
    "cursor": "cursor.exe",

    # Mídia
    "spotify": "spotify.exe",
    "vlc": "vlc.exe",
    "discord": "discord.exe",

    # Sistema
    "gerenciador de tarefas": "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "calculadora": "calc.exe",
    "calculator": "calc.exe",
    "explorador de arquivos": "explorer.exe",
    "file explorer": "explorer.exe",
    "painel de controle": "control.exe",
    "configurações": "ms-settings:",
    "prompt de comando": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",

    # Comunicação
    "whatsapp": "whatsapp.exe",
    "telegram": "telegram.exe",
    "teams": "teams.exe",
    "zoom": "zoom.exe",
    "slack": "slack.exe",

    # Jogos
    "steam": "steam.exe",

    # Utilitários
    "winrar": "winrar.exe",
    "7zip": "7zfm.exe",
    "obs": "obs64.exe",
    "obs studio": "obs64.exe",
}


def open_application(app_name: str) -> str:
    """
    Abre um aplicativo pelo nome comum, executável, caminho ou atalho do Menu Iniciar.

    Args:
        app_name: Nome comum ou caminho do aplicativo.

    Returns:
        Mensagem descritiva do resultado (sucesso só quando o Windows aceitou abrir).
    """
    name = app_name.strip().strip('"')
    lowered = name.lower()
    logger.info(f"Abrindo aplicativo: '{name}'")

    target = APP_ALIASES.get(lowered)
    candidates = target if isinstance(target, list) else ([target] if target else [])
    candidates.append(name)
    for candidate in candidates:
        opened = _try_open(candidate)
        if opened:
            return f"✅ {name} aberto ({opened})."

    shortcut = _find_start_menu_shortcut(lowered) or _find_executable(lowered)
    if shortcut and _try_open(shortcut):
        return f"✅ {name} aberto: {shortcut}"

    logger.warning(f"Aplicativo não encontrado: '{name}'")
    return (
        f"❌ Não encontrei '{name}'. "
        "Informe o caminho completo do executável ou o nome exato do atalho do Menu Iniciar."
    )


def _try_open(target: str) -> Optional[str]:
    """
    Tenta abrir sem usar shell (evita injeção de comandos).

    Returns:
        Descrição do que foi aberto, ou None se o Windows não encontrou o alvo.
    """
    try:
        if target.endswith(":") or "://" in target:
            os.startfile(target)  # protocolo (ms-settings:, https://...)
            return target
        if os.path.exists(target):
            os.startfile(target)
            return target
        exe = shutil.which(target)
        if exe:
            subprocess.Popen([exe], close_fds=True)
            return exe
        # ShellExecute resolve executáveis registrados em "App Paths" (chrome.exe, winword.exe...)
        os.startfile(target)
        return target
    except OSError:
        return None
    except Exception as e:
        logger.debug(f"Falha ao abrir '{target}': {e}")
        return None


def _find_start_menu_shortcut(name: str) -> Optional[str]:
    """Procura um atalho .lnk no Menu Iniciar cujo nome contenha o termo."""
    roots = [
        os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
    ]
    best: Optional[tuple[int, str]] = None
    for root in roots:
        if not os.path.isdir(root):
            continue
        for folder, _, files in os.walk(root):
            for file in files:
                if not file.lower().endswith(".lnk"):
                    continue
                stem = file[:-4].lower()
                if name in stem:
                    score = len(stem) - len(name)  # o nome mais parecido vence
                    if best is None or score < best[0]:
                        best = (score, os.path.join(folder, file))
    return best[1] if best else None


def _find_executable(name: str) -> Optional[str]:
    """
    Procura um executável em locais comuns do Windows (busca rasa).

    Args:
        name: Nome do aplicativo.

    Returns:
        Caminho do executável se encontrado.
    """
    search_dirs = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    ]
    compact = name.replace(" ", "")
    for base_dir in search_dirs:
        if not base_dir or not os.path.isdir(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            for file in files:
                lowered = file.lower()
                if lowered.endswith(".exe") and compact in lowered.replace(" ", "") and "unins" not in lowered:
                    return os.path.join(root, file)
            if root.count(os.sep) - base_dir.count(os.sep) >= 2:
                dirs.clear()
    return None


def list_running_apps() -> str:
    """
    Lista os processos em execução no Windows.

    Returns:
        Lista de processos ativos.
    """
    try:
        import psutil
        procs = []
        for proc in psutil.process_iter(["name", "pid", "memory_percent"]):
            try:
                info = proc.info
                procs.append((info["name"], info["pid"], info.get("memory_percent", 0)))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        procs.sort(key=lambda x: x[2], reverse=True)
        lines = ["Processos em execução (top 20 por memória):"]
        for name, pid, mem in procs[:20]:
            lines.append(f"  {name} (PID: {pid}) — {mem:.1f}% RAM")

        return "\n".join(lines)
    except ImportError:
        return "psutil não instalado. Execute: pip install psutil"
    except Exception as e:
        return f"Erro ao listar processos: {e}"


def close_application(app_name: str) -> str:
    """
    Fecha um aplicativo pelo nome do processo.

    Args:
        app_name: Nome do processo (ex: 'notepad.exe').

    Returns:
        Mensagem de resultado.
    """
    try:
        import psutil
        killed = []
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if app_name.lower() in proc.info["name"].lower():
                    proc.terminate()
                    killed.append(proc.info["name"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if killed:
            return f"✅ Encerrado: {', '.join(set(killed))}"
        return f"❌ Processo '{app_name}' não encontrado em execução."
    except ImportError:
        return "psutil não instalado. Execute: pip install psutil"
    except Exception as e:
        return f"Erro ao fechar aplicativo: {e}"
