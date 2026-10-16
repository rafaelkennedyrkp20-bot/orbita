"""
toolbox.py — Caixa de ferramentas opcional: programas que a IA sabe usar.

Catálogo versionado em `toolbox_catalog.json` (versão fixa, URL oficial, SHA-256, tamanho).
Instalações vão para `models/tools/<id>/<versão>/` (fora do git). Regras:

- Só baixa URL que está no catálogo, e só https.
- Download vai para um `.part`; tamanho ou SHA-256 diferente → arquivo apagado e erro.
- Extrai zip / tar.xz (Python) e 7z (`tar` do Windows ou `7z`), sem rodar instalador nem pedir admin.
- Extração numa pasta temporária, renomeada só no fim (instalação nunca fica pela metade).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from agent.core.config import MODELS_DIR

logger = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).with_name("toolbox_catalog.json")
TOOLS_DIR = MODELS_DIR / "tools"
FORMATS = {"zip", "7z", "tar.xz", "raw"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ProgressFn = Callable[[dict], None]


def platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return ""


def size_label(size: int) -> str:
    mb = size / 1e6
    return f"{mb:.1f} MB" if mb < 100 else f"{mb:.0f} MB"


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["tools"]


def download(url: str, target: Path, on_bytes: Callable[[int], None],
             cancel: Optional[threading.Event] = None, limit: int = 0) -> None:
    """Baixa `url` para `target` em blocos, chamando `on_bytes(total_lido)`."""
    import httpx

    done = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as response:
        response.raise_for_status()
        with open(target, "wb") as out:
            for chunk in response.iter_bytes(1 << 20):
                if cancel is not None and cancel.is_set():
                    raise InterruptedError("Download cancelado.")
                done += len(chunk)
                if limit and done > limit:
                    raise ValueError("O servidor mandou mais dados do que o tamanho registrado no catálogo.")
                out.write(chunk)
                on_bytes(done)


class Toolbox:

    def __init__(self, root: Path = TOOLS_DIR, catalog_path: Path = CATALOG_PATH,
                 platform: Optional[str] = None, fetch: Callable = download):
        self.root = Path(root)
        self.catalog_path = catalog_path
        self.platform = platform if platform is not None else platform_key()
        self.fetch = fetch
        self._listeners: list[ProgressFn] = []
        self._busy: dict[str, dict] = {}
        self._lock = threading.Lock()

    # ── Catálogo ─────────────────────────────────────────────

    def tools(self) -> list[dict]:
        return load_catalog(self.catalog_path)

    def get(self, tool_id: str) -> dict:
        for item in self.tools():
            if item["id"] == tool_id:
                return item
        raise KeyError(f"'{tool_id}' não está no catálogo. Opções: {', '.join(t['id'] for t in self.tools())}")

    def package(self, item: dict) -> Optional[dict]:
        return (item.get("packages") or {}).get(self.platform)

    def install_dir(self, item: dict) -> Path:
        return self.root / item["id"] / item["version"]

    # ── Progresso ────────────────────────────────────────────

    def add_listener(self, fn: ProgressFn) -> None:
        self._listeners.append(fn)

    def _emit(self, data: dict) -> None:
        if data.get("state") in ("downloading", "extracting"):
            self._busy[data["id"]] = data
        else:
            self._busy.pop(data["id"], None)
        for fn in list(self._listeners):
            try:
                fn(dict(data))
            except Exception:
                logger.exception("Ouvinte da caixa de ferramentas falhou")

    # ── Consulta ─────────────────────────────────────────────

    def find_executable(self, tool_id: str) -> Optional[Path]:
        """Executável instalado pela caixa (versão do catálogo), ou None."""
        item = self.get(tool_id)
        pkg = self.package(item)
        folder = self.install_dir(item)
        if not pkg or not folder.is_dir():
            return None
        for pattern in (pkg["exe"], f"*/{pkg['exe']}", f"*/bin/{pkg['exe']}", f"**/{pkg['exe']}"):
            found = sorted(folder.glob(pattern), key=lambda p: (len(p.parts), str(p)))
            if found:
                return found[0]
        return None

    def system_executable(self, tool_id: str) -> Optional[str]:
        """Mesmo programa já disponível no PATH do sistema (ex.: ffmpeg do winget)."""
        item = self.get(tool_id)
        pkg = self.package(item) or {}
        name = Path(pkg.get("exe") or item["id"]).stem.split("_")[0].lower()
        return shutil.which(name)

    def status(self, tool_id: str) -> dict:
        item = self.get(tool_id)
        pkg = self.package(item)
        exe = self.find_executable(tool_id)
        busy = self._busy.get(tool_id)
        return {
            "id": item["id"], "name": item["name"], "purpose": item["purpose"], "version": item["version"],
            "homepage": item.get("homepage", ""),
            "size": pkg["size"] if pkg else 0, "size_label": size_label(pkg["size"]) if pkg else "",
            "source": urlparse(pkg["url"]).netloc if pkg else "",
            "available": bool(pkg),
            "installed": exe is not None, "exe": str(exe) if exe else "",
            "system_exe": self.system_executable(tool_id) or "",
            "state": busy["state"] if busy else "", "pct": busy.get("pct", 0) if busy else 0,
            "package_commands": item.get("linux_packages", {}) if self.platform == "linux" and not pkg else {},
            "test": item.get("test", []),
        }

    def list(self) -> list[dict]:
        return [self.status(item["id"]) for item in self.tools()]

    def approval_detail(self, tool_id: str) -> str:
        """Texto do pedido de permissão: nome, versão, tamanho e origem exata."""
        try:
            item = self.get(tool_id)
        except KeyError as error:
            return str(error)
        pkg = self.package(item)
        if not pkg:
            return f"{item['name']} {item['version']}: sem pacote portátil para este sistema (nada será baixado)."
        return (f"{item['name']} {item['version']} · {size_label(pkg['size'])}\n"
                f"Origem: {pkg['url']}\nDestino: {self.install_dir(item)}")

    # ── Instalar / remover ───────────────────────────────────

    def install(self, tool_id: str, cancel: Optional[threading.Event] = None) -> Path:
        item = self.get(tool_id)
        pkg = self.package(item)
        if not pkg:
            raise RuntimeError(f"{item['name']} não tem pacote portátil para este sistema.")
        url = pkg["url"]
        if urlparse(url).scheme != "https" or pkg.get("format") not in FORMATS:
            raise ValueError(f"Entrada inválida no catálogo para {item['name']}.")
        existing = self.find_executable(tool_id)
        if existing:
            return existing
        with self._lock:
            if tool_id in self._busy:
                raise RuntimeError(f"{item['name']} já está sendo instalado.")
            self._busy[tool_id] = {"id": tool_id, "state": "downloading", "pct": 0}
        try:
            exe = self._install(item, pkg, cancel)
        except BaseException as error:
            self._emit({"id": tool_id, "state": "error", "error": str(error)})
            raise
        self._emit({"id": tool_id, "state": "done", "exe": str(exe)})
        return exe

    def _install(self, item: dict, pkg: dict, cancel: Optional[threading.Event]) -> Path:
        tool_id, total = item["id"], int(pkg["size"])
        base = self.root / tool_id
        base.mkdir(parents=True, exist_ok=True)
        part = base / (Path(urlparse(pkg["url"]).path).name + ".part")
        staging = base / f".staging-{item['version']}"
        last = [0.0]

        def on_bytes(done: int) -> None:
            if time.time() - last[0] > 0.3 or done >= total:
                last[0] = time.time()
                self._emit({"id": tool_id, "state": "downloading", "pct": min(99, int(done * 100 / total)),
                            "done": done, "total": total})

        try:
            self._emit({"id": tool_id, "state": "downloading", "pct": 0, "done": 0, "total": total})
            self.fetch(pkg["url"], part, on_bytes, cancel, total + 1024)
            got = part.stat().st_size
            if got != total:
                raise ValueError(f"Tamanho diferente do catálogo ({got} ≠ {total} bytes). Download apagado.")
            digest = _sha256(part)
            if digest != pkg["sha256"].lower():
                raise ValueError(f"SHA-256 não confere (esperado {pkg['sha256'][:12]}…, veio {digest[:12]}…). "
                                 "Download apagado.")
            self._emit({"id": tool_id, "state": "extracting", "pct": 100})
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            _extract(part, staging, pkg)
            if not sorted(staging.rglob(pkg["exe"])):
                raise RuntimeError(f"O pacote não tem o executável esperado ({pkg['exe']}).")
            target = self.install_dir(item)
            shutil.rmtree(target, ignore_errors=True)
            staging.rename(target)
            for old in base.iterdir():   # versões antigas saem para não ocupar espaço
                if old.is_dir() and old.name != item["version"] and not old.name.startswith("."):
                    shutil.rmtree(old, ignore_errors=True)
        finally:
            part.unlink(missing_ok=True)
            shutil.rmtree(staging, ignore_errors=True)
        exe = self.find_executable(tool_id)
        if exe is None:
            raise RuntimeError("Instalação concluída, mas o executável não foi encontrado.")
        if os.name != "nt":
            exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return exe

    def remove(self, tool_id: str) -> bool:
        item = self.get(tool_id)
        if tool_id in self._busy:
            raise RuntimeError(f"{item['name']} está sendo instalado agora.")
        folder = self.root / item["id"]
        existed = folder.exists()
        shutil.rmtree(folder, ignore_errors=True)
        self._emit({"id": tool_id, "state": "removed"})
        return existed

    def run_test(self, tool_id: str, timeout: int = 90) -> str:
        """Roda o comando de teste do catálogo (ex.: `magick -version`) e devolve a primeira linha."""
        exe = self.find_executable(tool_id)
        if exe is None:
            raise RuntimeError("Programa não instalado.")
        proc = subprocess.run([str(exe), *self.get(tool_id).get("test", [])], capture_output=True,
                              timeout=timeout, creationflags=NO_WINDOW)
        text = (proc.stdout or proc.stderr).decode("utf-8", "replace").strip()
        if proc.returncode != 0:
            raise RuntimeError(f"Teste saiu com código {proc.returncode}: {text[:300]}")
        return text.splitlines()[0] if text else "(sem saída)"


# ── Auxiliares ───────────────────────────────────────────────

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(base: Path, name: str) -> bool:
    target = (base / name).resolve()
    return target == base.resolve() or base.resolve() in target.parents


def _extract(archive: Path, dest: Path, pkg: dict) -> None:
    kind = pkg["format"]
    if kind == "raw":   # AppImage: o próprio arquivo é o programa
        shutil.copyfile(archive, dest / pkg["exe"])
        return
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            bad = [n for n in zf.namelist() if not _inside(dest, n)]
            if bad:
                raise ValueError(f"Pacote com caminho perigoso: {bad[0]}")
            zf.extractall(dest)
        return
    if kind == "tar.xz":
        with tarfile.open(archive, "r:xz") as tf:
            bad = [m.name for m in tf.getmembers() if not _inside(dest, m.name) or m.issym() and
                   not _inside(dest, str(Path(m.name).parent / m.linkname))]
            if bad:
                raise ValueError(f"Pacote com caminho perigoso: {bad[0]}")
            tf.extractall(dest)
        return
    # 7z: o `tar` do Windows (bsdtar/libarchive) lê 7z e recusa caminhos com ".."; 7-Zip como reserva.
    # O tar do System32 vem antes do PATH: o tar do Git (GNU) não abre 7z.
    system_tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    tar = str(system_tar) if os.name == "nt" and system_tar.is_file() else "tar"
    errors = []
    for command in ([tar, "-xf", str(archive), "-C", str(dest)],
                    ["7z", "x", "-y", f"-o{dest}", str(archive)]):
        if not shutil.which(command[0]):
            continue
        proc = subprocess.run(command, capture_output=True, timeout=900, creationflags=NO_WINDOW)
        if proc.returncode == 0:
            return
        errors.append((proc.stderr or proc.stdout).decode("utf-8", "replace")[-300:])
    raise RuntimeError("Não consegui extrair o .7z (precisa do tar do Windows 10+ ou do 7-Zip). "
                       + " | ".join(errors))


_default: Optional[Toolbox] = None


def get_toolbox() -> Toolbox:
    """Instância única: interface e agente veem o mesmo progresso."""
    global _default
    if _default is None:
        _default = Toolbox()
    return _default


# ── Ferramentas do agente ────────────────────────────────────

def register_toolbox_tools(registry, box: Optional[Toolbox] = None) -> None:
    from agent.core.tools import ToolContext, ToolResult, tool

    def current() -> Toolbox:
        return box or get_toolbox()

    @tool(registry, "toolbox_list",
          "List optional creative programs (ImageMagick, OpenSCAD, Blender, Godot, FFmpeg): installed path or "
          "download size. After installing, call them with run_shell using the full executable path.",
          group="shell")
    def toolbox_list(args, ctx: ToolContext):
        lines = []
        for s in current().list():
            if s["installed"]:
                where = f"instalado: {s['exe']}"
            elif s["system_exe"]:
                where = f"já no sistema (PATH): {s['system_exe']}"
            elif s["available"]:
                where = f"não instalado · {s['size_label']} · toolbox_install id='{s['id']}'"
            else:
                cmds = "; ".join(f"{k}: {v}" for k, v in s["package_commands"].items())
                where = f"sem pacote portátil aqui; peça ao usuário para instalar ({cmds or s['homepage']})"
            test = " ".join(s["test"])
            lines.append(f"- {s['id']} · {s['name']} {s['version']} — {s['purpose']}\n  {where}"
                         + (f"\n  teste: <exe> {test}" if test else ""))
        return "\n".join(lines)

    ids = [item["id"] for item in current().tools()]

    @tool(registry, "toolbox_install",
          "Download and install an optional program from the fixed official catalog (asks the user; shows "
          "size and source). Returns the executable path to use with run_shell. Prefer a program already on "
          "PATH unless force=true.",
          {"id": {"type": "string", "enum": ids, "description": "Program id from toolbox_list"},
           "force": {"type": "boolean", "description": "Install even if the program is already on PATH"}},
          ["id"], risk="exec", group="shell")
    def toolbox_install(args, ctx: ToolContext):
        tb = current()
        tool_id = str(args["id"]).strip().lower()
        item = tb.get(tool_id)
        system = tb.system_executable(tool_id)
        if system and not tb.find_executable(tool_id) and not args.get("force"):
            return f"{item['name']} já está no PATH do sistema: {system}\nUse esse caminho no run_shell."
        if not tb.package(item):
            cmds = "\n".join(f"  {k}: {v}" for k, v in item.get("linux_packages", {}).items())
            return (f"{item['name']} não tem pacote portátil para este sistema; nada foi baixado. "
                    f"Peça ao usuário para instalar pelo gerenciador de pacotes:\n{cmds}")
        exe = tb.install(tool_id, cancel=ctx.cancel)
        try:
            check = tb.run_test(tool_id)
        except Exception as error:
            return ToolResult.error(f"Instalado em {exe}, mas o teste falhou: {error}")
        return (f"Instalado: {item['name']} {item['version']}\nExecutável: {exe}\nTeste: {check}\n"
                f"No run_shell (PowerShell) use o caminho completo: & \"{exe}\" {' '.join(item.get('test', []))}")
