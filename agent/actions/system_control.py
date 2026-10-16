"""
system_control.py — Controle de mouse, teclado, tela e sistema.
Usa pyautogui para automação e psutil para informações do sistema.
"""

import logging
import os
import time
from datetime import datetime
from typing import Optional, Tuple

import psutil

from agent.core.config import DATA_DIR

logger = logging.getLogger(__name__)
_pyautogui = None


def _gui():
    """pyautogui sob demanda: sem tela gráfica (servidor, SSH) o resto do módulo continua funcionando."""
    global _pyautogui
    if _pyautogui is None:
        try:
            import pyautogui
        except Exception as error:   # Linux sem DISPLAY, Wayland puro sem XWayland...
            raise RuntimeError(f"controle de tela indisponível neste sistema ({error}). No Linux é preciso uma "
                               "sessão gráfica X11 ou XWayland.") from error
        pyautogui.PAUSE = 0.1         # Pausa entre ações (evita erros)
        pyautogui.FAILSAFE = True     # Mover mouse para canto superior esquerdo = para tudo
        _pyautogui = pyautogui
    return _pyautogui

SCREENSHOTS_DIR = DATA_DIR / "screenshots"


def _linux_audio(pactl: list[str], amixer: list[str], done: str) -> str:
    import shutil
    import subprocess

    for argv in (pactl, amixer):
        if shutil.which(argv[0]):
            result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return done
    return "Não consegui mudar o áudio: instale pactl (PipeWire/PulseAudio) ou amixer (alsa-utils)."


class SystemControl:
    """
    Controla mouse, teclado, captura de tela e informações do sistema.
    """

    def __init__(self):
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("SystemControl inicializado.")

    # ─────────────────────────────────────────────
    # Screenshot
    # ─────────────────────────────────────────────

    def take_screenshot(self, filename: Optional[str] = None,
                        region: Optional[Tuple[int, int, int, int]] = None) -> str:
        """
        Tira um screenshot da tela.

        Args:
            filename: Nome do arquivo (sem extensão). Padrão: timestamp.
            region: Região (x, y, largura, altura) ou None para tela inteira.

        Returns:
            Caminho do arquivo salvo.
        """
        try:
            if not filename:
                filename = datetime.now().strftime("screenshot_%Y%m%d_%H%M%S")

            path = SCREENSHOTS_DIR / f"{filename}.png"

            img = _gui().screenshot(region=region)
            img.save(str(path))

            logger.info(f"Screenshot salvo: {path}")
            return str(path)
        except Exception as e:
            logger.error(f"Erro ao tirar screenshot: {e}")
            return f"Erro ao tirar screenshot: {e}"

    # ─────────────────────────────────────────────
    # Mouse
    # ─────────────────────────────────────────────

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> str:
        """
        Clica em uma posição da tela.

        Args:
            x, y: Coordenadas do clique.
            button: 'left', 'right' ou 'middle'.
            clicks: Número de cliques (2 = duplo clique).

        Returns:
            Confirmação da ação.
        """
        try:
            _gui().click(x, y, button=button, clicks=clicks)
            logger.debug(f"Clique em ({x}, {y}) [{button}]")
            return f"Clique em ({x}, {y}) realizado."
        except Exception as e:
            logger.error(f"Erro ao clicar: {e}")
            return f"Erro ao clicar: {e}"

    def move_mouse(self, x: int, y: int, duration: float = 0.3) -> str:
        """
        Move o mouse para uma posição.

        Args:
            x, y: Posição de destino.
            duration: Duração do movimento em segundos.

        Returns:
            Confirmação da ação.
        """
        try:
            _gui().moveTo(x, y, duration=duration)
            return f"Mouse movido para ({x}, {y})."
        except Exception as e:
            return f"Erro ao mover mouse: {e}"

    def scroll(self, amount: int, x: Optional[int] = None, y: Optional[int] = None) -> str:
        """
        Rola a tela (scroll).

        Args:
            amount: Quantidade (positivo = cima, negativo = baixo).
            x, y: Posição para rolar (None = posição atual do mouse).

        Returns:
            Confirmação da ação.
        """
        try:
            if x and y:
                _gui().scroll(amount, x=x, y=y)
            else:
                _gui().scroll(amount)
            direction = "cima" if amount > 0 else "baixo"
            return f"Scroll {direction} ({abs(amount)} unidades)."
        except Exception as e:
            return f"Erro no scroll: {e}"

    def get_mouse_position(self) -> Tuple[int, int]:
        """Retorna a posição atual do mouse."""
        return _gui().position()

    # ─────────────────────────────────────────────
    # Teclado
    # ─────────────────────────────────────────────

    def type_text(self, text: str, interval: float = 0.02) -> str:
        """
        Digita um texto.

        Args:
            text: Texto a digitar.
            interval: Intervalo entre teclas em segundos.

        Returns:
            Confirmação da ação.
        """
        try:
            if text.isascii() and "\n" not in text:
                _gui().typewrite(text, interval=interval)
            else:
                # pyautogui não digita acentos/emoji: cola via área de transferência
                # e restaura o conteúdo anterior.
                import pyperclip

                previous = pyperclip.paste()
                pyperclip.copy(text)
                _gui().hotkey("ctrl", "v")
                time.sleep(0.15)
                pyperclip.copy(previous)
            logger.debug(f"Texto digitado: '{text[:30]}'")
            return f"Texto digitado: '{text[:50]}'"
        except Exception as e:
            logger.error(f"Erro ao digitar: {e}")
            return f"Erro ao digitar: {e}"

    def press_key(self, key: str) -> str:
        """
        Pressiona uma tecla.

        Args:
            key: Tecla (ex: 'enter', 'esc', 'f5', 'ctrl+c').

        Returns:
            Confirmação da ação.
        """
        try:
            if "+" in key:
                keys = [k.strip() for k in key.split("+")]
                _gui().hotkey(*keys)
            else:
                _gui().press(key)
            return f"Tecla pressionada: {key}"
        except Exception as e:
            return f"Erro ao pressionar tecla '{key}': {e}"

    def hotkey(self, *keys: str) -> str:
        """
        Executa um atalho de teclado (ex: Ctrl+C, Ctrl+Alt+Del).

        Args:
            *keys: Teclas do atalho.

        Returns:
            Confirmação da ação.
        """
        try:
            _gui().hotkey(*keys)
            combo = "+".join(keys)
            return f"Atalho executado: {combo}"
        except Exception as e:
            return f"Erro ao executar atalho: {e}"

    # ─────────────────────────────────────────────
    # Informações do Sistema
    # ─────────────────────────────────────────────

    def get_system_info(self) -> str:
        """
        Retorna informações sobre o estado atual do sistema.

        Returns:
            String formatada com informações do sistema.
        """
        try:
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/")
            battery = psutil.sensors_battery()

            lines = [
                "📊 Status do Sistema:",
                f"  🖥️  CPU: {cpu:.1f}%",
                f"  💾 RAM: {ram.percent:.1f}% usada ({ram.used / 1024**3:.1f}/{ram.total / 1024**3:.1f} GB)",
                f"  💿 Disco C: {disk.percent:.1f}% usado ({disk.free / 1024**3:.1f} GB livres)",
            ]

            if battery:
                status = "carregando" if battery.power_plugged else "bateria"
                lines.append(f"  🔋 Bateria: {battery.percent:.0f}% ({status})")

            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Erro ao obter info do sistema: {e}")
            return f"Erro ao obter informações do sistema: {e}"

    def get_screen_size(self) -> Tuple[int, int]:
        """Retorna a resolução da tela principal."""
        return _gui().size()

    # ─────────────────────────────────────────────
    # Volume
    # ─────────────────────────────────────────────

    def set_volume(self, level: int) -> str:
        """
        Ajusta o volume do sistema (Windows: API de áudio; Linux: PipeWire/PulseAudio ou ALSA).

        Args:
            level: Nível de 0 a 100.

        Returns:
            Confirmação da ação.
        """
        if os.name != "nt":
            return _linux_audio(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{max(0, min(100, level))}%"],
                                ["amixer", "-q", "sset", "Master", f"{max(0, min(100, level))}%"],
                                f"Volume ajustado para {max(0, min(100, level))}%.")
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            import math

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))

            # Converte 0-100 para dB (escala logarítmica)
            level = max(0, min(100, level))
            if level == 0:
                volume.SetMasterVolumeLevel(-65.25, None)
            else:
                db = 20 * math.log10(level / 100)
                volume.SetMasterVolumeLevel(db, None)

            return f"Volume ajustado para {level}%."
        except ImportError:
            # Fallback via teclas de mídia
            times = level // 2
            for _ in range(50):
                _gui().press("volumedown")
            for _ in range(times):
                _gui().press("volumeup")
            return f"Volume ajustado (aproximado) para {level}%."
        except Exception as e:
            logger.error(f"Erro ao ajustar volume: {e}")
            return f"Erro ao ajustar volume: {e}"

    def mute_toggle(self) -> str:
        """Alterna mudo/unmuted."""
        if os.name != "nt":
            return _linux_audio(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
                                ["amixer", "-q", "sset", "Master", "toggle"], "Áudio alternado (mudo/normal).")
        try:
            _gui().press("volumemute")
            return "Áudio alternado (mudo/normal)."
        except Exception as e:
            return f"Erro ao alternar mudo: {e}"

    # ─────────────────────────────────────────────
    # Clipboard
    # ─────────────────────────────────────────────

    def copy_to_clipboard(self, text: str) -> str:
        """Copia texto para a área de transferência."""
        try:
            import pyperclip
            pyperclip.copy(text)
            return f"Copiado para clipboard: '{text[:50]}'"
        except ImportError:
            return "pyperclip não instalado. Use: pip install pyperclip"
        except Exception as e:
            return f"Erro ao copiar: {e}"

    def get_clipboard(self) -> str:
        """Retorna o conteúdo atual da área de transferência."""
        try:
            import pyperclip
            return pyperclip.paste()
        except ImportError:
            return "pyperclip não instalado."
        except Exception as e:
            return f"Erro ao ler clipboard: {e}"
