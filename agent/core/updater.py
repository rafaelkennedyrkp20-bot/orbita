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

O botão do GitHub continua nesse caminho público, sem selo. `apply_verified` é outra
rota: HMAC-SHA256 com chave que não mora no repositório. Selo ruim não grava nada.
Um aplicativo já empacotado não se atualiza por cima dos próprios arquivos.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
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


# No Windows (e no macOS de fábrica) `.ENV` e `Data/` são o mesmo arquivo e a mesma pasta que `.env` e
# `data/`; no Windows ainda somem ponto e espaço no fim de cada nome (`data./` é `data/`).
_WINDOWS = os.name == "nt"
_CASELESS = _WINDOWS or sys.platform == "darwin"


def _path_key(rel: str) -> str:
    """Como o sistema de arquivos enxerga o caminho relativo: é isso que se compara com PROTECTED."""
    parts = [p for p in str(rel).replace("\\", "/").split("/") if p not in ("", ".")]
    if _WINDOWS:
        parts = [p.rstrip(" .") or p for p in parts]
    key = "/".join(parts) + ("/" if str(rel).endswith(("/", "\\")) else "")
    return key.casefold() if _CASELESS else key


def is_protected(rel: str) -> bool:
    rel = _path_key(rel)
    return any(rel == _path_key(p).rstrip("/") or rel.startswith(_path_key(p)) for p in PROTECTED)


def _blocked(root: Path, rel: str) -> bool:
    """Protegido pelo nome ou pelo destino real (link, junção, nome curto), ou fora da pasta do programa."""
    if is_protected(rel):
        return True
    try:
        real = (root / rel).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError, RuntimeError):
        return True
    return is_protected(real)


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
    # core.fileMode=false: no Linux, um `chmod +x` no iniciar_orbita.sh não conta como "alteração local".
    result = subprocess.run(["git", "-c", "core.fileMode=false", *args], cwd=str(root), capture_output=True,
                            env=env, timeout=120, creationflags=_NO_WINDOW)
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


# Arquivos versionados que o próprio programa pode regravar (versões antigas regravavam o ícone ao abrir).
# Não são trabalho da pessoa: voltam ao original antes de atualizar.
GENERATED = ("agent/ui/web/app.ico",)


def _status(root: Path) -> list[str]:
    out = _git(root, "status", "--porcelain", "--untracked-files=no", check=False)
    return [line[3:].strip().strip('"') for line in out.splitlines() if line.strip()]


def local_changes(root: Path) -> list[str]:
    """Arquivos rastreados alterados pela pessoa (só no modo git; ignora os que o programa gera)."""
    return [p for p in _status(root) if p not in GENERATED]


def write_problem(root: Path = ROOT, mode: Optional[str] = None) -> str:
    """Por que a atualização não conseguiria gravar na pasta do programa ('' se consegue)."""
    mode = mode or install_mode(root)
    targets = [root, root / "agent", root / "agent" / "core"]
    targets += [root / ".git"] if mode == "git" else [root / "agent" / "__init__.py", root / "agent" / "gui.py"]
    blocked = [t for t in targets if t.exists() and not os.access(t, os.W_OK)]
    if not blocked:
        return ""
    owner = ""
    if os.name != "nt":
        try:
            import pwd
            owner = pwd.getpwuid(blocked[0].stat().st_uid).pw_name
        except (ImportError, KeyError, OSError):
            owner = ""
    if os.name == "nt":
        return (f"Sem permissão para gravar em {blocked[0]}. Mova a pasta do Órbita para dentro da sua pasta de "
                "usuário (ex.: Documentos) ou abra o Órbita como administrador uma vez para atualizar.")
    return (f"Sem permissão para gravar em {blocked[0]}" + (f" (a pasta é do usuário '{owner}')" if owner else "")
            + ". Isso acontece quando o Órbita foi baixado ou instalado com sudo. Para liberar, rode no terminal:\n"
            f"sudo chown -R \"$USER\": \"{root}\"\ne abra o Órbita de novo.")


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
        # Alterações da pessoa não bloqueiam mais: a interface oferece "atualizar guardando minhas alterações".
        info["local_changes"] = local_changes(root)

    if not info["blocked"]:
        info["blocked"] = write_problem(root, mode)   # Linux: pasta de outro usuário (instalada com sudo)

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


def _collisions(root: Path, rels: list[str]) -> list[str]:
    """Caminhos que não cabem na pasta: arquivo onde precisa haver pasta, ou pasta onde vai um arquivo.

    Conferido antes da primeira gravação, inclusive entre os próprios itens do pacote."""
    names = {_path_key(rel) for rel in rels}
    seen: set[str] = set()
    bad = []
    for rel in rels:
        target = root / rel
        parents = [p for p in Path(rel).parents if p != Path(".")]
        key = _path_key(rel)   # `A.py` e `a.py` no mesmo pacote seriam um arquivo só no Windows
        if key in seen or target.is_dir() or any((root / p).exists() and not (root / p).is_dir() for p in parents) \
                or any(_path_key(p.as_posix()) in names for p in parents):
            bad.append(rel)
        seen.add(key)
    return bad


def _make_parents(root: Path, folder: Path, created: list[Path]) -> None:
    """Cria as pastas que faltam e anota quais eram novas (para sumirem se a transação voltar)."""
    missing = []
    while folder != root and not folder.exists():
        missing.append(folder)
        folder = folder.parent
    for path in reversed(missing):
        path.mkdir()
        created.append(path)


def _transaction(root: Path, backup: Path, writes: dict[str, bytes], removes: list[str],
                 finish=None) -> tuple[list[str], list[str], list[str]]:
    """Grava `writes`, apaga `removes` e chama `finish` como uma coisa só. Em qualquer falha, os arquivos
    substituídos e removidos voltam do backup, os novos e as pastas novas somem, e o erro sobe."""
    replaced: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    backed: list[str] = []
    created: list[Path] = []
    try:
        for rel, data in sorted(writes.items()):
            target = root / rel
            if target.is_file():
                _backup(root, backup, rel)
                backed.append(rel)
                replaced.append(rel)
            else:
                added.append(rel)
            _make_parents(root, target.parent, created)
            target.write_bytes(data)
        for rel in removes:
            _backup(root, backup, rel)
            backed.append(rel)
            (root / rel).unlink()
            removed.append(rel)
        if finish:
            finish()
    except BaseException:
        for rel in added:
            try:
                (root / rel).unlink(missing_ok=True)
            except OSError:
                pass
        for rel in backed:
            try:
                restore_backup(root, backup, [rel])
            except OSError:
                pass
        for folder in reversed(created):
            try:
                folder.rmdir()
            except OSError:
                pass
        raise
    return replaced, added, removed


def _write_manifest(root: Path, sha: str, files: dict) -> None:
    """Grava o manifesto de uma vez (arquivo temporário + troca): nunca fica meio escrito."""
    folder = updates_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    temp = folder / "install.json.tmp"
    temp.write_text(json.dumps({"sha": sha, "updated_at": datetime.now().isoformat(timespec="seconds"),
                                "files": files}, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temp, folder / "install.json")


def apply_zip(root: Path, zip_path: Path, sha: str) -> dict:
    """Aplica o ZIP como transação: ou a versão nova entra inteira (com manifesto), ou tudo volta como estava."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = updates_dir(root) / f"backup-{stamp}"
    with zipfile.ZipFile(zip_path) as archive:
        members = _safe_members(archive)
        payloads = {rel: archive.read(item) for rel, item in members.items() if not _blocked(root, rel)}
    writes = {}
    for rel, data in payloads.items():
        target = root / rel
        if target.is_file():
            current = target.read_bytes()
            if current == data or current.replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n"):
                continue   # igual (só a quebra de linha muda): não mexe
        writes[rel] = data
    # Antes de gravar qualquer coisa: se algum arquivo não puder ser substituído, não mexe em nada
    # (atualização pela metade é pior que nenhuma).
    locked = [rel for rel in writes
              if ((root / rel).exists() and not os.access(root / rel, os.W_OK))
              or (not (root / rel).exists() and _first_existing(root / rel).exists()
                  and not os.access(_first_existing(root / rel), os.W_OK))]
    if locked:
        raise RuntimeError(write_problem(root, "zip") or
                           f"Sem permissão para gravar {len(locked)} arquivo(s) do programa (ex.: {locked[0]}). "
                           "Nada foi alterado.")
    clash = _collisions(root, sorted(writes))
    if clash:
        raise RuntimeError(f"A versão nova não cabe na pasta: {clash[0]} esbarra em um arquivo ou pasta que já "
                           "existe com o mesmo nome. Nada foi alterado.")
    old = manifest(root).get("files") or {}
    keep = {_path_key(rel) for rel in members}   # no Windows, `Gui.py` na versão nova é o mesmo arquivo que `gui.py`
    removes = [rel for rel in sorted(old) if _path_key(rel) not in keep and not _blocked(root, rel)
               and (root / rel).is_file()]

    def finish():
        files = {rel: blob_sha((root / rel).read_bytes()) for rel in payloads if (root / rel).is_file()}
        _write_manifest(root, sha, files)

    try:
        replaced, added, removed = _transaction(root, backup, writes, removes, finish)
    except OSError as error:
        raise RuntimeError("A gravação foi interrompida e os arquivos anteriores voltaram. "
                           f"Nada foi alterado. ({error})") from error
    return {"replaced": replaced, "added": added, "removed": removed,
            "backup": str(backup) if (replaced or removed) else ""}


def apply_git(root: Path, keep_local: bool = False) -> dict:
    """`git pull --ff-only`. Com `keep_local`, alterações da pessoa em arquivos do programa são guardadas
    (cópia em data/updates/backup-… + git stash), a atualização entra e elas são reaplicadas por cima.
    Se uma delas conflitar com a versão nova, fica a versão nova e a da pessoa continua no backup."""
    problem = write_problem(root, "git")
    if problem:
        raise RuntimeError(problem)
    dirty = local_changes(root)
    if dirty and not keep_local:
        raise RuntimeError(f"Alterações locais não salvas em {len(dirty)} arquivo(s) ({', '.join(dirty[:5])}); "
                           "nada foi alterado.")
    generated = [p for p in _status(root) if p in GENERATED]
    if generated:   # o programa regravou (ex.: o ícone): volta ao original para o pull passar
        _git(root, "checkout", "--", *generated)
    backup = ""
    if dirty:
        folder = updates_dir(root) / f"backup-{datetime.now():%Y%m%d-%H%M%S}"
        for rel in dirty:
            _backup(root, folder, rel)
        backup = str(folder)
        _git(root, "stash", "push", "--quiet", "-m", "orbita: alterações guardadas antes de atualizar", "--", *dirty)
    before = _git(root, "rev-parse", "HEAD").strip()
    try:
        _git(root, "fetch", "--quiet", "origin", BRANCH)
        _git(root, "merge", "--ff-only", f"origin/{BRANCH}")
    except RuntimeError as error:
        if dirty:
            _git(root, "stash", "pop", "--quiet", check=False)   # devolve tudo como estava
        raise RuntimeError("Sua cópia tem commits que não estão no GitHub; atualize com git pull. "
                           f"Nada foi alterado. ({error})")
    changed = _git(root, "diff", "--name-only", before, "HEAD").split()
    conflicts: list[str] = []
    if dirty:
        _git(root, "stash", "pop", "--quiet", check=False)
        conflicts = _git(root, "diff", "--name-only", "--diff-filter=U", check=False).split()
        if conflicts:   # fica a versão nova; a da pessoa está no backup (e no git stash)
            _git(root, "checkout", "HEAD", "--", *conflicts, check=False)
            _git(root, "reset", "--quiet", "--", *conflicts, check=False)
    return {"replaced": changed, "added": [], "removed": [], "backup": backup,
            "kept_local": [p for p in dirty if p not in conflicts], "conflicts": conflicts}


def _first_existing(path: Path) -> Path:
    """A pasta mais próxima que já existe (onde um arquivo novo seria criado)."""
    for parent in path.parents:
        if parent.exists():
            return parent
    return path.anchor and Path(path.anchor) or path


def restore_backup(root: Path, backup: Path, rels: list[str]) -> None:
    """Devolve arquivos do programa. Caminho protegido no backup não volta por cima dos dados."""
    for rel in rels:
        rel = str(rel).replace("\\", "/")
        if not rel or rel.startswith("/") or ".." in rel.split("/") or ":" in rel or _blocked(root, rel):
            continue
        source = backup / rel
        if not source.is_file():
            continue
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def apply_verified(root: Path, zip_path: Path, manifest: dict, signature: str, key: bytes) -> dict:
    """Confere o selo e os hashes antes de gravar. Caminho protegido nunca é escrito.

    A chave é compartilhada (HMAC-SHA256), não uma assinatura de chave pública.
    O hash conferido é o SHA-256 dos bytes do arquivo, não o hash de blob do git.
    """
    from agent.core.update_auth import UpdateAuthError, verify_manifest

    verify_manifest(manifest, signature, key)
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict) or not files:
        raise UpdateAuthError("Manifesto sem arquivos. Nada foi alterado.")
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as error:
        raise UpdateAuthError(f"Pacote ilegível. Nada foi alterado. ({error})") from error
    try:
        members = _safe_members(archive)
        payloads: dict[str, bytes] = {}
        for rel, expected in files.items():
            rel_norm = str(rel).replace("\\", "/")
            if not rel_norm or rel_norm.startswith("/") or ".." in rel_norm.split("/") or ":" in rel_norm:
                raise UpdateAuthError("Caminho recusado. Nada foi alterado.")
            if _blocked(root, rel_norm):
                continue
            if not isinstance(expected, str) or len(expected) != 64:
                raise UpdateAuthError(f"Hash inválido em {rel_norm}. Nada foi alterado.")
            item = members.get(rel_norm)
            if item is None:
                raise UpdateAuthError(f"Arquivo ausente no pacote: {rel_norm}. Nada foi alterado.")
            data = archive.read(item)
            digest = hashlib.sha256(data).hexdigest()
            if not hmac.compare_digest(digest, expected.lower()):
                raise UpdateAuthError(f"Hash não confere em {rel_norm}. Nada foi alterado.")
            payloads[rel_norm] = data
    finally:
        archive.close()

    clash = _collisions(root, sorted(payloads))
    if clash:
        raise UpdateAuthError(f"{clash[0]} esbarra em um arquivo ou pasta que já existe. Nada foi alterado.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = updates_dir(root) / f"backup-{stamp}"
    try:
        replaced, added, _ = _transaction(root, backup, payloads, [])
    except OSError as error:
        raise UpdateAuthError(
            "A gravação foi interrompida e os arquivos anteriores voltaram. Nada ficou pela metade."
        ) from error
    return {"replaced": replaced, "added": added, "removed": [],
            "backup": str(backup) if replaced else ""}


def apply(root: Path = ROOT, sha: Optional[str] = None, keep_local: bool = False) -> dict:
    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "O aplicativo empacotado não atualiza por cima dos próprios arquivos. "
            "Instale um pacote novo. Conversas, chaves e modelos não foram tocados."
        )
    mode = install_mode(root)
    problem = write_problem(root, mode)
    if problem:
        raise RuntimeError(problem)
    if mode == "git":
        return apply_git(root, keep_local=keep_local)
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
    python = (root / "venv" / "Scripts" / "pythonw.exe") if os.name == "nt" else (root / "venv" / "bin" / "python")
    if not python.is_file():
        python = Path(sys.executable)
    subprocess.Popen([str(python), str(root / "launcher.py"), "--no-console"], cwd=str(root),
                     creationflags=_NO_WINDOW, start_new_session=os.name != "nt")


def start_detached(sha: str, root: Path = ROOT, keep_local: bool = False) -> None:
    """Chamado pela janela antes de fechar: o atualizador espera o programa sair e trabalha sozinho."""
    python = Path(sys.executable)
    windowed = python.with_name("pythonw.exe")
    subprocess.Popen([str(windowed if windowed.is_file() else python), "-m", "agent.core.updater", "apply",
                      "--pid", str(os.getpid()), "--sha", sha, "--restart"] + (["--keep-local"] if keep_local else []), cwd=str(root),
                     creationflags=_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0),
                     start_new_session=os.name != "nt")   # no Linux sobrevive ao fechamento da janela


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Atualizador do Órbita")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    run = sub.add_parser("apply")
    run.add_argument("--pid", type=int, default=0)
    run.add_argument("--sha", default=None)
    run.add_argument("--restart", action="store_true")
    run.add_argument("--keep-local", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "check":
        print(json.dumps(check(), ensure_ascii=False, indent=1))
        return 0
    if args.pid:
        _wait_pid(args.pid)
    result_file = updates_dir() / "result.json"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = {"ok": True, **apply(sha=args.sha, keep_local=args.keep_local)}
    except Exception as error:
        result = {"ok": False, "error": str(error)}
    result["at"] = datetime.now().isoformat(timespec="seconds")
    result_file.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.restart:
        relaunch()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
