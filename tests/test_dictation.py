"""Ditado de ponta a ponta com microfone simulado: parcial enquanto fala, final no fim, cancelar e silêncio."""

import sys
import threading
import time
import types

import numpy as np
import pytest

from agent.voice import dictation as d


class FakeStream:
    """Entrega blocos de 100 ms como um microfone: fala (seno) por `speech` segundos, depois silêncio."""

    def __init__(self, speech, samplerate, channels, dtype, blocksize, callback):
        self.cb, self.block, self.speech, self.sr = callback, blocksize, speech, samplerate
        self.stop = threading.Event()

    def __enter__(self):
        def feed():
            t = 0.0
            while not self.stop.is_set():
                x = np.arange(self.block) / self.sr
                loud = 0.2 if t < self.speech else 0.0
                self.cb((loud * np.sin(2 * np.pi * 220 * x)).astype("float32")[:, None], self.block, None, None)
                t += self.block / self.sr
                time.sleep(0.01)   # 10x mais rápido que o tempo real
        threading.Thread(target=feed, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.stop.set()


@pytest.fixture
def fake_audio(monkeypatch):
    def install(speech):
        module = types.SimpleNamespace(InputStream=lambda **kw: FakeStream(speech, **kw))
        monkeypatch.setitem(sys.modules, "sounddevice", module)
    calls = []

    def transcribe(size, audio, final):
        calls.append((size, final))
        return "texto final" if final else "texto parcial"
    monkeypatch.setattr(d.WHISPER, "get", lambda size: None)
    monkeypatch.setattr(d.WHISPER, "warm", lambda size: None)
    monkeypatch.setattr(d.WHISPER, "transcribe", transcribe)
    monkeypatch.setattr(d.WHISPER, "partial_size", lambda size: "base")
    monkeypatch.setattr(d, "PARTIAL_EVERY", 0.05)
    return install, calls


def run(dictation, events, until, timeout=5):
    assert dictation.start() is None
    deadline = time.time() + timeout
    while time.time() < deadline and not until():
        time.sleep(0.02)


def test_partial_then_final_text(fake_audio):
    install, calls = fake_audio
    install(speech=60)
    events = []
    dic = d.Dictation(events.append, lambda: {"kind": "local", "size": "small"})
    run(dic, events, lambda: any(e["state"] == "partial" for e in events))
    dic.stop()
    run_until = time.time() + 5
    while time.time() < run_until and not any(e["state"] == "done" for e in events):
        time.sleep(0.02)
    states = [e["state"] for e in events]
    assert "recording" in states and "partial" in states and "level" in states
    assert events[-1] == {"type": "dictation", "state": "done", "text": "texto final"}
    assert ("base", False) in calls and ("small", True) in calls   # parcial leve, final no modelo escolhido


CLOUD = {"kind": "cloud", "label": "Groq · nuvem", "base_url": "https://api.groq.com/openai/v1",
         "key": "gsk_teste", "model": "whisper-large-v3-turbo"}


def _finish(dic, events):
    deadline = time.time() + 5
    while time.time() < deadline and not any(e["state"] in ("done", "error") for e in events):
        time.sleep(0.02)


def test_cloud_engine_sends_wav_and_never_loads_a_local_model(fake_audio, monkeypatch):
    install, calls = fake_audio
    install(speech=60)
    posts = []

    class Resp:
        status_code = 200

        def json(self):
            return {"text": f"nuvem {len(posts)}"}

    def post(url, headers, files, data, timeout):
        posts.append((url, headers["Authorization"], files["file"][1][:4], data["model"], data["language"]))
        return Resp()
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=post))
    monkeypatch.setattr(d, "PARTIAL_EVERY_CLOUD", 0.05)
    events = []
    dic = d.Dictation(events.append, lambda: CLOUD)
    run(dic, events, lambda: any(e["state"] == "partial" for e in events))
    dic.stop()
    _finish(dic, events)
    assert posts[0] == ("https://api.groq.com/openai/v1/audio/transcriptions", "Bearer gsk_teste", b"RIFF",
                        "whisper-large-v3-turbo", "pt")
    assert events[-1]["state"] == "done" and events[-1]["text"].startswith("nuvem")
    assert calls == []   # nenhum Whisper local: funciona em PC fraco
    assert any(e.get("engine") == "Groq · nuvem" for e in events)


def test_cloud_failure_at_the_end_keeps_the_last_partial(fake_audio, monkeypatch):
    install, _ = fake_audio
    install(speech=60)
    state = {"n": 0}

    class Resp:
        status_code = 200

        def json(self):
            return {"text": "quase tudo"}

    def post(url, headers, files, data, timeout):
        state["n"] += 1
        if timeout >= 60:
            raise OSError("sem internet")
        return Resp()
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(post=post))
    monkeypatch.setattr(d, "PARTIAL_EVERY_CLOUD", 0.05)
    events = []
    dic = d.Dictation(events.append, lambda: CLOUD)
    run(dic, events, lambda: any(e["state"] == "partial" for e in events))
    dic.stop()
    _finish(dic, events)
    assert events[-1]["text"] == "quase tudo" and "falhou" in events[-1]["message"]


def test_wav_bytes_is_a_valid_16k_mono_wav():
    import io
    import wave
    data = d.wav_bytes(np.zeros(16000, dtype="float32"))
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()) == (16000, 1, 2, 16000)


def test_cancel_sends_nothing(fake_audio):
    install, calls = fake_audio
    install(speech=60)
    events = []
    dic = d.Dictation(events.append, lambda: {"kind": "local", "size": "small"})
    run(dic, events, lambda: any(e["state"] == "recording" for e in events))
    dic.cancel()
    deadline = time.time() + 5
    while time.time() < deadline and dic.active:
        time.sleep(0.02)
    assert events[-1]["state"] == "cancelled" and ("small", True) not in calls


def test_silence_only_reports_nothing_heard(fake_audio):
    install, _ = fake_audio
    install(speech=0)
    events = []
    dic = d.Dictation(events.append, lambda: {"kind": "local", "size": "small"})
    run(dic, events, lambda: any(e["state"] == "recording" for e in events))
    time.sleep(0.2)
    dic.stop()
    deadline = time.time() + 5
    while time.time() < deadline and dic.active:
        time.sleep(0.02)
    assert events[-1]["state"] == "done" and events[-1]["text"] == "" and "Não ouvi" in events[-1]["message"]
