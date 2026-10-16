"""
wake_word.py — Detecção de ativação do agente via tecla de atalho.
Por padrão usa Ctrl+Space. Configurável em config.py.
"""

import logging
import threading
import keyboard

from agent.core.config import HOTKEY_ACTIVATE

logger = logging.getLogger(__name__)


class WakeWord:
    """
    Gerencia a ativação do agente via tecla de atalho (hotkey).
    Funciona como um gate de bloqueio: wait_for_activation() fica travado
    até que a tecla seja pressionada.
    """

    def __init__(self, hotkey: str = None):
        self.hotkey = hotkey or HOTKEY_ACTIVATE
        self._event = threading.Event()
        self._active = False
        self._setup_hotkey()
        logger.info(f"Wake word configurada: '{self.hotkey}'")

    def _setup_hotkey(self):
        """Registra o callback da tecla de atalho."""
        try:
            keyboard.add_hotkey(self.hotkey, self._on_activate, suppress=True)
            logger.info(f"Hotkey '{self.hotkey}' registrada com sucesso.")
        except Exception as e:
            logger.error(f"Erro ao registrar hotkey '{self.hotkey}': {e}")

    def _on_activate(self):
        """Callback chamado quando a tecla de atalho é pressionada."""
        logger.debug(f"Hotkey '{self.hotkey}' acionada.")
        self._event.set()

    def wait_for_activation(self, timeout: float = None) -> bool:
        """
        Bloqueia até que a tecla de ativação seja pressionada.

        Args:
            timeout: Tempo máximo de espera em segundos. None = indefinido.

        Returns:
            True se ativado, False se timeout.
        """
        self._event.clear()
        activated = self._event.wait(timeout=timeout)
        return activated

    def cleanup(self):
        """Remove o registro da tecla de atalho."""
        try:
            keyboard.remove_hotkey(self.hotkey)
        except Exception:
            pass
