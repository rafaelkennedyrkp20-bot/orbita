"""
updater.py — Avisa quando há atualização no GitHub e atualiza o Órbita com um clique.

O GitHub é a âncora: não há servidor próprio. Duas formas de instalação:

* **git** (cópia feita com `git clone`): atualiza com `git pull --ff-only`. Se a pessoa tiver
  alterações locais não salvas ou commits que não estão no GitHub, recusa e explica — nunca
  sobrescreve trabalho de ninguém.
* **zip** (código baixado do GitHub): baixa o ZIP do commit novo e substitui só os arquivos do
  programa. Antes, copia para `data/updates/backup-<data>/` tudo que vai ser substituído ou
  removido. Um arquivo só é removido se veio de uma versão anterior do programa (manifesto em
  `data/updates/install.json`); arquivo criado pela pessoa nunca é apagado.

Nunca tocados: `data/` (conversas, configurações, perfis), `.env` (chaves), memória,
`models/`, `venv/`. Só biblioteca padrão: este módulo também roda sozinho, com o programa
fechado (`python -m agent.core.updater apply --pid N`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
REPO = "rafaelkennedyrkp20-bot/orbita"
BRANCH = "main"
API = f"https://api.github.com/repos/{REPO}"
CHECK_EVERY = 6 * 3600

# Dados da pessoa: nunca escritos, substituídos nem apagados por uma atualização.
PROTECTED = ("data/", ".env", "venv/", ".venv/", "env/", "models/", ".git/", "temp/",
             "agent/memory/daily_logs/", "agent/memory/long_term/")
DOCS = re.compile(r"(^docs/|\.md$|^LICENSE$|^\.gitignore$|^\.gitattributes$|\.png$|\.jpe?g$)", re.I)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GROUPS = [
    ("Correções", re.compile(r"corrig|conserta|fix|bug|erro|falha|trava", re.I)),
    ("Desempenho", re.compile(r"velocidade|rápid|desempenho|perf|cache|lent|memória ram|startup", re.I)),
    ("Interface", re.compile(r"interface|tela|janela|ícone|botão|visual|tema|ui\b", re.I)),
]


def updates_dir(root: Path = ROOT) -> Path:
    return root / "data" / "updates"


def is_protected(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in PROTECTED)


# ── Rede ───────────────────────────────────────────────────────

def _http_json(url: str, timeout: float = 12):
    request = urllib.request.Request(url, headers={"User-Agent": "Orbita-Updater",
                                                   "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Orbita-Updater"})
    with urllib.request.urlopen(request, timeout=120) as response, open(dest, "wb") as out:
        shutil.copyfileobj(response, out)


# ── Estado local ───────────────────────────────────────────────

def blob_sha(data: bytes) -> str:
    """Mesmo hash que o git dá a um arquivo (permite comparar sem ter o git instalado)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def same_as_blob(path: Path, sha: str) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return blob_sha(data) == sha or (b"\r\n" in data and blob_sha(data.replace(b"\r\n", b"\n")) == sha)


def _git(root: Path, *args: str, check: bool = True) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(["git", *args], cwd=str(root), capture_output=True, env=env, timeout=120,
                            creationflags=_NO_WINDOW)
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} falhou")
    return result.stdout.decode("utf-8", "replace")


def install_mode(root: Path = ROOT) -> str:
    if (root / ".git").exists() and shutil.which("git"):
        try:
            if REPO.lower() in _git(root, "remote", "get-url", "origin").lower():
                return "git"
        except Exception:
            pass
    return "zip"


def manifest(root: Path = ROOT) -> dict:
    try:
        return json.loads((updates_dir(root) / "install.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def local_sha(root: Path = ROOT, mode: Optional[str] = None) -> Optional[str]:
    if (mode or install_mode(root)) == "git":
        try:
            return _git(root, "rev-parse", "HEAD").strip()
        except Exception:
            return None
    return manifest(root).get("sha")


def local_changes(root: Path) -> list[str]:
    """Arquivos rastreados com alteração não salva (só no modo git)."""
    out = _git(root, "status", "--porcelain", "--untracked-files=no", check=False)
    return [line[3:].strip() for line in out.splitlines() if line.strip()]


# ── Verificação ────────────────────────────────────────────────

def group_commits(titles: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for title in titles:
        if title.lower().startswith("merge "):
            continue
        name = next((g for g, rx in GROUPS if rx.search(title)), "Novidades")
        groups.setdefault(name, []).append(title)
    return groups


def _remote_version(sha: str) -> str:
    try:
        request = urllib.request.Request(f"https://raw.githubusercontent.com/{REPO}/{sha}/agent/__init__.py",
                                         headers={"User-Agent": "Orbita-Updater"})
        with urllib.request.urlopen(request, timeout=8) as response:
            text = response.read().decode("utf-8", "replace")
        match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
        return match.group(1) if match else ""
    except Exception:
        return ""


def _zip_plan(root: Path, remote_sha: str) -> dict:
    tree = _http_json(f"{API}/git/trees/{remote_sha}?recursive=1")
    blobs = {item["path"]: item["sha"] for item in tree.get("tree", []) if item.get("type") == "blob"}
    changed, added = [], []
    for rel, sha in sorted(blobs.items()):
        if is_protected(rel):
            continue
        target = root / rel
        if not target.exists():
            added.append(rel)
        elif not same_as_blob(target, sha):
            changed.append(rel)
    old = manifest(root).get("files") or {}
    removed = sorted(rel for rel in old if rel not in blobs and not is_protected(rel) and (root / rel).is_file())
    return {"changed": changed, "added": added, "removed": removed}


def check(root: Path = ROOT) -> dict:
    """Consulta o GitHub. Nunca altera nada."""
    mode = install_mode(root)
    head = _http_json(f"{API}/commits/{BRANCH}")
    remote = head["sha"]
    local = local_sha(root, mode)
    info = {"mode": mode, "local": local, "remote": remote, "available": False, "significant": False,
            "blocked": "", "groups": {}, "files": {"changed": [], "added": [], "removed": []},
            "remote_date": (head.get("commit", {}).get("committer") or {}).get("date", ""),
            "url": f"https://github.com/{REPO}/commits/{BRANCH}", "checked_at": time.time()}
    if local == remote:
        return info

    titles: list[str] = []
    if local:
        try:
            compare = _http_json(f"{API}/compare/{local}...{remote}")
        except Exception:
            compare = None   # commit local que não existe no GitHub
        if compare is not None:
            if compare.get("status") in ("identical", "behind"):
                return info   # a cópia local está igual ou à frente
            titles = [c["commit"]["message"].split("\n", 1)[0] for c in compare.get("commits", [])]
            info["url"] = compare.get("html_url") or info["url"]
            if mode == "git":
                for f in compare.get("files", []):
                    key = {"added": "added", "removed": "removed"}.get(f.get("status"), "changed")
                    info["files"][key].append(f["filename"])
            if compare.get("status") == "diverged":
                info["blocked"] = ("Sua cópia tem commits que não estão no GitHub. Atualize pelo git "
                                   "(git pull) para não perder esse trabalho.")
        elif mode == "git":
            return info   # commits locais à frente do GitHub: quem desenvolve atualiza na mão
    if not titles:
        commits = _http_json(f"{API}/commits?sha={remote}&per_page=10")
        titles = [c["commit"]["message"].split("\n", 1)[0] for c in commits]

    if mode == "zip":
        info["files"] = _zip_plan(root, remote)
    else:
        dirty = local_changes(root)
        if dirty and not info["blocked"]:
            shown = ", ".join(dirty[:6]) + ("…" if len(dirty) > 6 else "")
            info["blocked"] = (f"Há alterações locais não salvas em {len(dirty)} arquivo(s) ({shown}). "
                               "Salve (commit) ou descarte e tente de novo.")

    files = info["files"]
    touched = files["changed"] + files["added"] + files["removed"]
    info["available"] = bool(touched) or (mode == "git" and bool(titles))
    info["significant"] = any(not DOCS.search(p) for p in touched) if touched else bool(titles)
    info["groups"] = group_commits(titles)
    info["count"] = len(titles)
    info["remote_version"] = _remote_version(remote)
    return info


def check_cached(root: Path = ROOT, force: bool = False) -> dict:
    cache = updates_dir(root) / "last_check.json"
    if not force:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if time.time() - data.get("checked_at", 0) < CHECK_EVERY and data.get("local") == local_sha(root):
                return data
        except (OSError, ValueError):
            pass
    info = check(root)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


# ── Aplicação ──────────────────────────────────────────────────

def _backup(root: Path, backup: Path, rel: str) -> None:
    source = root / rel
    if source.is_file():
        target = backup / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _safe_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Caminho relativo → item do ZIP, sem a pasta raiz do GitHub e sem nada que saia da pasta."""
    members = {}
    for item in archive.infolist():
        if item.is_dir():
            continue
        parts = item.filename.replace("\\", "/").split("/", 1)
        if len(parts) < 2 or not parts[1]:
            continue
        rel = parts[1]
        if rel.startswith("/") or ".." in rel.split("/") or ":" in rel:
            continue
        members[rel] = item
    return members


def apply_zip(root: Path, zip_path: Path, sha: str) -> dict:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = updates_dir(root) / f"backup-{stamp}"
    replaced, added, removed = [], [], []
    with zipfile.ZipFile(zip_path) as archive:
        members = _safe_members(archive)
        for rel, item in sorted(members.items()):
            if is_protected(rel):
                continue
            data = archive.read(item)
            target = root / rel
            if target.is_file():
                current = target.read_bytes()
                if current == data or current.replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n"):
                    continue   # igual (só a quebra de linha muda): não mexe
                _backup(root, backup, rel)
                replaced.append(rel)
            else:
                added.append(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    old = manifest(root).get("files") or {}
    for rel in sorted(old):
        if rel not in members and not is_protected(rel) and (root / rel).is_file():
            _backup(root, backup, rel)
            (root / rel).unlink()
            removed.append(rel)
    files = {rel: blob_sha((root / rel).read_bytes()) for rel in members if not is_protected(rel) and (root / rel).is_file()}
    updates_dir(root).mkdir(parents=True, exist_ok=True)
    (updates_dir(root) / "install.json").write_text(json.dumps(
        {"sha": sha, "updated_at": datetime.now().isoformat(timespec="seconds"), "files": files},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return {"replaced": replaced, "added": added, "removed": removed,
            "backup": str(backup) if (replaced or removed) else ""}


def apply_git(root: Path) -> dict:
    dirty = local_changes(root)
    if dirty:
        raise RuntimeError(f"Alterações locais não salvas em {len(dirty)} arquivo(s); nada foi alterado.")
    before = _git(root, "rev-parse", "HEAD").strip()
    _git(root, "fetch", "--quiet", "origin", BRANCH)
    try:
        _git(root, "merge", "--ff-only", f"origin/{BRANCH}")
    except RuntimeError as error:
        raise RuntimeError("Sua cópia tem commits que não estão no GitHub; atualize com git pull. "
                           f"Nada foi alterado. ({error})")
    changed = _git(root, "diff", "--name-only", before, "HEAD").split()
    return {"replaced": changed, "added": [], "removed": [], "backup": ""}


def apply(root: Path = ROOT, sha: Optional[str] = None) -> dict:
    mode = install_mode(root)
    if mode == "git":
        return apply_git(root)
    sha = sha or _http_json(f"{API}/commits/{BRANCH}")["sha"]
    work = updates_dir(root)
    work.mkdir(parents=True, exist_ok=True)
    zip_path = work / f"orbita-{sha[:12]}.zip"
    _download(f"https://codeload.github.com/{REPO}/zip/{sha}", zip_path)
    try:
        return apply_zip(root, zip_path, sha)
    finally:
        zip_path.unlink(missing_ok=True)


# ── Processo separado (programa fechado) ───────────────────────

def _wait_pid(pid: int, timeout: float = 60) -> None:
    if os.name == "nt":
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)   # SYNCHRONIZE
        if handle:
            ctypes.windll.kernel32.WaitForSingleObject(handle, int(timeout * 1000))
            ctypes.windll.kernel32.CloseHandle(handle)
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.3)


def relaunch(root: Path = ROOT) -> None:
    python = root / "venv" / "Scripts" / ("pythonw.exe" if os.name == "nt" else "python")
    if not python.is_file():
        python = Path(sys.executable)
    subprocess.Popen([str(python), str(root / "launcher.py"), "--no-console"], cwd=str(root),
                     creationflags=_NO_WINDOW)


def start_detached(sha: str, root: Path = ROOT) -> None:
    """Chamado pela janela antes de fechar: o atualizador espera o programa sair e trabalha sozinho."""
    python = Path(sys.executable)
    windowed = python.with_name("pythonw.exe")
    subprocess.Popen([str(windowed if windowed.is_file() else python), "-m", "agent.core.updater", "apply",
                      "--pid", str(os.getpid()), "--sha", sha, "--restart"], cwd=str(root),
                     creationflags=_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0))


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Atualizador do Órbita")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    run = sub.add_parser("apply")
    run.add_argument("--pid", type=int, default=0)
    run.add_argument("--sha", default=None)
    run.add_argument("--restart", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "check":
        print(json.dumps(check(), ensure_ascii=False, indent=1))
        return 0
    if args.pid:
        _wait_pid(args.pid)
    result_file = updates_dir() / "result.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = {"ok": True, **apply(sha=args.sha)}
    except Exception as error:
        result = {"ok": False, "error": str(error)}
    result["at"] = datetime.now().isoformat(timespec="seconds")
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.restart:
        relaunch()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
