"""Baixar/instalar o Ghidra de dentro do Órbita (motor nativo do REA)."""

import hashlib
import os
import zipfile
from pathlib import Path

from agent.core import ghidra_setup, toolbox


def _fake_ghidra_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("ghidra_12.1.4_PUBLIC/support/analyzeHeadless.bat", "echo headless")
        zf.writestr("ghidra_12.1.4_PUBLIC/Ghidra/application.properties", "x")
        zf.writestr("ghidra_12.1.4_PUBLIC/ghidraRun.bat", "echo run")


def test_is_ghidra_and_installed_dir(tmp_path, monkeypatch):
    good = tmp_path / "g"
    (good / "support").mkdir(parents=True)
    (good / "Ghidra").mkdir()
    bad = tmp_path / "b"
    bad.mkdir()
    assert ghidra_setup._is_ghidra(good)
    assert not ghidra_setup._is_ghidra(bad)

    monkeypatch.setattr(ghidra_setup, "INSTALL_ROOT", tmp_path / "sem-nada")
    monkeypatch.setenv("GHIDRA_INSTALL_DIR", str(good))
    assert ghidra_setup.installed_dir() == good
    monkeypatch.setenv("GHIDRA_INSTALL_DIR", str(bad))
    assert ghidra_setup.installed_dir() is None


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


def test_set_env_uncomments_and_updates(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("API_KEY=secreto\n# GHIDRA_INSTALL_DIR=C:\\velho\n", encoding="utf-8")
    monkeypatch.setattr(ghidra_setup, "ENV_FILE", env)
    monkeypatch.setenv("GHIDRA_INSTALL_DIR", "pendente")   # monkeypatch restaura no fim

    ghidra_setup.set_env(tmp_path / "ghidra_novo")
    text = env.read_text(encoding="utf-8")
    assert "API_KEY=secreto" in text
    assert "# GHIDRA_INSTALL_DIR" not in text
    assert text.count("GHIDRA_INSTALL_DIR=") == 1
    assert os.environ["GHIDRA_INSTALL_DIR"].endswith("ghidra_novo")


def test_install_downloads_verifies_extracts_sets_env(tmp_path, monkeypatch):
    src = tmp_path / "src.zip"
    _fake_ghidra_zip(src)
    data = src.read_bytes()

    monkeypatch.setattr(ghidra_setup, "INSTALL_ROOT", tmp_path / "install")
    monkeypatch.setattr(ghidra_setup, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setitem(ghidra_setup.GHIDRA, "sha256", hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(ghidra_setup.GHIDRA, "size", len(data))
    monkeypatch.setenv("GHIDRA_INSTALL_DIR", "pendente")

    def fake_download(url, target, on_bytes, cancel=None, limit=0):
        target.write_bytes(data)
        on_bytes(len(data))
    monkeypatch.setattr(toolbox, "download", fake_download)

    events = []
    target = ghidra_setup.install(on_progress=events.append)
    assert target.name == "ghidra_12.1.4_PUBLIC"
    assert (target / "support").is_dir() and (target / "Ghidra").is_dir()
    assert os.environ["GHIDRA_INSTALL_DIR"] == str(target)
    assert [e["state"] for e in events][-1] == "done"
    assert not (ghidra_setup.INSTALL_ROOT / (ghidra_setup.GHIDRA["zip_name"] + ".part")).exists()


def test_install_rejects_bad_sha256(tmp_path, monkeypatch):
    src = tmp_path / "src.zip"
    _fake_ghidra_zip(src)
    data = src.read_bytes()

    monkeypatch.setattr(ghidra_setup, "INSTALL_ROOT", tmp_path / "install")
    monkeypatch.setattr(ghidra_setup, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setitem(ghidra_setup.GHIDRA, "sha256", "0" * 64)   # errado de propósito
    monkeypatch.setitem(ghidra_setup.GHIDRA, "size", len(data))

    monkeypatch.setattr(toolbox, "download", lambda url, target, on_bytes, cancel=None, limit=0:
                        (target.write_bytes(data), on_bytes(len(data))))

    try:
        ghidra_setup.install()
        assert False, "deveria ter recusado o SHA-256"
    except ValueError as error:
        assert "SHA-256" in str(error)
    assert not (ghidra_setup.INSTALL_ROOT / ghidra_setup.GHIDRA["dir_name"]).is_dir()   # nada instalado
