"""
ghidra_setup.py — Baixar e instalar o Ghidra dentro do Órbita, para o motor nativo do REA.

Versão fixa, URL oficial do GitHub e SHA-256 conferido (corpo da release). Instala em
`models/tools/ghidra`, aponta `GHIDRA_INSTALL_DIR` (ambiente + `.env`) e devolve a pasta.
O REA herda essa variável (`inherit_env`) e passa a usar o Ghidra ao reconectar.

Reusa o download com progresso, a verificação de integridade e a extração da Caixa de
ferramentas (`toolbox`). Não roda o Ghidra; só o deixa pronto. O Ghidra precisa de JDK 21+.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from agent.core import toolbox
from agent.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

# Ghidra 12.1.4 — SHA-256 do corpo da release oficial (NationalSecurityAgency/ghidra), conferido em 2026-10-19.
GHIDRA = {
    "version": "12.1.4",
    "url": ("https://github.com/NationalSecurityAgency/ghidra/releases/download/"
            "Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip"),
    "sha256": "ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db",
    "size": 569649598,
    "zip_name": "ghidra_12.1.4_PUBLIC_20260921.zip",
    "dir_name": "ghidra_12.1.4_PUBLIC",
    "min_jdk": 21,
}
ENV_VAR = "GHIDRA_INSTALL_DIR"
INSTALL_ROOT = toolbox.TOOLS_DIR / "ghidra"
ENV_FILE = PROJECT_ROOT / ".env"

ProgressFn = Callable[[dict], None]


def _is_ghidra(path: Optional[Path]) -> bool:
    """Uma pasta é um Ghidra válido se tem os diretórios `support` e `Ghidra`."""
    try:
        return bool(path) and path.is_dir() and (path / "support").is_dir() and (path / "Ghidra").is_dir()
    except OSError:
        return False


def installed_dir() -> Optional[Path]:
    """Pasta do Ghidra em uso: a de `GHIDRA_INSTALL_DIR` (se válida) ou a instalada pela caixa."""
    env = os.environ.get(ENV_VAR)
    if env and _is_ghidra(Path(env)):
        return Path(env)
    managed = INSTALL_ROOT / GHIDRA["dir_name"]
    return managed if _is_ghidra(managed) else None


def java_status() -> dict:
    """Checa se há um JDK 21+ no PATH (requisito do Ghidra)."""
    exe = shutil.which("java")
    if not exe:
        return {"ok": False, "version": "", "reason": "Java não foi encontrado no PATH."}
    try:
        proc = subprocess.run([exe, "-version"], capture_output=True, timeout=20, creationflags=toolbox.NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "version": "", "reason": str(error)}
    text = (proc.stderr or proc.stdout).decode("utf-8", "replace")
    match = re.search(r'version "(\d+)', text)
    major = int(match.group(1)) if match else 0
    version = match.group(1) if match else "?"
    if major >= GHIDRA["min_jdk"]:
        return {"ok": True, "version": version, "reason": ""}
    return {"ok": False, "version": version,
            "reason": f"Ghidra precisa do JDK {GHIDRA['min_jdk']}+ (achei {version})."}


def status() -> dict:
    """Estado para a interface: instalado?, pasta, tamanho do download e situação do Java."""
    folder = installed_dir()
    java = java_status()
    return {
        "installed": folder is not None,
        "dir": str(folder) if folder else "",
        "version": GHIDRA["version"],
        "size": GHIDRA["size"],
        "size_label": toolbox.size_label(GHIDRA["size"]),
        "source": "github.com/NationalSecurityAgency/ghidra",
        "java_ok": java["ok"],
        "java_version": java["version"],
        "java_reason": java["reason"],
    }


def set_env(ghidra_dir: Path) -> None:
    """Aponta `GHIDRA_INSTALL_DIR` no ambiente e grava no `.env` (o REA herda ao reconectar)."""
    os.environ[ENV_VAR] = str(ghidra_dir)
    line = f"{ENV_VAR}={ghidra_dir}"
    try:
        text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    except OSError:
        text = ""
    pattern = re.compile(rf'(?m)^\s*#?\s*{re.escape(ENV_VAR)}=.*$')
    text = pattern.sub(lambda _: line, text) if pattern.search(text) else \
        (text.rstrip() + "\n" if text.strip() else "") + line + "\n"
    try:
        ENV_FILE.write_text(text, encoding="utf-8")
    except OSError as error:
        logger.warning("Não consegui gravar %s no .env: %s", ENV_VAR, error)


def install(on_progress: ProgressFn = lambda data: None,
            cancel: Optional[threading.Event] = None) -> Path:
    """Baixa, confere o SHA-256, extrai o Ghidra e aponta `GHIDRA_INSTALL_DIR`. Devolve a pasta."""
    import time

    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)
    part = INSTALL_ROOT / (GHIDRA["zip_name"] + ".part")
    staging = INSTALL_ROOT / ".staging"
    total = GHIDRA["size"]
    last = [0.0]

    def on_bytes(done: int) -> None:
        if time.time() - last[0] > 0.3 or done >= total:
            last[0] = time.time()
            on_progress({"state": "downloading", "pct": min(99, int(done * 100 / total)),
                         "done": done, "total": total})

    try:
        on_progress({"state": "downloading", "pct": 0, "done": 0, "total": total})
        toolbox.download(GHIDRA["url"], part, on_bytes, cancel, total + 1024)
        if part.stat().st_size != total:
            raise ValueError(f"Tamanho diferente do esperado ({part.stat().st_size} ≠ {total} bytes). Download apagado.")
        on_progress({"state": "verifying", "pct": 100})
        digest = toolbox._sha256(part)
        if digest != GHIDRA["sha256"]:
            raise ValueError(f"SHA-256 não confere (esperado {GHIDRA['sha256'][:12]}…, veio {digest[:12]}…). "
                             "Download apagado.")
        on_progress({"state": "extracting", "pct": 100})
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)
        toolbox._extract(part, staging, {"format": "zip"})
        extracted = staging / GHIDRA["dir_name"]
        if not _is_ghidra(extracted):
            found = next((p.parent.parent for p in staging.rglob("support/analyzeHeadless*")), None)
            extracted = found or extracted
        if not _is_ghidra(extracted):
            raise RuntimeError("O pacote extraído não parece um Ghidra válido.")
        target = INSTALL_ROOT / GHIDRA["dir_name"]
        shutil.rmtree(target, ignore_errors=True)
        extracted.rename(target)
    finally:
        part.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)

    set_env(target)
    on_progress({"state": "done", "pct": 100, "dir": str(target)})
    return target
