"""Inicializador rápido e reproduzível do Órbita no Windows."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / "venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"
REQUIREMENTS_STAMP = VENV_DIR / ".requirements.sha256"
OLLAMA_ENDPOINT = "http://127.0.0.1:11434"


def _print(message: str) -> None:
    print(f"[Órbita] {message}", flush=True)


def _venv_python() -> Path:
    return VENV_DIR / "Scripts" / "python.exe"


def _requirements_hash() -> str:
    return hashlib.sha256(REQUIREMENTS_FILE.read_bytes()).hexdigest()


def ensure_environment() -> Path:
    """Cria o venv e instala pacotes apenas quando requirements mudou."""
    python = _venv_python()
    if not python.is_file():
        _print("Criando ambiente isolado (apenas no primeiro uso)...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])

    current_hash = _requirements_hash()
    installed_hash = REQUIREMENTS_STAMP.read_text(encoding="ascii").strip() if REQUIREMENTS_STAMP.exists() else ""
    if installed_hash == current_hash:
        return python

    _print("Sincronizando dependências; isso só acontece após mudanças no projeto...")
    subprocess.check_call([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])
    REQUIREMENTS_STAMP.write_text(current_hash, encoding="ascii")
    return python


def _ollama_executable() -> str | None:
    candidates = (
        shutil.which("ollama"),
        PROJECT_ROOT / "models" / "llm" / "ollama" / "ollama.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
        Path(r"C:\Program Files\Ollama\ollama.exe"),
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def _ollama_is_ready() -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_ENDPOINT, timeout=1.5):
            return True
    except Exception:
        return False


def ensure_ollama() -> None:
    """Inicia o servidor local somente quando ele ainda não estiver ativo."""
    if _ollama_is_ready():
        return

    executable = _ollama_executable()
    if not executable:
        raise RuntimeError("Ollama não foi encontrado. Verifique models\\llm\\ollama ou instale o Ollama.")

    _print("Iniciando servidor Ollama local...")
    subprocess.Popen(
        [executable, "serve"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    for _ in range(12):
        time.sleep(0.5)
        if _ollama_is_ready():
            return
    raise RuntimeError("Ollama não respondeu a tempo. Execute o arquivo de verificação para detalhes.")


def create_shortcuts(only_if_missing: bool = False) -> int:
    """Atalhos com o ícone do app (Área de Trabalho e Menu Iniciar) que abrem sem console."""
    if os.name != "nt":
        return 0
    windowed = VENV_DIR / "Scripts" / "pythonw.exe"
    icon = PROJECT_ROOT / "agent" / "ui" / "web" / "app.ico"
    targets = [Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop" / "Órbita.lnk",
               Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Órbita.lnk"]
    if only_if_missing and all(t.exists() for t in targets):
        return 0
    if not windowed.is_file() or not icon.is_file():
        return 0
    for target in targets:
        script = (
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:AP_LNK);"
            "$s.TargetPath = $env:AP_EXE; $s.Arguments = '\"' + $env:AP_LAUNCHER + '\" --no-console';"
            "$s.WorkingDirectory = $env:AP_DIR; $s.IconLocation = $env:AP_ICON;"
            "$s.Description = 'Órbita — seu agente pessoal de IA'; $s.Save()"
        )
        env = {**os.environ, "AP_LNK": str(target), "AP_EXE": str(windowed), "AP_LAUNCHER": str(PROJECT_ROOT / "launcher.py"),
               "AP_DIR": str(PROJECT_ROOT), "AP_ICON": str(icon)}
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], env=env,
                       capture_output=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _print("Atalhos criados na Área de Trabalho e no Menu Iniciar.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inicializador do Órbita")
    parser.add_argument("--check", action="store_true", help="Executa apenas a verificação de saúde")
    parser.add_argument("--shortcut", action="store_true", help="Cria/atualiza os atalhos na Área de Trabalho e no Menu Iniciar")
    parser.add_argument("--no-console", action="store_true", help="Abre a interface sem janela de console")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        python = ensure_environment()
        try:
            ensure_ollama()
        except RuntimeError as error:
            # Sem Ollama o agente ainda funciona com provedores em nuvem (DeepSeek, GPT, Claude...).
            _print(f"Aviso: {error} Modelos locais ficarão indisponíveis.")
        if args.shortcut:
            return create_shortcuts()
        mode = "--check" if args.check else "--gui"
        if mode == "--gui":
            create_shortcuts(only_if_missing=True)
            # Sem janela de console: a interface abre como um programa normal do Windows.
            windowed = python.with_name("pythonw.exe")
            if windowed.is_file() and (sys.stdout is None or args.no_console):
                subprocess.Popen([str(windowed), str(PROJECT_ROOT / "agent" / "main.py"), mode], cwd=str(PROJECT_ROOT))
                return 0
        return subprocess.call([str(python), str(PROJECT_ROOT / "agent" / "main.py"), mode], cwd=str(PROJECT_ROOT))
    except subprocess.CalledProcessError as error:
        _print(f"Falha ao preparar o ambiente: {error}")
        return error.returncode or 1
    except Exception as error:
        _print(f"Falha ao iniciar: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
