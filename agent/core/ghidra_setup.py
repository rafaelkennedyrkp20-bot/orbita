"""
ghidra_setup.py — Ghidra gerenciado pelo backend, para o motor nativo do REA.

Sem botões: quando o REA vai conectar, o hub chama `GhidraBootstrap.ensure()`. Se já existe um
Ghidra válido (o do usuário em `GHIDRA_INSTALL_DIR` ou o gerenciado em `models/tools/ghidra`), só
aponta `os.environ["GHIDRA_INSTALL_DIR"]` antes de subir o subprocesso. Se falta, baixa em segundo
plano a versão fixa da release oficial, confere o SHA-256 e reconecta o REA. O `.env` nunca é gravado.

Extração atômica: download em `ghidra.zip.tmp`, extração em `ghidra.extract.tmp` (pasta irmã) e um
único rename para `ghidra` no fim. Erro, hash errado ou cancelamento não deixam pasta pela metade;
sobras de um processo morto no meio são apagadas no próximo início. O JDK 21+ só é informado;
sem ele, nada é baixado (a próxima conexão do REA confere de novo).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

from agent.core import toolbox

logger = logging.getLogger(__name__)

# Ghidra 12.1.4 — SHA-256 do corpo da release oficial (NationalSecurityAgency/ghidra), conferido em 2026-10-19.
GHIDRA = {
    "version": "12.1.4",
    "url": ("https://github.com/NationalSecurityAgency/ghidra/releases/download/"
            "Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip"),
    "sha256": "ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db",
    "size": 569649598,
    "dir_name": "ghidra_12.1.4_PUBLIC",
    "min_jdk": 21,
}
ENV_VAR = "GHIDRA_INSTALL_DIR"
TMP_ZIP = "ghidra.zip.tmp"
TMP_DIR = "ghidra.extract.tmp"


def _is_ghidra(path: Optional[Path]) -> bool:
    """Uma pasta é um Ghidra válido se tem os diretórios `support` e `Ghidra`."""
    try:
        return bool(path) and path.is_dir() and (path / "support").is_dir() and (path / "Ghidra").is_dir()
    except OSError:
        return False


def installed_dir(root: Path = toolbox.TOOLS_DIR) -> Optional[Path]:
    """Ghidra em uso: o de `GHIDRA_INSTALL_DIR` (se válido) ou o gerenciado em `<root>/ghidra`."""
    env = os.environ.get(ENV_VAR)
    if env and _is_ghidra(Path(env)):
        return Path(env)
    managed = root / "ghidra"
    return managed if _is_ghidra(managed) else None


def prepare_env(root: Path = toolbox.TOOLS_DIR) -> Optional[Path]:
    """Rápido (só confere pastas): aponta `GHIDRA_INSTALL_DIR` no processo, respeitando o do usuário."""
    folder = installed_dir(root)
    if folder is not None:
        os.environ[ENV_VAR] = str(folder)
    return folder


def wants_ghidra(cfg: dict) -> bool:
    """O servidor é o REA (que usa o Ghidra como motor nativo)?"""
    return any("rea-agents" in str(part) for part in [cfg.get("command", ""), *(cfg.get("args") or [])])


def java_status() -> dict:
    """Checa se há um JDK 21+ no PATH (requisito do Ghidra). Roda um processo: nunca na thread da UI."""
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


def _clean_temp(root: Path) -> None:
    (root / TMP_ZIP).unlink(missing_ok=True)
    shutil.rmtree(root / TMP_DIR, ignore_errors=True)


def _extract_zip(archive: Path, dest: Path, cancel: threading.Event, on_pct: Callable[[int], None]) -> None:
    """Extrai membro a membro (dá para cancelar e mostrar progresso), recusando caminhos para fora."""
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        bad = [m.filename for m in members if not toolbox._inside(dest, m.filename)]
        if bad:
            raise ValueError(f"Pacote com caminho perigoso: {bad[0]}")
        for index, member in enumerate(members, 1):
            if cancel.is_set():
                raise InterruptedError("Instalação do Ghidra cancelada.")
            zf.extract(member, dest)
            if index % 200 == 0:
                on_pct(int(index * 100 / len(members)))


def install(root: Path, cancel: threading.Event, on_progress: Callable[[str, int], None]) -> Path:
    """Baixa, confere o SHA-256 e extrai atomicamente em `<root>/ghidra`. Não toca no ambiente."""
    root.mkdir(parents=True, exist_ok=True)
    _clean_temp(root)
    part, staging, target = root / TMP_ZIP, root / TMP_DIR, root / "ghidra"
    total = GHIDRA["size"]
    last = [0.0]

    def on_bytes(done: int) -> None:
        if time.monotonic() - last[0] > 1 or done >= total:
            last[0] = time.monotonic()
            on_progress("downloading", min(99, int(done * 100 / total)))

    try:
        on_progress("downloading", 0)
        toolbox.download(GHIDRA["url"], part, on_bytes, cancel, total + 1024)
        if part.stat().st_size != total:
            raise ValueError(f"Tamanho diferente do esperado ({part.stat().st_size} ≠ {total} bytes).")
        on_progress("verifying", 100)
        digest = toolbox._sha256(part)
        if digest != GHIDRA["sha256"]:
            raise ValueError(f"SHA-256 não confere (esperado {GHIDRA['sha256'][:12]}…, veio {digest[:12]}…).")
        on_progress("extracting", 0)
        staging.mkdir()
        _extract_zip(part, staging, cancel, lambda pct: on_progress("extracting", pct))
        extracted = staging / GHIDRA["dir_name"]
        if not _is_ghidra(extracted):
            raise RuntimeError("O pacote extraído não parece um Ghidra válido.")
        if cancel.is_set():
            raise InterruptedError("Instalação do Ghidra cancelada.")
        if target.exists():   # sobra inválida (senão nem teríamos baixado): é a pasta gerenciada
            shutil.rmtree(target)
        extracted.rename(target)   # o único passo que publica a instalação
    finally:
        _clean_temp(root)
    return target


class GhidraBootstrap:
    """Ciclo de vida do Ghidra: aponta, instala em segundo plano e publica o estado para a interface."""

    def __init__(self, root: Path = toolbox.TOOLS_DIR):
        self.root = root
        self.listeners: list[Callable[[], None]] = []
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._state = {"state": "idle", "phase": "", "pct": 0, "dir": "", "message": "",
                       "java_ok": None, "java_version": ""}

    def status(self) -> dict:
        """Estado real: idle | checking | installing (phase/pct) | installed | missing_jdk | error."""
        with self._lock:
            return {**self._state, "version": GHIDRA["version"], "size_label": toolbox.size_label(GHIDRA["size"]),
                    "source": "github.com/NationalSecurityAgency/ghidra"}

    def _set(self, **changes) -> None:
        with self._lock:
            self._state.update(changes)
        for listener in list(self.listeners):
            try:
                listener()
            except Exception:
                logger.debug("listener do Ghidra falhou", exc_info=True)

    def ensure(self, on_installed: Optional[Callable[[], None]] = None) -> Optional[Path]:
        """Chamado antes de conectar o REA. Aponta o caminho já (rápido); confere o JDK e, se falta o
        Ghidra, instala numa thread. `on_installed` roda depois de uma instalação nova (reconectar)."""
        folder = prepare_env(self.root)
        with self._lock:
            busy = self._thread is not None and self._thread.is_alive()
            settled = self._state["state"] in ("installed", "missing_jdk")
        if busy or (settled and folder is not None) or self._cancel.is_set():
            return folder
        self._thread = threading.Thread(target=self._work, args=(on_installed,), name="ghidra-bootstrap",
                                        daemon=True)
        self._thread.start()
        return folder

    def _work(self, on_installed: Optional[Callable[[], None]]) -> None:
        fresh = False
        try:
            self._set(state="checking", message="")
            _clean_temp(self.root)
            folder = prepare_env(self.root)
            java = java_status()
            if folder is None and not java["ok"]:   # sem JDK o Ghidra não roda: não baixa 570 MB à toa
                self._set(state="missing_jdk", phase="", pct=0, dir="", message=java["reason"], java_ok=False,
                          java_version=java["version"])
                return
            if folder is None:
                self._set(state="installing", phase="downloading", pct=0)
                folder = install(self.root, self._cancel,
                                 lambda phase, pct: self._set(state="installing", phase=phase, pct=pct))
                os.environ[ENV_VAR] = str(folder)
                fresh = True
                logger.info("Ghidra %s instalado em %s", GHIDRA["version"], folder)
            self._set(state="installed" if java["ok"] else "missing_jdk", phase="", pct=100, dir=str(folder),
                      message=java["reason"], java_ok=java["ok"], java_version=java["version"])
        except Exception as error:
            logger.warning("Ghidra não foi instalado: %s", error)
            self._set(state="error", phase="", message=str(error)[:300] or type(error).__name__)
            return
        if fresh and on_installed is not None and not self._cancel.is_set():
            try:
                on_installed()
            except Exception:
                logger.warning("Reconectar depois de instalar o Ghidra falhou", exc_info=True)

    def wait(self, timeout: Optional[float] = None) -> bool:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def shutdown(self) -> None:
        """Ao fechar o app: interrompe o download/extração (o `finally` apaga as sobras)."""
        self._cancel.set()
