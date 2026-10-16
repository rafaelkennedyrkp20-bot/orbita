"""brand.py — Identidade do app no Windows: ícone, nome e registro na barra de tarefas."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

APP_NAME = "Órbita"
TAGLINE = "seu agente pessoal de IA"
APP_ID = "Orbita.Desktop.1"          # identidade própria na barra de tarefas do Windows
WEB_DIR = Path(__file__).resolve().parent / "web"
LOGO_SVG = WEB_DIR / "logo.svg"
ICON_FILE = WEB_DIR / "app.ico"
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def register_windows_app() -> None:
    """Sem isto o Windows agrupa a janela sob o ícone do python.exe."""
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass


def render_logo(size: int) -> QImage:
    renderer = QSvgRenderer(QByteArray(LOGO_SVG.read_bytes()))
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def app_icon() -> QIcon:
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(QPixmap.fromImage(render_logo(size)))
    return icon


def ensure_ico() -> Path:
    """Gera o .ico (multi-tamanho) a partir do logo SVG, para atalhos e o executável.

    Só se ele não existir: o .ico é versionado, e regravá-lo ao abrir (as datas dos arquivos depois de um
    `git clone` são aleatórias) deixava o git "sujo" e travava a atualização automática."""
    if ICON_FILE.exists():
        return ICON_FILE
    images = [render_logo(size) for size in (16, 24, 32, 48, 64, 128, 256)]
    _write_ico(images, ICON_FILE)
    return ICON_FILE


def _write_ico(images: list[QImage], path: Path) -> None:
    """Escreve um ICO com PNGs embutidos (formato aceito desde o Windows Vista)."""
    import struct

    from PyQt6.QtCore import QBuffer, QIODevice

    blobs = []
    for image in images:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        blobs.append((image.width(), bytes(buffer.data())))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries, data = b"", b""
    for size, png in blobs:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        data += png
    path.write_bytes(header + entries + data)
