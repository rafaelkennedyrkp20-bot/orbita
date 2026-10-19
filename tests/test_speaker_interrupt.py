"""Parar corta o próximo pedaço. O microfone só abre depois que a fala saiu."""

import threading

import numpy as np

from agent.voice.speaker import Speaker


def _speaker(monkeypatch):
    import agent.voice.speaker as speaker_mod

    speaker = Speaker()
    speaker._kokoro_available = True
    speaker._piper_available = False
    speaker._tts_engine = None
    created = []

    class Kokoro:
        def create(self, chunk, voice, speed, lang):
            created.append(chunk)
            return np.zeros(8, dtype=np.float32), 16000

    speaker._kokoro = Kokoro()
    speaker._chunks = lambda text, max_chars=360: ["Não pare.", "Ação seguinte.", "Terceiro pedaço."]
    monkeypatch.setattr(speaker_mod.sd, "play", lambda *args, **kwargs: None)
    monkeypatch.setattr(speaker_mod.sd, "wait", lambda: None)
    monkeypatch.setattr(speaker_mod.sd, "stop", lambda: None)
    return speaker, created, speaker_mod


def test_chunks_keep_portuguese_accents():
    chunks = Speaker._chunks(("Não pare agora. Ação seguinte precisa continuar nesta frase. " * 30).strip())
    assert len(chunks) > 1
    assert any("Não" in chunk and "Ação" in chunk or "Não" in chunk for chunk in chunks)


def test_stop_skips_the_remaining_chunks(monkeypatch):
    speaker, created, speaker_mod = _speaker(monkeypatch)
    played = []

    def play(samples, rate):
        played.append(created[-1])
        if len(played) == 1:
            speaker.stop()

    monkeypatch.setattr(speaker_mod.sd, "play", play)
    speaker.note_user_speech_ended()
    speaker._speech_ended_at -= 0.25
    speaker.speak("Não pare. Ação seguinte. Terceiro pedaço.")
    assert played == ["Não pare."]
    assert created == ["Não pare."]
    assert speaker.last_latency_ms is not None and speaker.last_latency_ms >= 200


def test_quiet_for_listen_waits_until_playback_stops(monkeypatch):
    speaker, created, speaker_mod = _speaker(monkeypatch)
    release = threading.Event()
    started = threading.Event()

    def wait():
        started.set()
        release.wait(2)

    def stop():
        release.set()

    monkeypatch.setattr(speaker_mod.sd, "wait", wait)
    monkeypatch.setattr(speaker_mod.sd, "stop", stop)
    worker = threading.Thread(target=lambda: speaker.speak("Não pare. Ação seguinte."))
    worker.start()
    assert started.wait(2)
    captured = []
    speaker.quiet_for_listen(timeout=2)
    captured.append("mic")
    worker.join(2)
    assert not worker.is_alive()
    assert not speaker._playing.is_set()
    assert created == ["Não pare."]
    assert captured == ["mic"]


def test_stop_ends_the_piper_process(monkeypatch):
    import agent.voice.speaker as speaker_mod

    speaker = Speaker()
    speaker._kokoro_available = False
    speaker._piper_available = True
    speaker._tts_engine = None
    ended = {}

    class Proc:
        def __init__(self):
            self.stdin = self
            self.stderr = self
            self.returncode = None
            self.terminated = False

        def write(self, data):
            assert "Não" in data.decode("utf-8")

        def close(self):
            pass

        def read(self):
            return b""

        def poll(self):
            if not self.terminated:
                speaker.stop()
                return None
            self.returncode = -1
            return -1

        def terminate(self):
            self.terminated = True
            ended["terminated"] = True

        def kill(self):
            ended["killed"] = True

        def wait(self, timeout=None):
            self.returncode = -1
            return -1

    monkeypatch.setattr(speaker_mod.subprocess, "Popen", lambda *args, **kwargs: Proc())
    monkeypatch.setattr(speaker_mod.sd, "play", lambda *a, **k: (_ for _ in ()).throw(AssertionError("tocou")))
    speaker.speak("Não pare.")
    assert ended.get("terminated") is True
