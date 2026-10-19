"""O controle do PC para quando o mouse sai do lugar e não volta sozinho."""

from agent.core.pc_pause import PcPause


def test_user_mouse_pauses_until_an_explicit_resume():
    pause = PcPause()
    assert pause.before((10, 10)) is None
    pause.after((10, 10))
    assert pause.before((12, 10)) is None
    reason = pause.before((40, 10))
    assert reason and "não volta sozinho" in reason
    assert pause.before((10, 10)) == reason
    pause.resume()
    assert pause.paused is False
    assert pause.before((40, 10)) is None
