"""
open_apps.py — Abre programas e aplicativos (Windows, Linux e macOS).
Suporta nome comum, executável, pesquisa no PATH e atalhos do menu (Menu Iniciar ou .desktop).
"""

import logging
import os
import re
import subprocess
import shutil
import sys
from typing import Optional

logger = logging.getLogger(__name__)

IS_WINDOWS = os.name == "nt"

# No Linux os nomes variam por distribuição: tenta cada um até achar um instalado.
LINUX_ALIASES: dict[str, list[str]] = {
    "bloco de notas": ["gnome-text-editor", "gedit", "kate", "mousepad", "xed"],
    "notepad": ["gnome-text-editor", "gedit", "kate", "mousepad", "xed"],
    "calculadora": ["gnome-calculator", "kcalc", "galculator", "qalculate-gtk"],
    "calculator": ["gnome-calculator", "kcalc", "galculator", "qalculate-gtk"],
    "explorador de arquivos": ["nautilus", "dolphin", "thunar", "nemo", "pcmanfm"],
    "file explorer": ["nautilus", "dolphin", "thunar", "nemo", "pcmanfm"],
    "terminal": ["x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "kitty", "alacritty"],
    "gerenciador de tarefas": ["gnome-system-monitor", "plasma-systemmonitor", "ksysguard", "xfce4-taskmanager"],
    "task manager": ["gnome-system-monitor", "plasma-systemmonitor", "ksysguard", "xfce4-taskmanager"],
    "configurações": ["gnome-control-center", "systemsettings", "xfce4-settings-manager"],
    "chrome": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "vscode": ["code", "codium"], "visual studio code": ["code", "codium"], "vs code": ["code", "codium"],
    "obs": ["obs"], "obs studio": ["obs"], "word": ["libreoffice --writer"], "excel": ["libreoffice --calc"],
    "powerpoint": ["libreoffice --impress"],
}


def open_path(target: str) -> None:
    """Abre arquivo, pasta ou link com o programa padrão do sistema."""
    if IS_WINDOWS:
        os.startfile(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target], close_fds=True)
    else:
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if not opener:
            raise OSError("xdg-open não encontrado")
        subprocess.Popen([opener, "open", target] if opener.endswith("gio") else [opener, target], close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

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

    if IS_WINDOWS:
        target = APP_ALIASES.get(lowered)
        candidates = target if isinstance(target, list) else ([target] if target else [])
    else:
        target = APP_ALIASES.get(lowered)
        exes = target if isinstance(target, list) else ([target] if target else [])
        candidates = LINUX_ALIASES.get(lowered, []) + [e[:-4] for e in exes if e.endswith(".exe")]
    candidates.append(name)
    for candidate in candidates:
        opened = _try_open(candidate)
        if opened:
            return f"✅ {name} aberto ({opened})."

    if IS_WINDOWS:
        shortcut = _find_start_menu_shortcut(lowered) or _find_executable(lowered)
        if shortcut and _try_open(shortcut):
            return f"✅ {name} aberto: {shortcut}"
    else:
        launched = _launch_desktop_entry(lowered)
        if launched:
            return f"✅ {name} aberto ({launched})."

    logger.warning(f"Aplicativo não encontrado: '{name}'")
    return (
        f"❌ Não encontrei '{name}'. "
        + ("Informe o caminho completo do executável ou o nome exato do atalho do Menu Iniciar." if IS_WINDOWS
           else "Informe o comando do programa (como aparece no terminal) ou o caminho completo.")
    )


def _try_open(target: str) -> Optional[str]:
    """
    Tenta abrir sem usar shell (evita injeção de comandos).

    Returns:
        Descrição do que foi aberto, ou None se o Windows não encontrou o alvo.
    """
    try:
        if target.endswith(":") or "://" in target:
            if not IS_WINDOWS and target.endswith(":"):
                return None   # protocolos ms-settings: só existem no Windows
            open_path(target)  # protocolo (ms-settings:, https://...)
            return target
        if os.path.exists(target):
            if not IS_WINDOWS and os.access(target, os.X_OK) and os.path.isfile(target):
                subprocess.Popen([target], close_fds=True, start_new_session=True)
            else:
                open_path(target)
            return target
        program, *extra = target.split() if not IS_WINDOWS else [target]
        exe = shutil.which(program)
        if exe:
            subprocess.Popen([exe, *extra], close_fds=True, start_new_session=not IS_WINDOWS,
                             stdout=subprocess.DEVNULL if not IS_WINDOWS else None,
                             stderr=subprocess.DEVNULL if not IS_WINDOWS else None)
            return exe
        if not IS_WINDOWS:
            return None
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


def _desktop_dirs() -> list[str]:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    extra = ["/var/lib/flatpak/exports/share", os.path.expanduser("~/.local/share/flatpak/exports/share")]
    return [os.path.join(d, "applications") for d in [data_home, *data_dirs, *extra]]


def find_desktop_entry(name: str, dirs: Optional[list[str]] = None) -> Optional[tuple[str, list[str]]]:
    """Atalho .desktop (menu de aplicativos do Linux) cujo Name contém o termo → (Name, comando)."""
    best: Optional[tuple[int, str, list[str]]] = None
    for folder in dirs or _desktop_dirs():
        if not os.path.isdir(folder):
            continue
        for file in sorted(os.listdir(folder)):
            if not file.endswith(".desktop"):
                continue
            try:
                with open(os.path.join(folder, file), encoding="utf-8", errors="replace") as handle:
                    text = handle.read().split("\n[", 1)[0]   # só a seção [Desktop Entry]
            except OSError:
                continue
            if re.search(r"^(NoDisplay|Hidden)=true", text, re.M):
                continue
            names = re.findall(r"^Name(?:\[[^\]]+\])?=(.+)$", text, re.M)
            exec_line = re.search(r"^Exec=(.+)$", text, re.M)
            if not exec_line:
                continue
            for title in names:
                if name in title.lower():
                    score = len(title) - len(name)
                    if best is None or score < best[0]:
                        argv = [a for a in exec_line.group(1).split() if not re.fullmatch(r"%[a-zA-Z]", a)]
                        best = (score, names[0], argv)
    return (best[1], best[2]) if best else None


def _launch_desktop_entry(name: str) -> Optional[str]:
    entry = find_desktop_entry(name)
    if not entry or not entry[1] or not shutil.which(entry[1][0].strip('"')):
        return None
    try:
        subprocess.Popen([a.strip('"') for a in entry[1]], close_fds=True, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return entry[0]
    except OSError:
        return None


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
