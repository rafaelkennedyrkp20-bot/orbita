"""Ghidra gerenciado pelo backend (motor nativo do REA): sem botões, sem .env, extração atômica.

Sem rede: o download é sempre falso (monkeypatch em toolbox.download).
"""

import hashlib
import os
import threading
import time
import zipfile
from pathlib import Path

import pytest

from agent.core import ghidra_setup, toolbox
from agent.core.config import PROJECT_ROOT
from agent.core.mcp_hub import MCPHub, ServerState
from agent.core.tools import ToolRegistry

DIR_NAME = ghidra_setup.GHIDRA["dir_name"]


def _fake_ghidra_zip(path: Path, extra: int = 0) -> bytes:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{DIR_NAME}/support/analyzeHeadless.bat", "echo headless")
        zf.writestr(f"{DIR_NAME}/Ghidra/application.properties", "x")
        zf.writestr(f"{DIR_NAME}/ghidraRun.bat", "echo run")
        for i in range(extra):
            zf.writestr(f"{DIR_NAME}/Ghidra/Features/f{i}.txt", "y" * 10)
    return path.read_bytes()


def _make_ghidra(folder: Path) -> Path:
    (folder / "support").mkdir(parents=True)
    (folder / "Ghidra").mkdir()
    return folder


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Raiz isolada, sem GHIDRA_INSTALL_DIR herdado e Java 21 "instalado"."""
    monkeypatch.setenv("GHIDRA_INSTALL_DIR", "x")   # registra o valor original para restaurar no fim
    monkeypatch.delenv("GHIDRA_INSTALL_DIR")
    monkeypatch.setattr(ghidra_setup, "java_status", lambda: {"ok": True, "version": "21", "reason": ""})
    return tmp_path / "tools"


def _serve_zip(monkeypatch, tmp_path, data=None, *, fail_after=None, error=None, wait=None):
    """Troca o download real por um que escreve `data` (ou para no meio com `error`)."""
    if data is None:
        data = _fake_ghidra_zip(tmp_path / "src.zip")
    monkeypatch.setitem(ghidra_setup.GHIDRA, "sha256", hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(ghidra_setup.GHIDRA, "size", len(data))
    calls = []

    def fake_download(url, target, on_bytes, cancel=None, limit=0):
        calls.append(url)
        if wait is not None:
            while not (cancel is not None and cancel.is_set()):
                target.write_bytes(data[: len(data) // 2])
                wait.set()
                time.sleep(0.01)
            raise InterruptedError("Download cancelado.")
        if fail_after is not None:
            target.write_bytes(data[:fail_after])
            on_bytes(fail_after)
            raise error or OSError("conexão caiu")
        target.write_bytes(data)
        on_bytes(len(data))
    monkeypatch.setattr(toolbox, "download", fake_download)
    return calls


def _leftovers(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir() if p.name.endswith(".tmp")) if root.exists() else []


def _wait(boot, timeout=5.0):
    assert boot.wait(timeout), "bootstrap não terminou a tempo"


# ── Detecção ────────────────────────────────────────────────

def test_is_ghidra_and_installed_dir(tmp_path, env):
    good = _make_ghidra(tmp_path / "g")
    bad = tmp_path / "b"
    bad.mkdir()
    assert ghidra_setup._is_ghidra(good)
    assert not ghidra_setup._is_ghidra(bad)
    assert ghidra_setup.installed_dir(env) is None

    os.environ["GHIDRA_INSTALL_DIR"] = str(good)
    assert ghidra_setup.installed_dir(env) == good
    os.environ["GHIDRA_INSTALL_DIR"] = str(bad)
    assert ghidra_setup.installed_dir(env) is None
    managed = _make_ghidra(env / "ghidra")
    assert ghidra_setup.installed_dir(env) == managed   # env inválido: cai para a pasta gerenciada


def test_java_status_parses_major_version(monkeypatch):
    monkeypatch.setattr(ghidra_setup.shutil, "which", lambda name: "java")

    class Ok:
        stderr = b'openjdk version "21.0.9" 2025-10-21 LTS'
        stdout = b""
    monkeypatch.setattr(ghidra_setup.subprocess, "run", lambda *a, **k: Ok())
    status = ghidra_setup.java_status()
    assert status["ok"] and status["version"] == "21"

    class Old:
        stderr = b'java version "17.0.1"'
        stdout = b""
    monkeypatch.setattr(ghidra_setup.subprocess, "run", lambda *a, **k: Old())
    status = ghidra_setup.java_status()
    assert not status["ok"] and "21" in status["reason"]

    monkeypatch.setattr(ghidra_setup.shutil, "which", lambda name: None)
    assert not ghidra_setup.java_status()["ok"]


def test_wants_ghidra_only_for_rea():
    assert ghidra_setup.wants_ghidra({"command": "npx", "args": ["-y", "rea-agents@6.5.0", "mcp"]})
    assert not ghidra_setup.wants_ghidra({"command": "npx", "args": ["-y", "@playwright/mcp@latest"]})
    assert not ghidra_setup.wants_ghidra({"url": "https://exemplo.com/mcp"})


# ── Inicialização: aponta o caminho sem gravar .env ─────────

def test_prepare_env_respects_user_dir(tmp_path, env):
    user = _make_ghidra(tmp_path / "meu_ghidra")
    _make_ghidra(env / "ghidra")
    os.environ["GHIDRA_INSTALL_DIR"] = str(user)
    assert ghidra_setup.prepare_env(env) == user
    assert os.environ["GHIDRA_INSTALL_DIR"] == str(user)   # o do usuário vence


def test_prepare_env_points_to_managed_folder(env):
    managed = _make_ghidra(env / "ghidra")
    assert ghidra_setup.prepare_env(env) == managed
    assert os.environ["GHIDRA_INSTALL_DIR"] == str(managed)


def test_prepare_env_without_folder(env):
    assert ghidra_setup.prepare_env(env) is None
    assert "GHIDRA_INSTALL_DIR" not in os.environ


def test_bootstrap_with_folder_only_points_path(tmp_path, monkeypatch, env):
    managed = _make_ghidra(env / "ghidra")
    calls = _serve_zip(monkeypatch, tmp_path)
    installed = []
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.ensure(on_installed=lambda: installed.append(1))
    assert os.environ["GHIDRA_INSTALL_DIR"] == str(managed)   # já no ambiente ao voltar de ensure()
    _wait(boot)
    assert calls == [] and installed == []
    assert boot.status()["state"] == "installed" and boot.status()["dir"] == str(managed)


def test_bootstrap_without_folder_installs_in_background(tmp_path, monkeypatch, env):
    calls = _serve_zip(monkeypatch, tmp_path)
    installed = []
    seen = []
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.listeners.append(lambda: seen.append(boot.status()["state"]))
    start = time.monotonic()
    boot.ensure(on_installed=lambda: installed.append(os.environ.get("GHIDRA_INSTALL_DIR")))
    assert time.monotonic() - start < 0.5   # não bloqueia quem chamou
    _wait(boot)
    target = env / "ghidra"
    assert len(calls) == 1
    assert ghidra_setup._is_ghidra(target)
    assert installed == [str(target)]                       # reconecta já com o caminho no ambiente
    assert boot.status()["state"] == "installed"
    assert "installing" in seen
    assert _leftovers(env) == []
    boot.ensure(on_installed=lambda: installed.append("de novo"))
    _wait(boot)
    assert len(calls) == 1 and len(installed) == 1           # idempotente


def test_network_abort_keeps_folder_intact(tmp_path, monkeypatch, env):
    _serve_zip(monkeypatch, tmp_path, fail_after=100, error=OSError("conexão caiu"))
    installed = []
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.ensure(on_installed=lambda: installed.append(1))
    _wait(boot)
    status = boot.status()
    assert status["state"] == "error" and "conexão caiu" in status["message"]
    assert not (env / "ghidra").exists()
    assert _leftovers(env) == []
    assert installed == [] and "GHIDRA_INSTALL_DIR" not in os.environ


def test_bad_sha256_does_not_install(tmp_path, monkeypatch, env):
    _serve_zip(monkeypatch, tmp_path)
    monkeypatch.setitem(ghidra_setup.GHIDRA, "sha256", "0" * 64)   # errado de propósito
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.ensure()
    _wait(boot)
    assert boot.status()["state"] == "error" and "SHA-256" in boot.status()["message"]
    assert not (env / "ghidra").exists()
    assert _leftovers(env) == []


def test_cancel_on_shutdown_leaves_nothing(tmp_path, monkeypatch, env):
    started = threading.Event()
    _serve_zip(monkeypatch, tmp_path, wait=started)
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.ensure()
    assert started.wait(5)
    assert any(p.name.endswith(".tmp") for p in env.iterdir())   # baixando no .tmp
    boot.shutdown()
    _wait(boot)
    assert not (env / "ghidra").exists()
    assert _leftovers(env) == []


def test_cancel_during_extraction_leaves_nothing(tmp_path, monkeypatch, env):
    data = _fake_ghidra_zip(tmp_path / "src.zip", extra=40)
    _serve_zip(monkeypatch, tmp_path, data)
    boot = ghidra_setup.GhidraBootstrap(env)
    real_extract = zipfile.ZipFile.extract
    count = [0]

    def slow_extract(self, member, path=None, pwd=None):
        count[0] += 1
        if count[0] == 5:
            boot.shutdown()   # app fechando no meio da extração
        return real_extract(self, member, path, pwd)
    monkeypatch.setattr(zipfile.ZipFile, "extract", slow_extract)
    boot.ensure()
    _wait(boot)
    assert boot.status()["state"] == "error"
    assert not (env / "ghidra").exists()
    assert _leftovers(env) == []


def test_orphan_tmp_from_crash_is_cleaned(tmp_path, monkeypatch, env):
    _make_ghidra(env / "ghidra")
    (env / "ghidra.zip.tmp").write_bytes(b"meio download")
    (env / "ghidra.extract.tmp" / "lixo").mkdir(parents=True)
    _serve_zip(monkeypatch, tmp_path)
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.ensure()
    _wait(boot)
    assert _leftovers(env) == []
    assert ghidra_setup._is_ghidra(env / "ghidra")


def test_invalid_leftover_target_is_replaced(tmp_path, monkeypatch, env):
    (env / "ghidra" / "quebrado").mkdir(parents=True)   # pasta sem support/Ghidra
    _serve_zip(monkeypatch, tmp_path)
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.ensure()
    _wait(boot)
    assert ghidra_setup._is_ghidra(env / "ghidra")
    assert not (env / "ghidra" / "quebrado").exists()


def test_missing_jdk_is_reported_not_installed(tmp_path, monkeypatch, env):
    _make_ghidra(env / "ghidra")
    monkeypatch.setattr(ghidra_setup, "java_status",
                        lambda: {"ok": False, "version": "", "reason": "Java não foi encontrado no PATH."})
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.ensure()
    _wait(boot)
    status = boot.status()
    assert status["state"] == "missing_jdk" and "Java" in status["message"]
    assert status["dir"]   # o Ghidra está lá; só falta o JDK


def test_missing_jdk_skips_download(tmp_path, monkeypatch, env):
    # Sem JDK 21+ o Ghidra não roda: não vale baixar 570 MB. A próxima conexão do REA confere de novo.
    calls = _serve_zip(monkeypatch, tmp_path)
    java = {"ok": False, "version": "17", "reason": "Ghidra precisa do JDK 21+ (achei 17)."}
    monkeypatch.setattr(ghidra_setup, "java_status", lambda: java)
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.ensure()
    _wait(boot)
    assert calls == [] and boot.status()["state"] == "missing_jdk" and "JDK 21" in boot.status()["message"]
    assert not (env / "ghidra").exists()
    java.update(ok=True, version="21", reason="")   # o usuário instalou o JDK
    boot.ensure()
    _wait(boot)
    assert len(calls) == 1 and boot.status()["state"] == "installed"


def test_env_file_is_never_written(tmp_path, monkeypatch, env):
    dotenv = PROJECT_ROOT / ".env"
    before = dotenv.stat().st_mtime_ns if dotenv.exists() else None
    _serve_zip(monkeypatch, tmp_path)
    boot = ghidra_setup.GhidraBootstrap(env)
    boot.ensure()
    _wait(boot)
    assert boot.status()["state"] == "installed"
    assert (dotenv.stat().st_mtime_ns if dotenv.exists() else None) == before
    assert not hasattr(ghidra_setup, "set_env") and not hasattr(ghidra_setup, "ENV_FILE")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["src.zip", "tools"]   # nada fora da raiz


# ── Ligação com o hub: prepara antes de subir o subprocesso ─

def test_hub_runs_prepare_hooks_before_connecting(tmp_path):
    import sys

    hub = MCPHub(ToolRegistry(), config_path=tmp_path / "mcp.json")
    seen = []
    hub.prepare_hooks.append(lambda state: seen.append((state.name, state.status)))
    state = ServerState("rea", {"command": sys.executable, "args": ["-c", "pass"]})
    hub._start(state)
    assert seen == [("rea", "desligado")]       # antes de virar "conectando"
    assert state.status == "conectando"

    off = ServerState("off", {"command": sys.executable, "enabled": False})
    hub._start(off)
    assert [name for name, _ in seen] == ["rea"]   # desligado não prepara nada
