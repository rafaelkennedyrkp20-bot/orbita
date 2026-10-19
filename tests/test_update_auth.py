"""Selo HMAC da atualização: recusa antes de gravar e não toca em dados da pessoa."""

import hashlib
import zipfile
from pathlib import Path

import pytest

from agent.core import updater
from agent.core.update_auth import UpdateAuthError, load_key, sign_manifest


KEY = b"0123456789abcdef"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "orbita"
    (root / "agent").mkdir(parents=True)
    (root / "agent" / "gui.py").write_bytes(b"velho")
    (root / "data").mkdir()
    (root / "data" / "settings.json").write_text('{"meu": true}', encoding="utf-8")
    (root / ".env").write_text("CHAVE=segredo\n", encoding="utf-8")
    (root / "models").mkdir()
    (root / "models" / "peso.bin").write_bytes(b"peso")
    (root / "venv").mkdir()
    (root / "venv" / "pyvenv.cfg").write_text("home = aqui\n", encoding="utf-8")
    return root


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    archive_path = path / "pacote.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for rel, data in members.items():
            archive.writestr(f"orbita/{rel}", data)
    return archive_path


def _signed(files: dict[str, str]) -> tuple[dict, str]:
    manifest = {"files": files}
    return manifest, sign_manifest(manifest, KEY)


def _backups(root: Path) -> list[Path]:
    folder = root / "data" / "updates"
    if not folder.is_dir():
        return []
    return list(folder.glob("backup-*"))


def test_load_key_does_not_invent_one(monkeypatch, tmp_path):
    monkeypatch.delenv("ORBITA_UPDATE_KEY", raising=False)
    monkeypatch.delenv("ORBITA_UPDATE_KEY_FILE", raising=False)
    assert load_key() is None
    path = tmp_path / "chave.txt"
    path.write_bytes(KEY)
    monkeypatch.setenv("ORBITA_UPDATE_KEY_FILE", str(path))
    assert load_key() == KEY
    monkeypatch.setenv("ORBITA_UPDATE_KEY", "curta-demais")
    assert load_key() == b"curta-demais"


def test_bad_signature_and_short_key_write_nothing(tmp_path):
    root = _root(tmp_path)
    package = _zip(tmp_path, {"agent/gui.py": b"novo"})
    manifest, _signature = _signed({"agent/gui.py": _sha(b"novo")})
    with pytest.raises(UpdateAuthError, match="Assinatura"):
        updater.apply_verified(root, package, manifest, "ab" * 32, KEY)
    with pytest.raises(UpdateAuthError, match="curta"):
        updater.apply_verified(root, root / "nao-existe.zip", manifest, "ab" * 32, b"curta")
    assert (root / "agent" / "gui.py").read_bytes() == b"velho"
    assert _backups(root) == []


def test_hash_mismatch_writes_nothing_including_earlier_files(tmp_path):
    root = _root(tmp_path)
    good = b"novo-gui"
    package = _zip(tmp_path, {"agent/gui.py": good, "agent/novo.py": b"criado"})
    manifest, signature = _signed({
        "agent/gui.py": _sha(good),
        "agent/novo.py": "0" * 64,
    })
    with pytest.raises(UpdateAuthError, match="Hash não confere"):
        updater.apply_verified(root, package, manifest, signature, KEY)
    assert (root / "agent" / "gui.py").read_bytes() == b"velho"
    assert not (root / "agent" / "novo.py").exists()
    assert _backups(root) == []


def test_protected_paths_stay_even_when_the_seal_is_valid(tmp_path):
    root = _root(tmp_path)
    program = b"programa-novo"
    members = {
        "agent/gui.py": program,
        "agent/extra.py": b"fora do manifesto",
        "data/settings.json": b"roubado",
        ".env": b"CHAVE=da-rede\n",
        "models/peso.bin": b"outro",
        "venv/pyvenv.cfg": b"home = atacante\n",
    }
    package = _zip(tmp_path, members)
    manifest, signature = _signed({
        "agent/gui.py": _sha(program),
        "data/settings.json": _sha(b"roubado"),
        ".env": _sha(b"CHAVE=da-rede\n"),
        "models/peso.bin": _sha(b"outro"),
        "venv/pyvenv.cfg": _sha(b"home = atacante\n"),
    })
    result = updater.apply_verified(root, package, manifest, signature, KEY)
    assert (root / "agent" / "gui.py").read_bytes() == program
    assert not (root / "agent" / "extra.py").exists()
    assert (root / "data" / "settings.json").read_text(encoding="utf-8") == '{"meu": true}'
    assert (root / ".env").read_text(encoding="utf-8") == "CHAVE=segredo\n"
    assert (root / "models" / "peso.bin").read_bytes() == b"peso"
    assert (root / "venv" / "pyvenv.cfg").read_text(encoding="utf-8") == "home = aqui\n"
    assert result["replaced"] == ["agent/gui.py"]


def test_traversal_is_refused_before_any_write(tmp_path):
    root = _root(tmp_path)
    package = _zip(tmp_path, {"agent/gui.py": b"novo"})
    manifest, signature = _signed({"agent/gui.py": _sha(b"novo"), "../fora.txt": _sha(b"x")})
    with pytest.raises(UpdateAuthError, match="Caminho recusado"):
        updater.apply_verified(root, package, manifest, signature, KEY)
    assert (root / "agent" / "gui.py").read_bytes() == b"velho"
    assert not (tmp_path / "fora.txt").exists()
    assert _backups(root) == []


def test_interrupted_write_restores_the_previous_program(tmp_path, monkeypatch):
    root = _root(tmp_path)
    first = b"primeiro"
    second = b"segundo"
    package = _zip(tmp_path, {"agent/gui.py": first, "agent/novo.py": second})
    manifest, signature = _signed({"agent/gui.py": _sha(first), "agent/novo.py": _sha(second)})
    original = Path.write_bytes

    def fail_on_second(self, data):
        if data == second:
            raise OSError("disco cheio")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", fail_on_second)
    with pytest.raises(UpdateAuthError, match="interrompida"):
        updater.apply_verified(root, package, manifest, signature, KEY)
    assert (root / "agent" / "gui.py").read_bytes() == b"velho"
    assert not (root / "agent" / "novo.py").exists()
    assert (root / "data" / "settings.json").read_text(encoding="utf-8") == '{"meu": true}'


def test_restore_skips_a_protected_path_in_the_backup(tmp_path):
    root = _root(tmp_path)
    backup = tmp_path / "backup"
    (backup / "agent").mkdir(parents=True)
    (backup / "agent" / "gui.py").write_bytes(b"restaurado")
    (backup / "data").mkdir()
    (backup / "data" / "settings.json").write_text("roubado", encoding="utf-8")
    updater.restore_backup(root, backup, ["agent/gui.py", "data/settings.json"])
    assert (root / "agent" / "gui.py").read_bytes() == b"restaurado"
    assert (root / "data" / "settings.json").read_text(encoding="utf-8") == '{"meu": true}'


def test_frozen_app_refuses_before_any_write(tmp_path, monkeypatch):
    root = _root(tmp_path)
    monkeypatch.setattr(updater, "_download", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("baixou")))
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    with pytest.raises(RuntimeError, match="empacotado"):
        updater.apply(root)
    assert (root / "agent" / "gui.py").read_bytes() == b"velho"
    assert (root / "data" / "settings.json").read_text(encoding="utf-8") == '{"meu": true}'
    assert _backups(root) == []
