"""Montagem curta de imagens que já estão no disco.

Isto não é um modelo de vídeo. Não baixa peso, não chama API e não troca
para a nuvem se o ffmpeg não existir. O limite é aplicado antes de executar:
até 8 segundos, 1280x720, 12 imagens e 8 quadros por segundo.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

MAX_SECONDS = 8
MAX_IMAGES = 12
MAX_WIDTH = 1280
MAX_HEIGHT = 720
FPS = 8
_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ClipError(RuntimeError):
    pass


def _number(value, *, minimum: float, maximum: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ClipError(f"{label} inválido.")
    number = float(value)
    if number < minimum or number > maximum:
        raise ClipError(
            f"{label} fora do limite. O clipe aceita até {MAX_SECONDS:g} segundos, "
            f"{MAX_WIDTH}x{MAX_HEIGHT} e {MAX_IMAGES} imagens. Nada foi executado."
        )
    return number


def _size(text: str) -> tuple[int, int]:
    raw = (text or "640x360").lower().replace(" ", "")
    if "x" not in raw:
        raise ClipError("Tamanho inválido. Use largura x altura, por exemplo 640x360.")
    width_text, height_text = raw.split("x", 1)
    try:
        width, height = int(width_text), int(height_text)
    except ValueError:
        raise ClipError("Tamanho inválido. Use números pares, por exemplo 640x360.") from None
    if width % 2 or height % 2 or not 64 <= width <= MAX_WIDTH or not 64 <= height <= MAX_HEIGHT:
        raise ClipError(
            f"Tamanho fora do limite. Use números pares entre 64 e {MAX_WIDTH}x{MAX_HEIGHT}. "
            "Nada foi executado."
        )
    return width, height


def _remote(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return lowered.startswith(("http://", "https://", "ftp://", "data:"))


def render_clip(frames: list[Path], dest: Path, *, seconds: float, width: int, height: int,
                cancel: threading.Event | None = None, runner=None, ffmpeg: str | None = None) -> None:
    """Monta o mp4. `runner(argv, cancel)` executa só este processo."""
    if not frames or len(frames) > MAX_IMAGES:
        raise ClipError(f"Informe de 1 a {MAX_IMAGES} imagens locais.")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or
            not 0.5 <= float(seconds) <= MAX_SECONDS or
            isinstance(width, bool) or isinstance(height, bool) or
            not isinstance(width, int) or not isinstance(height, int) or
            width % 2 or height % 2 or not 64 <= width <= MAX_WIDTH or not 64 <= height <= MAX_HEIGHT):
        raise ClipError(
            f"O clipe passa do limite (até {MAX_SECONDS:g} segundos, {MAX_WIDTH}x{MAX_HEIGHT} "
            f"e {MAX_IMAGES} imagens). Nada foi executado."
        )
    if cancel is not None and cancel.is_set():
        raise ClipError("Montagem cancelada antes de começar. Nenhum processo foi aberto.")
    executable = ffmpeg if ffmpeg is not None else shutil.which("ffmpeg")
    if not executable:
        raise ClipError(
            "O ffmpeg não está neste computador. O Órbita não baixa um modelo de vídeo "
            "nem instala o ffmpeg sozinho."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="orbita-clip-") as folder:
        folder_path = Path(folder)
        copied = []
        for index, frame in enumerate(frames, start=1):
            target = folder_path / f"frame-{index:02d}{frame.suffix.lower()}"
            shutil.copyfile(frame, target)
            copied.append(target)
        each = seconds / len(copied)
        lines = []
        for frame in copied:
            lines.append(f"file '{frame.as_posix()}'")
            lines.append(f"duration {each:.3f}")
        lines.append(f"file '{copied[-1].as_posix()}'")
        script = folder_path / "lista.txt"
        script.write_text("\n".join(lines), encoding="utf-8")
        output_frames = int(seconds * FPS)
        argv = [
            executable, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(script),
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-t", f"{seconds:.3f}", "-r", str(FPS), "-frames:v", str(output_frames),
            "-pix_fmt", "yuv420p", str(dest),
        ]
        code = (runner or _run)(argv, cancel)
    if cancel is not None and cancel.is_set():
        try:
            if dest.is_file():
                dest.unlink()
        except OSError:
            pass
        raise ClipError("Montagem cancelada. Só este processo foi encerrado.")
    if code != 0 or not dest.is_file():
        raise ClipError("O ffmpeg não conseguiu montar o clipe. Nenhum modelo de vídeo foi chamado.")


def _run(argv: list[str], cancel: threading.Event | None) -> int:
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
    try:
        while proc.poll() is None:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                return -1
            time.sleep(0.05)
        return int(proc.returncode or 0)
    except Exception:
        if proc.poll() is None:
            proc.kill()
        raise
