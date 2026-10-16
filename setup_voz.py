"""Baixa a voz neural local (Kokoro, ~350 MB) usada pelo Órbita para ler as respostas.

Uso: venv\\Scripts\\python.exe setup_voz.py
Sem estes arquivos o Órbita usa a voz do Windows automaticamente.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

DEST = Path(__file__).resolve().parent / "models" / "tts" / "kokoro"
BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = {"kokoro-v1.0.onnx": 325_532_387, "voices-v1.0.bin": 28_214_398}


def download(name: str, size: int) -> None:
    target = DEST / name
    if target.exists() and target.stat().st_size == size:
        print(f"✓ {name} já está pronto")
        return
    partial = target.with_suffix(target.suffix + ".part")
    print(f"↓ Baixando {name} ({size / 1e6:.0f} MB)...")
    with urllib.request.urlopen(BASE + name) as response, open(partial, "wb") as out:
        done = 0
        while chunk := response.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            print(f"\r  {done / size * 100:5.1f}%", end="", flush=True)
    print()
    if partial.stat().st_size != size:
        partial.unlink()
        raise RuntimeError(f"Download incompleto de {name}. Tente de novo.")
    partial.replace(target)


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    try:
        for name, size in FILES.items():
            download(name, size)
    except Exception as error:  # rede, disco cheio...
        print(f"Falha: {error}")
        return 1
    print("Voz neural pronta. Ative 'Ler respostas em voz alta' em Configurações › Voz.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
