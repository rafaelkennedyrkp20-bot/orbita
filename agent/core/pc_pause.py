"""Pausa do controle do PC quando a pessoa assume o mouse.

Nada aqui retoma sozinho. Só `resume`, chamado pela interface, libera de novo.
"""

from __future__ import annotations

_TOLERANCE = 12


class PcPause:
    def __init__(self):
        self.paused = False
        self.reason = ""
        self._last: tuple[int, int] | None = None

    def before(self, current: tuple[int, int] | None) -> str | None:
        if self.paused:
            return self.reason or "O controle do PC está pausado e não volta sozinho."
        if self._last is not None and current is not None:
            if abs(current[0] - self._last[0]) > _TOLERANCE or abs(current[1] - self._last[1]) > _TOLERANCE:
                self.paused = True
                self.reason = ("O mouse saiu do lugar em que o Órbita deixou. "
                               "O controle ficou pausado e não volta sozinho.")
                return self.reason
        return None

    def after(self, position: tuple[int, int] | None) -> None:
        if self.paused or position is None:
            return
        self._last = (int(position[0]), int(position[1]))

    def pause(self, reason: str = "") -> None:
        self.paused = True
        self.reason = reason or "O controle do PC está pausado e não volta sozinho."

    def resume(self) -> None:
        self.paused = False
        self.reason = ""
        self._last = None


PC_PAUSE = PcPause()
