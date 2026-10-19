"""Auditoria do atualizador: ZIP aplicado como transação (#15) e caminhos protegidos sem distinção de caixa (#17)."""

import json
import zipfile
from pathlib import Path

import pytest

from agent.core import updater


def _install(tmp_path: Path) -> Path:
    """Instalação temporária com manifesto de uma versão anterior."""
    root = tmp_path / "orbita"
    (root / "agent").mkdir(parents=True)
    (root / "a.py").write_text("v1", encoding="utf-8")
    (root / "b").write_text("arquivo comum", encoding="utf-8")
    (root / "agent" / "velho.py").write_text("sai na v2", encoding="utf-8")
    (root / ".env").write_text("KEY=keep", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "settings.json").write_text("KEEP", encoding="utf-8")
    files = {rel: updater.blob_sha((root / rel).read_bytes()) for rel in ("a.py", "agent/velho.py")}
    (root / "data" / "updates").mkdir()
    (root / "data" / "updates" / "install.json").write_text(json.dumps({"sha": "a" * 40, "files": files}),
                                                            encoding="utf-8")
    return root


def _release(tmp_path: Path, files: dict[str, str]) -> Path:
    path = tmp_path / "release.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for rel, text in files.items():
            archive.writestr(f"release/{rel}", text)
    return path


def _snapshot(root: Path) -> dict[str, bytes]:
    """Todos os arquivos fora dos backups (o backup pode ficar: é cópia, não estado do programa)."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and "backup-" not in p.as_posix()}


def _dirs(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_dir() and "backup-" not in p.as_posix()}


# ── #15: atualização pela metade ───────────────────────────────

def test_file_where_release_needs_a_folder_changes_nothing(tmp_path):
    root = _install(tmp_path)
    before, dirs = _snapshot(root), _dirs(root)
    package = _release(tmp_path, {"a.py": "v2", "b/main.py": "v2", "c/novo.py": "novo"})

    with pytest.raises(RuntimeError, match="Nada foi alterado"):
        updater.apply_zip(root, package, "b" * 40)

    assert _snapshot(root) == before            # a.py continua v1, b continua arquivo, manifesto intacto
    assert _dirs(root) == dirs                  # nenhuma pasta nova ficou para trás
    assert updater.manifest(root)["sha"] == "a" * 40


def test_folder_where_release_needs_a_file_changes_nothing(tmp_path):
    root = _install(tmp_path)
    (root / "pasta").mkdir()
    (root / "pasta" / "meu.txt").write_text("da pessoa", encoding="utf-8")
    before = _snapshot(root)

    with pytest.raises(RuntimeError, match="Nada foi alterado"):
        updater.apply_zip(root, _release(tmp_path, {"a.py": "v2", "pasta": "agora sou arquivo"}), "b" * 40)
    assert _snapshot(root) == before


def test_write_error_on_second_file_rolls_everything_back(tmp_path, monkeypatch):
    root = _install(tmp_path)
    before, dirs = _snapshot(root), _dirs(root)
    package = _release(tmp_path, {"a.py": "v2", "novo/x.py": "novo", "z.py": "falha"})
    original = Path.write_bytes

    def fail_on_z(self, data):
        if self.name == "z.py":
            raise OSError("disco cheio")
        return original(self, data)

    monkeypatch.setattr(Path, "write_bytes", fail_on_z)
    with pytest.raises(RuntimeError, match="interrompida"):
        updater.apply_zip(root, package, "b" * 40)

    assert (root / "a.py").read_text(encoding="utf-8") == "v1"
    assert not (root / "novo").exists()          # arquivo e pasta novos saem
    assert _snapshot(root) == before and _dirs(root) == dirs
    assert updater.manifest(root)["sha"] == "a" * 40


def test_failure_after_removals_brings_removed_files_back(tmp_path, monkeypatch):
    root = _install(tmp_path)
    before = _snapshot(root)
    package = _release(tmp_path, {"a.py": "v2", "agent/novo.py": "novo"})   # agent/velho.py sai na v2
    original = Path.write_text

    def fail_manifest(self, *args, **kwargs):
        if "install" in self.name:
            raise OSError("disco cheio")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_manifest)
    with pytest.raises(RuntimeError, match="interrompida"):
        updater.apply_zip(root, package, "b" * 40)

    assert (root / "agent" / "velho.py").read_text(encoding="utf-8") == "sai na v2"
    assert not (root / "agent" / "novo.py").exists()
    assert _snapshot(root) == before


def test_successful_zip_still_updates_and_records_manifest(tmp_path):
    root = _install(tmp_path)
    result = updater.apply_zip(root, _release(tmp_path, {"a.py": "v2", "c/novo.py": "novo"}), "b" * 40)
    assert (root / "a.py").read_text(encoding="utf-8") == "v2"
    assert result["replaced"] == ["a.py"] and result["added"] == ["c/novo.py"]
    assert result["removed"] == ["agent/velho.py"]
    assert updater.manifest(root)["sha"] == "b" * 40
    assert (Path(result["backup"]) / "a.py").read_text(encoding="utf-8") == "v1"


# ── #17: caminho protegido com outra caixa ─────────────────────

def _user_data(root: Path) -> dict[str, bytes]:
    (root / "models").mkdir(exist_ok=True)
    (root / "models" / "peso.bin").write_bytes(b"peso")
    (root / "venv").mkdir(exist_ok=True)
    (root / "venv" / "pyvenv.cfg").write_bytes(b"home = aqui")
    names = (".env", "data/settings.json", "models/peso.bin", "venv/pyvenv.cfg")
    return {rel: (root / rel).read_bytes() for rel in names}


CASE_VARIANTS = {".ENV": "KEY=replaced", "Data/settings.json": "REPLACED", "MODELS/peso.bin": "trocado",
                 "Venv/pyvenv.cfg": "trocado", "DATA/updates/install.json": '{"sha": "falso"}',
                 "data/Updates/backup-1/a.py": "trocado", ".env ": "KEY=espaco", "Data./settings.json": "PONTO"}


def test_case_variants_never_reach_user_data_in_apply_zip(tmp_path):
    root = _install(tmp_path)
    keep = _user_data(root)
    old = updater.manifest(root)
    old["files"]["MODELS/peso.bin"] = "0" * 40      # manifesto antigo citando dado da pessoa com outra caixa
    (root / "data" / "updates" / "install.json").write_text(json.dumps(old), encoding="utf-8")

    result = updater.apply_zip(root, _release(tmp_path, {"a.py": "v2", **CASE_VARIANTS}), "b" * 40)

    assert {rel: (root / rel).read_bytes() for rel in keep} == keep
    assert (root / "a.py").read_text(encoding="utf-8") == "v2"
    assert updater.manifest(root)["sha"] == "b" * 40
    touched = result["replaced"] + result["added"] + result["removed"]
    assert not any(updater.is_protected(rel) for rel in touched + list(updater.manifest(root)["files"]))


def test_case_variants_never_reach_user_data_in_apply_verified(tmp_path):
    import hashlib
    from agent.core.update_auth import sign_manifest

    root = _install(tmp_path)
    keep = _user_data(root)
    key = b"0123456789abcdef"
    members = {"a.py": b"v2", **{rel: text.encode() for rel, text in CASE_VARIANTS.items()}}
    path = tmp_path / "pacote.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for rel, data in members.items():
            archive.writestr(f"orbita/{rel}", data)
    manifest = {"files": {rel: hashlib.sha256(data).hexdigest() for rel, data in members.items()}}

    updater.apply_verified(root, path, manifest, sign_manifest(manifest, key), key)

    assert {rel: (root / rel).read_bytes() for rel in keep} == keep
    assert (root / "a.py").read_bytes() == b"v2"


def test_restore_never_writes_case_variants_over_user_data(tmp_path):
    root = _install(tmp_path)
    keep = _user_data(root)
    backup = tmp_path / "backup"
    for rel, text in CASE_VARIANTS.items():
        (backup / rel).parent.mkdir(parents=True, exist_ok=True)
        (backup / rel).write_text(text, encoding="utf-8")
    (backup / "a.py").write_text("restaurado", encoding="utf-8")

    updater.restore_backup(root, backup, ["a.py", *CASE_VARIANTS])

    assert {rel: (root / rel).read_bytes() for rel in keep} == keep
    assert (root / "a.py").read_text(encoding="utf-8") == "restaurado"


def test_effective_destination_through_a_link_is_protected(tmp_path):
    root = _install(tmp_path)
    try:
        (root / "agent" / "atalho").symlink_to(root / "data", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("sem permissão para criar link simbólico")
    keep = (root / "data" / "settings.json").read_bytes()
    updater.apply_zip(root, _release(tmp_path, {"a.py": "v2", "agent/atalho/settings.json": "REPLACED"}), "b" * 40)
    assert (root / "data" / "settings.json").read_bytes() == keep


def test_case_rule_follows_the_filesystem(monkeypatch):
    monkeypatch.setattr(updater, "_CASELESS", True)
    monkeypatch.setattr(updater, "_WINDOWS", True)
    assert updater.is_protected("Data/settings.json") and updater.is_protected(".ENV")
    assert updater.is_protected("VENV/x") and updater.is_protected("data./x") and updater.is_protected(".env ")
    assert updater.is_protected("./data/x") and not updater.is_protected("agent/data.py")
    monkeypatch.setattr(updater, "_CASELESS", False)
    monkeypatch.setattr(updater, "_WINDOWS", False)
    assert updater.is_protected("data/settings.json") and updater.is_protected(".env")
    assert not updater.is_protected("Data/settings.json") and not updater.is_protected(".ENV")


@pytest.mark.skipif(not updater._CASELESS, reason="só onde a caixa não distingue arquivos")
def test_same_name_twice_with_other_case_changes_nothing(tmp_path):
    root = _install(tmp_path)
    before = _snapshot(root)
    with pytest.raises(RuntimeError, match="Nada foi alterado"):
        updater.apply_zip(root, _release(tmp_path, {"a.py": "v2", "X.py": "um", "x.py": "outro"}), "b" * 40)
    assert _snapshot(root) == before
