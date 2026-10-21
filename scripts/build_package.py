"""Protótipo desktop PyInstaller: recursos públicos explícitos, sem pesos ou dados pessoais."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
WEB_FILES = {"index.html", "app.js", "app.css", "logo.svg", "app.ico"}
PRIVATE_PARTS = {"data", "models", "venv", ".venv", "env", "daily_logs", "long_term", "__pycache__"}
OPTIONAL_MODULES = ("torch", "torchaudio", "tensorflow", "faster_whisper", "ctranslate2", "kokoro_onnx",
                    "onnxruntime", "silero_vad", "nvidia", "PySide6", "PyQt5")
CATALOG = "agent/core/local_models.json"
BROWSER_PAGE = "agent/ui/browser.html"


def tracked_files(root: Path) -> list[str]:
    """Recusa fallback por glob: arquivos locais não rastreados nunca entram por acidente."""
    result = subprocess.run(["git", "ls-files", "-z", "--", "agent/ui/web", "skills"],
                            cwd=root, check=True, capture_output=True)
    return [p for p in result.stdout.decode("utf-8").split("\0") if p]


def resources(root: Path, names: list[str] | None = None) -> list[tuple[Path, str]]:
    result = []
    # Recursos fixos: não varre outros JSONs nem HTMLs (podem conter dados locais).
    selected = tracked_files(root) + [CATALOG, BROWSER_PAGE] if names is None else names
    for name in selected:
        rel = PurePosixPath(name)
        if rel.is_absolute() or ".." in rel.parts or "\\" in name:
            raise ValueError(f"Caminho de recurso inválido: {name}")
        if any(p.startswith(".") or p.lower() in PRIVATE_PARTS for p in rel.parts):
            continue
        web = str(rel.parent) == "agent/ui/web" and rel.name in WEB_FILES
        skill = len(rel.parts) >= 3 and rel.parts[0] == "skills" and rel.suffix in {".md", ".py"}
        if not (web or skill or name in {CATALOG, BROWSER_PAGE}):
            continue
        source = root / name
        if source.is_symlink() or source.resolve() != root.resolve() / name:
            raise ValueError(f"Link ou recurso fora do projeto: {name}")
        if not source.is_file():
            raise ValueError(f"Falta recurso rastreado: {name}")
        result.append((source, str(rel.parent)))
    return sorted(result, key=lambda pair: pair[0].as_posix())


def manifest(root: Path) -> dict:
    return {
        "schema": 1,
        "platform": platform.system().lower(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "components": {
            "desktop": {"included": True, "description": "Interface Qt, provedores e ferramentas do Órbita"},
            "local_voice": {"included": False, "description": "Whisper/Kokoro e pesos: usar instalação por fonte"},
            "ollama": {"included": False, "description": "Servidor independente, instalar separadamente"},
            "comfyui": {"included": False, "description": "Servidor independente, instalar separadamente"},
            "cuda": {"included": False, "description": "Drivers e bibliotecas da GPU não são distribuídos"},
        },
        "resources": [{"path": p.relative_to(root).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p, _ in resources(root)],
        "authentication": "unsigned-development-build",
    }


def command(root: Path, output: Path, manifest_path: Path) -> list[str]:
    args = [sys.executable, "-m", "PyInstaller", "--onedir", "--windowed", "--noupx",
            "--name", "Orbita", "--distpath", str(output / "dist"), "--workpath", str(output / "work"),
            "--specpath", str(output), "--paths", str(root), "--collect-submodules", "agent",
            "--add-data", f"{manifest_path}{os.pathsep}."]
    if os.name == "nt":
        args += ["--icon", str(root / "agent/ui/web/app.ico")]
    for module in OPTIONAL_MODULES:
        args += ["--exclude-module", module]
    for source, destination in resources(root):
        args += ["--add-data", f"{source}{os.pathsep}{destination}"]
    return args + [str(root / "packaging/orbita_entry.py")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "temp" / "package")
    parser.add_argument("--manifest-only", action="store_true", help="Inspeciona recursos sem compilar")
    args = parser.parse_args()
    if args.manifest_only:
        print(json.dumps(manifest(ROOT), ensure_ascii=False, indent=2))
        return 0
    if sys.platform not in {"win32", "linux"}:
        parser.error("protótipo disponível somente para Windows e Linux")
    try:
        importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError:
        parser.error("instale requirements-build.txt no ambiente virtual de compilação")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "components.json"
    manifest_path.write_text(json.dumps(manifest(ROOT), ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run(command(ROOT, output, manifest_path), cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
