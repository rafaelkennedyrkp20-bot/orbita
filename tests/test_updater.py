"""Atualizador: verificação sem rede (GitHub simulado), ZIP que não apaga dados e git que não atropela trabalho local."""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from agent.core import updater


def _install(tmp_path):
    root = tmp_path / "orbita"
    (root / "agent").mkdir(parents=True)
    (root / "agent" / "gui.py").write_text("v1\n", encoding="utf-8")
    (root / "agent" / "velho.py").write_text("sai na v2\n", encoding="utf-8")
    (root / "README.md").write_text("# v1\n", encoding="utf-8")
    (root / "data").mkdir()
    (root / "data" / "settings.json").write_text('{"meu": "ajuste"}', encoding="utf-8")
    (root / ".env").write_text("CHAVE=segredo\n", encoding="utf-8")
    (root / "meu_script.py").write_text("criado pela pessoa\n", encoding="utf-8")
    files = {rel: updater.blob_sha((root / rel).read_bytes()) for rel in ("agent/gui.py", "agent/velho.py", "README.md")}
    (root / "data" / "updates").mkdir()
    (root / "data" / "updates" / "install.json").write_text(json.dumps({"sha": "a" * 40, "files": files}), encoding="utf-8")
    return root


def _release(tmp_path, files):
    """ZIP no formato do GitHub (pasta raiz orbita-<sha>/)."""
    path = tmp_path / "release.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for rel, text in files.items():
            archive.writestr(f"orbita-bbbb/{rel}", text)
    return path


V2 = {"agent/gui.py": "v2\n", "agent/novo.py": "novo\n", "README.md": "# v1\n",
      "data/settings.json": "{}", ".env": "CHAVE=da-internet\n", "../fora.txt": "x"}


def test_blob_sha_matches_git_and_ignores_crlf(tmp_path):
    f = tmp_path / "x.bat"
    f.write_bytes(b"@echo off\r\necho oi\r\n")
    if shutil.which("git"):
        git_sha = subprocess.run(["git", "hash-object", "--no-filters", str(f)], capture_output=True,
                                 text=True).stdout.strip()
        assert updater.blob_sha(f.read_bytes()) == git_sha
    assert updater.same_as_blob(f, updater.blob_sha(b"@echo off\necho oi\n"))


def test_apply_zip_updates_program_and_never_touches_user_data(tmp_path):
    root = _install(tmp_path)
    result = updater.apply_zip(root, _release(tmp_path, V2), "b" * 40)

    assert (root / "agent" / "gui.py").read_text(encoding="utf-8") == "v2\n"
    assert (root / "agent" / "novo.py").exists()
    assert not (root / "agent" / "velho.py").exists()                       # saiu do programa
    assert (root / "meu_script.py").exists()                                # arquivo da pessoa fica
    assert (root / "data" / "settings.json").read_text(encoding="utf-8") == '{"meu": "ajuste"}'
    assert (root / ".env").read_text(encoding="utf-8") == "CHAVE=segredo\n"
    assert not (tmp_path / "fora.txt").exists()                             # ZIP não escapa da pasta
    assert result["replaced"] == ["agent/gui.py"] and result["removed"] == ["agent/velho.py"]

    backup = updater.Path(result["backup"])                                 # cópia do que mudou
    assert (backup / "agent" / "gui.py").read_text(encoding="utf-8") == "v1\n"
    assert (backup / "agent" / "velho.py").exists()
    installed = updater.manifest(root)
    assert installed["sha"] == "b" * 40 and "agent/novo.py" in installed["files"]
    assert not any(updater.is_protected(rel) for rel in installed["files"])


def _fake_github(monkeypatch, tree, compare_status="ahead", titles=("Corrige travamento ao parar",)):
    def fake(url, timeout=12):
        if url.endswith(f"/commits/{updater.BRANCH}"):
            return {"sha": "b" * 40, "commit": {"committer": {"date": "2026-10-17"}}}
        if "/compare/" in url:
            return {"status": compare_status, "html_url": "https://github.com/x/compare",
                    "commits": [{"commit": {"message": t + "\n\ncorpo"}} for t in titles], "files": []}
        if "/git/trees/" in url:
            return {"tree": [{"path": p, "type": "blob", "sha": updater.blob_sha(c.encode())} for p, c in tree.items()]}
        raise AssertionError(url)
    monkeypatch.setattr(updater, "_http_json", fake)
    monkeypatch.setattr(updater, "_remote_version", lambda sha: "0.2.0-alpha")
    monkeypatch.setattr(updater, "install_mode", lambda root=None: "zip")


def test_check_zip_lists_exactly_what_changes(tmp_path, monkeypatch):
    root = _install(tmp_path)
    _fake_github(monkeypatch, {"agent/gui.py": "v2\n", "agent/novo.py": "n", "README.md": "# v1\n",
                               "data/x.json": "{}"},
                 titles=("Corrige travamento ao parar", "Interface: novo botão", "Cache do catálogo deixa abrir mais rápido"))
    info = updater.check(root)
    assert info["available"] and info["significant"] and not info["blocked"]
    assert info["files"] == {"changed": ["agent/gui.py"], "added": ["agent/novo.py"], "removed": ["agent/velho.py"]}
    assert set(info["groups"]) == {"Correções", "Interface", "Desempenho"}
    assert info["remote_version"] == "0.2.0-alpha"


def test_docs_only_update_is_not_significant(tmp_path, monkeypatch):
    root = _install(tmp_path)
    tree = {"agent/gui.py": "v1\n", "agent/velho.py": "sai na v2\n", "README.md": "# v2 com mais texto\n"}
    _fake_github(monkeypatch, tree, titles=("Atualiza README",))
    info = updater.check(root)
    assert info["available"] and not info["significant"]


def test_local_copy_newer_than_github_means_no_update(tmp_path, monkeypatch):
    root = _install(tmp_path)
    _fake_github(monkeypatch, {}, compare_status="behind")
    assert updater.check(root)["available"] is False


@pytest.mark.skipif(not shutil.which("git"), reason="git não instalado")
def test_git_install_refuses_with_local_changes(tmp_path):
    root = tmp_path / "clone"
    root.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("remote", "add", "origin", f"https://github.com/{updater.REPO}.git")
    (root / "app.py").write_text("v1\n", encoding="utf-8")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "v1")
    assert updater.install_mode(root) == "git"
    (root / "app.py").write_text("mexi\n", encoding="utf-8")
    assert updater.local_changes(root) == ["app.py"]
    with pytest.raises(RuntimeError, match="não salvas"):
        updater.apply_git(root)
    assert (root / "app.py").read_text(encoding="utf-8") == "mexi\n"


def _clone_with_remote(tmp_path):
    """Clone 'antigo' de um remoto local cujo caminho contém o nome do repositório (o modo git o reconhece)."""
    run = lambda cwd, *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd,  # noqa: E731
                                         check=True, capture_output=True)
    origin = tmp_path / "rafaelkennedyrkp20-bot" / "orbita"
    (origin / "agent" / "ui" / "web").mkdir(parents=True)
    (origin / "agent" / "ui" / "web" / "app.ico").write_bytes(b"ICO-original")
    (origin / "app.py").write_text("v1\n", encoding="utf-8")
    (origin / "iniciar.sh").write_text("python3.12 launcher.py\n", encoding="utf-8")
    run(origin, "init", "-q", "-b", "main")
    run(origin, "add", ".")
    run(origin, "commit", "-qm", "v1")
    clone = tmp_path / "clone"
    run(tmp_path, "clone", "-q", origin.as_posix(), str(clone))
    (origin / "app.py").write_text("v2\n", encoding="utf-8")
    run(origin, "commit", "-qam", "v2")
    return clone


@pytest.mark.skipif(not shutil.which("git"), reason="git não instalado")
def test_regenerated_icon_does_not_block_the_update(tmp_path):
    """Caso real no Linux: o programa regravava o app.ico ao abrir e o git acusava 'alteração local'."""
    clone = _clone_with_remote(tmp_path)
    assert updater.install_mode(clone) == "git"
    (clone / "agent" / "ui" / "web" / "app.ico").write_bytes(b"ICO-regravado-no-linux")
    assert updater.local_changes(clone) == []                      # não é trabalho da pessoa
    result = updater.apply_git(clone)
    assert (clone / "app.py").read_text(encoding="utf-8") == "v2\n" and "app.py" in result["replaced"]
    assert (clone / "agent" / "ui" / "web" / "app.ico").read_bytes() == b"ICO-original"


@pytest.mark.skipif(not shutil.which("git"), reason="git não instalado")
def test_update_keeping_local_changes(tmp_path):
    """Caso real: o usuário do Linux editou o iniciar.sh (Python 3.13) e o atualizador só recusava."""
    clone = _clone_with_remote(tmp_path)
    (clone / "iniciar.sh").write_text("python3.13 launcher.py\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="não salvas"):
        updater.apply_git(clone)                                   # sem pedir, continua não mexendo em nada
    result = updater.apply_git(clone, keep_local=True)
    assert (clone / "app.py").read_text(encoding="utf-8") == "v2\n"          # atualizou
    assert (clone / "iniciar.sh").read_text(encoding="utf-8") == "python3.13 launcher.py\n"   # e manteve a edição
    assert result["kept_local"] == ["iniciar.sh"] and result["conflicts"] == []
    assert (Path(result["backup"]) / "iniciar.sh").read_text(encoding="utf-8") == "python3.13 launcher.py\n"


@pytest.mark.skipif(not shutil.which("git"), reason="git não instalado")
def test_conflicting_local_change_keeps_new_version_and_backup(tmp_path):
    clone = _clone_with_remote(tmp_path)
    (clone / "app.py").write_text("minha versão\n", encoding="utf-8")   # o upstream também mudou app.py
    result = updater.apply_git(clone, keep_local=True)
    assert (clone / "app.py").read_text(encoding="utf-8") == "v2\n" and result["conflicts"] == ["app.py"]
    assert (Path(result["backup"]) / "app.py").read_text(encoding="utf-8") == "minha versão\n"
    assert updater.local_changes(clone) == []                                # repositório limpo, sem marcas de conflito


def test_folder_without_write_permission_is_explained_before_touching_anything(tmp_path, monkeypatch):
    root = _install(tmp_path)
    real_access = updater.os.access
    monkeypatch.setattr(updater.os, "access", lambda p, mode: False if Path(p) == root else real_access(p, mode))
    problem = updater.write_problem(root, "zip")
    assert "Sem permissão para gravar" in problem
    if updater.os.name != "nt":
        assert "sudo chown -R" in problem
    with pytest.raises(RuntimeError, match="Sem permissão"):
        updater.apply(root, sha="b" * 40)
    assert (root / "agent" / "gui.py").read_text(encoding="utf-8") == "v1\n"   # nada mudou


def test_commit_groups():
    groups = updater.group_commits(["Merge branch x", "Corrige bug no diff", "Checkpoints por resposta",
                                    "Tela de memórias"])
    assert groups == {"Correções": ["Corrige bug no diff"], "Novidades": ["Checkpoints por resposta"],
                      "Interface": ["Tela de memórias"]}
