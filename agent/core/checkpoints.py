"""
checkpoints.py — Pontos de restauração da pasta do projeto, um por resposta do agente.

Usa um repositório git "sombra" guardado em data/checkpoints/<hash da pasta>, com a pasta do
projeto como work tree. O git do próprio projeto (se houver) não é tocado: nada de commits,
branches ou stash nele. Antes de cada resposta tiramos uma foto; depois, outra. A diferença
entre as duas é o que o agente mudou, e "desfazer" volta só esses arquivos.

Pastas grandes demais, a pasta pessoal ou a raiz de um disco ficam de fora (seria lento e
inútil). Sem git instalado, o recurso simplesmente se desliga.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent.core.config import DATA_DIR

logger = logging.getLogger(__name__)

ROOT = DATA_DIR / "checkpoints"
MAX_FILES = 20000          # acima disso a pasta não ganha checkpoints
MAX_FILE_MB = 20           # arquivos maiores não entram na foto
EXCLUDES = [".git/", "node_modules/", "venv/", ".venv/", "env/", "__pycache__/", "*.pyc", ".mypy_cache/",
            ".pytest_cache/", ".next/", "dist/", "build/", "target/", ".gradle/", ".idea/", ".vs/",
            "data/checkpoints/", "models/", "*.gguf", "*.safetensors", "*.bin", "*.iso", "*.zip", "*.7z"]
_SKIP_WALK = {d.rstrip("/") for d in EXCLUDES if d.endswith("/")}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class Change:
    path: str
    status: str            # A (novo) | M (alterado) | D (apagado)
    added: int = 0
    removed: int = 0


@dataclass
class Turn:
    """Foto de antes e de depois de uma resposta."""
    workspace: str
    before: str
    after: str
    changes: list[Change] = field(default_factory=list)


def git_available() -> bool:
    return shutil.which("git") is not None


def eligible(workspace: Path) -> bool:
    """Pasta pequena o bastante, que não seja a pasta pessoal nem a raiz de um disco."""
    try:
        workspace = workspace.resolve()
    except OSError:
        return False
    if not workspace.is_dir() or workspace == Path.home().resolve() or workspace.parent == workspace:
        return False
    count = 0
    for _, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in _SKIP_WALK]
        count += len(files)
        if count > MAX_FILES:
            return False
    return True


def _too_big(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > MAX_FILE_MB * 1024 * 1024
    except OSError:
        return False


class Checkpoints:

    def __init__(self, root: Path = ROOT):
        self.root = root
        self._eligible: dict[str, bool] = {}

    # ── git sombra ───────────────────────────────────────────

    def _git_dir(self, workspace: Path) -> Path:
        key = hashlib.sha1(str(workspace.resolve()).lower().encode("utf-8")).hexdigest()[:16]
        return self.root / key

    def _git(self, workspace: Path, *args: str, check: bool = True) -> str:
        cmd = ["git", "--git-dir", str(self._git_dir(workspace)), "--work-tree", str(workspace),
               "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "-c", "core.quotepath=false",
               "-c", "user.name=Órbita", "-c", "user.email=orbita@local", "-c", "commit.gpgsign=false", *args]
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        env.pop("GIT_DIR", None)
        env.pop("GIT_WORK_TREE", None)
        result = subprocess.run(cmd, cwd=str(workspace), capture_output=True, env=env, timeout=120,
                                creationflags=_NO_WINDOW)
        out = result.stdout.decode("utf-8", errors="replace")
        if check and result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or f"git {args[0]} falhou")
        return out

    def _ensure_repo(self, workspace: Path) -> None:
        git_dir = self._git_dir(workspace)
        if (git_dir / "HEAD").is_file():
            return
        git_dir.mkdir(parents=True, exist_ok=True)
        self._git(workspace, "init", "--quiet")
        (git_dir / "info").mkdir(exist_ok=True)
        (git_dir / "info" / "exclude").write_text("\n".join(EXCLUDES) + "\n", encoding="utf-8")
        (git_dir / "orbita-workspace.txt").write_text(str(workspace.resolve()), encoding="utf-8")

    def enabled_for(self, workspace: Path) -> bool:
        key = str(workspace)
        if key not in self._eligible:
            self._eligible[key] = git_available() and eligible(workspace)
        return self._eligible[key]

    def _large_files(self, workspace: Path) -> list[str]:
        """Arquivos novos ou alterados acima do limite: ficam fora da foto.

        Tem de rodar ANTES do `git add`: depois dele nada mais aparece como novo ou alterado.
        """
        out = self._git(workspace, "ls-files", "--others", "--modified", "--exclude-standard", "-z")
        return [rel for rel in dict.fromkeys(filter(None, out.split("\0"))) if _too_big(workspace / rel)]

    def _add_all(self, workspace: Path) -> None:
        """`git add --all`, menos os arquivos acima do limite (nem o blob deles é gravado).

        O rastreado que cresceu fica no índice com a versão antiga: para a foto, não mudou.
        """
        specs = ["."] + [f":(exclude,literal){rel}" for rel in self._large_files(workspace)]
        listing = self._git_dir(workspace) / "orbita-add.txt"   # sem limite de tamanho da linha de comando
        listing.write_bytes("\0".join(specs).encode("utf-8"))
        self._git(workspace, "add", "--all", f"--pathspec-from-file={listing}", "--pathspec-file-nul")

    # ── API ──────────────────────────────────────────────────

    def snapshot(self, workspace: Path, label: str) -> Optional[str]:
        """Grava o estado atual da pasta e devolve o id da foto (None se desligado ou falhou)."""
        if not self.enabled_for(workspace):
            return None
        try:
            self._ensure_repo(workspace)
            self._add_all(workspace)
            self._git(workspace, "commit", "--quiet", "--allow-empty", "--no-verify", "-m", label[:200])
            return self._git(workspace, "rev-parse", "HEAD").strip()
        except Exception as error:   # checkpoint nunca pode derrubar a resposta
            logger.warning("Checkpoint falhou em %s: %s", workspace, error)
            return None

    def changes(self, workspace: Path, before: str, after: str) -> list[Change]:
        numstat = self._git(workspace, "diff", "--no-renames", "--numstat", "-z", before, after)
        counts: dict[str, tuple[int, int]] = {}
        parts = numstat.split("\0")
        for item in parts:
            fields = item.split("\t")
            if len(fields) == 3:
                added, removed, path = fields
                counts[path] = (int(added) if added.isdigit() else 0, int(removed) if removed.isdigit() else 0)
        status = self._git(workspace, "diff", "--no-renames", "--name-status", "-z", before, after).split("\0")
        result = []
        for code, path in zip(status[0::2], status[1::2]):
            if code and path:
                added, removed = counts.get(path, (0, 0))
                result.append(Change(path, code[0], added, removed))
        return result

    def finish(self, workspace: Path, before: Optional[str], label: str) -> Optional[Turn]:
        """Foto de depois; devolve a resposta com o que mudou (None se nada mudou)."""
        if not before:
            return None
        after = self.snapshot(workspace, label)
        if not after:
            return None
        try:
            changes = self.changes(workspace, before, after)
        except Exception as error:
            logger.warning("Diff do checkpoint falhou: %s", error)
            return None
        return Turn(str(workspace), before, after, changes) if changes else None

    def diff(self, workspace: Path, before: str, after: str, max_chars: int = 200_000) -> str:
        text = self._git(workspace, "diff", "--no-renames", "--no-color", "-U3", before, after)
        return text if len(text) <= max_chars else text[:max_chars] + "\n… (diff cortado)"

    def undo(self, workspace: Path, before: str, after: str) -> dict:
        """Volta os arquivos que a resposta mudou para como estavam antes.

        Tira uma foto antes e outra depois, então nada se perde: `redo` é o par que, passado de
        novo a `undo`, refaz o que foi desfeito. Sem a foto de segurança nada é tocado, e um
        erro no meio do caminho devolve os arquivos ao estado dessa foto: em ambos os casos
        sobe RuntimeError, e o chamador não anuncia sucesso.
        """
        changes = self.changes(workspace, before, after)
        too_big = [c.path for c in changes if _too_big(workspace / c.path)]
        if too_big:   # a foto de segurança não guardaria a versão atual deles
            raise RuntimeError("Não desfiz nada: arquivos grandes demais para a foto de segurança: "
                               + ", ".join(too_big[:5]))
        safety = self.snapshot(workspace, "antes de desfazer")
        if not safety:
            raise RuntimeError("Não desfiz nada: a foto de segurança falhou.")
        restored, removed = [], []
        try:
            for change in changes:
                target = workspace / change.path
                if change.status == "A":
                    if target.is_file():
                        target.unlink()
                        removed.append(change.path)
                        self._prune_empty(workspace, target.parent)
                else:
                    self._git(workspace, "checkout", before, "--", change.path)
                    restored.append(change.path)
        except Exception as error:
            stuck = self._rollback(workspace, safety, [c.path for c in changes])
            state = (f"não consegui voltar {', '.join(stuck[:5])}; a foto de segurança é {safety[:12]}" if stuck
                     else "os arquivos voltaram ao estado anterior")
            raise RuntimeError(f"Desfazer falhou ({error}); {state}.") from error
        undone = self.snapshot(workspace, "desfeito")
        return {"restored": restored, "removed": removed,
                "redo": [safety, undone] if undone else None}

    def _rollback(self, workspace: Path, safety: str, paths: list[str]) -> list[str]:
        """Devolve `paths` ao que estava na foto de segurança; retorna os que não voltaram."""
        kept = set(filter(None, self._git(workspace, "ls-tree", "-r", "--name-only", "-z", safety, check=False)
                          .split("\0")))
        stuck = []
        for path in paths:
            try:
                if path in kept:
                    self._git(workspace, "checkout", safety, "--", path)
                elif (workspace / path).is_file():
                    (workspace / path).unlink()
                    self._prune_empty(workspace, (workspace / path).parent)
            except Exception as error:
                logger.error("Não consegui voltar %s para a foto de segurança %s: %s", path, safety, error)
                stuck.append(path)
        return stuck

    @staticmethod
    def _prune_empty(workspace: Path, folder: Path) -> None:
        root = workspace.resolve()
        folder = folder.resolve()
        while folder != root and root in folder.parents:
            try:
                folder.rmdir()   # só apaga se estiver vazia
            except OSError:
                return
            folder = folder.parent
