"""Síntese de voz local com Kokoro ONNX e fallbacks offline."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import threading
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

from agent.core.config import (
    KOKORO_LANGUAGE,
    KOKORO_MODEL_PATH,
    KOKORO_SPEED,
    KOKORO_VOICE,
    KOKORO_VOICES_PATH,
    PIPER_EXECUTABLE,
    PIPER_VOICE_CONFIG,
    PIPER_VOICE_MODEL,
    TTS_ENGINE,
    TTS_FALLBACK_PREFERRED_GENDER,
    TTS_SPEED,
    TTS_SYSTEM_VOICE_NAME,
)


logger = logging.getLogger(__name__)


class Speaker:
    """Fala localmente sem manter modelos na GPU."""

    def __init__(self):
        self._lock = threading.Lock()
        self._gen_lock = threading.Lock()
        self._generation = 0
        self._cancels: list[threading.Event] = []
        self._playing = threading.Event()
        self._speech_ended_at: float | None = None
        self._marked_audio = False
        self.last_latency_ms: int | None = None
        self._tts_engine = None
        self._kokoro = None
        self._kokoro_available = (
            TTS_ENGINE.lower() == "kokoro"
            and os.path.isfile(KOKORO_MODEL_PATH)
            and os.path.isfile(KOKORO_VOICES_PATH)
        )
        self._piper_available = TTS_ENGINE.lower() == "piper" and self._check_piper()

        if self._kokoro_available:
            logger.info("Kokoro TTS configurado com a voz feminina pf_dora (carregamento sob demanda).")
        elif self._piper_available:
            logger.info("Piper TTS configurado: %s", os.path.basename(PIPER_VOICE_MODEL))
        else:
            logger.info("Kokoro/Piper indisponível. Usando voz feminina do Windows como fallback.")
            self._init_fallback()

    def _check_piper(self) -> bool:
        return all((
            os.path.isfile(PIPER_EXECUTABLE),
            os.path.isfile(PIPER_VOICE_MODEL),
            os.path.isfile(PIPER_VOICE_CONFIG),
        ))

    def _init_fallback(self) -> None:
        try:
            import pyttsx3

            self._tts_engine = pyttsx3.init()
            self._tts_engine.setProperty("rate", 180)
            requested = TTS_SYSTEM_VOICE_NAME.lower()
            preferred = None
            for voice in self._tts_engine.getProperty("voices"):
                label = f"{getattr(voice, 'id', '')} {getattr(voice, 'name', '')}".lower()
                gender = str(getattr(voice, "gender", "")).lower()
                if requested and requested in label:
                    preferred = voice.id
                    break
                if TTS_FALLBACK_PREFERRED_GENDER.lower().startswith("f") and gender.startswith("f"):
                    preferred = voice.id
            if preferred:
                self._tts_engine.setProperty("voice", preferred)
                logger.info("Fallback TTS selecionado: %s", preferred)
        except Exception as error:
            logger.error("Não foi possível inicializar fallback de voz: %s", error)
            self._tts_engine = None

    def _load_kokoro(self) -> bool:
        if not self._kokoro_available:
            return False
        if self._kokoro is not None:
            return True
        try:
            from kokoro_onnx import Kokoro

            self._kokoro = Kokoro(KOKORO_MODEL_PATH, KOKORO_VOICES_PATH)
            logger.info("Kokoro TTS carregado em CPU.")
            return True
        except Exception as error:
            logger.error("Falha ao carregar Kokoro: %s", error)
            self._kokoro_available = False
            self._init_fallback()
            return False

    @staticmethod
    def _chunks(text: str, max_chars: int = 360) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks, current = [], ""
        for sentence in sentences:
            if current and len(current) + len(sentence) + 1 > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current)
        return chunks or [text]

    def _cancelled(self, generation: int) -> bool:
        with self._gen_lock:
            return generation != self._generation

    def note_user_speech_ended(self) -> None:
        """Marca o fim da fala da pessoa, para medir até o primeiro áudio da resposta."""
        self._speech_ended_at = time.monotonic()
        self._marked_audio = False
        self.last_latency_ms = None

    def _mark_first_audio(self) -> None:
        if self._marked_audio or self._speech_ended_at is None:
            return
        self._marked_audio = True
        self.last_latency_ms = max(0, int((time.monotonic() - self._speech_ended_at) * 1000))

    def _play(self, samples, sample_rate: int, generation: int) -> bool:
        """Toca um pedaço. False significa que a fala foi cortada e não deve continuar."""
        if self._cancelled(generation):
            return False
        self._mark_first_audio()
        sd.play(np.asarray(samples, dtype=np.float32), sample_rate)
        sd.wait()
        if self._cancelled(generation):
            try:
                sd.stop()
            except Exception:
                pass
            return False
        return True

    def _speak_kokoro(self, text: str, generation: int) -> bool:
        if self._cancelled(generation) or not self._load_kokoro():
            return self._cancelled(generation)
        try:
            for chunk in self._chunks(text):
                if self._cancelled(generation):
                    return True
                samples, sample_rate = self._kokoro.create(
                    chunk,
                    voice=KOKORO_VOICE,
                    speed=KOKORO_SPEED,
                    lang=KOKORO_LANGUAGE,
                )
                if not self._play(samples, sample_rate, generation):
                    return True
            return True
        except Exception as error:
            logger.error("Falha no Kokoro TTS: %s", error)
            return self._cancelled(generation)

    def _speak_piper(self, text: str, generation: int) -> bool:
        if self._cancelled(generation):
            return True
        tmp_path = None
        proc = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            proc = subprocess.Popen(
                [PIPER_EXECUTABLE, "--model", PIPER_VOICE_MODEL, "--config", PIPER_VOICE_CONFIG,
                 "--output_file", tmp_path, "--length_scale", str(1.0 / TTS_SPEED)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            proc.stdin.write(text.encode("utf-8"))
            proc.stdin.close()
            while proc.poll() is None:
                if self._cancelled(generation):
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return True
                time.sleep(0.05)
            if proc.returncode != 0:
                logger.error("Piper retornou erro: %s", (proc.stderr.read() or b"").decode(errors="replace")[:300])
                return False
            if self._cancelled(generation):
                return True
            audio, sample_rate = sf.read(tmp_path, dtype="float32")
            return self._play(audio, sample_rate, generation)
        except Exception as error:
            logger.error("Falha no Piper TTS: %s", error)
            if proc is not None and proc.poll() is None:
                proc.kill()
            return self._cancelled(generation)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _speak_fallback(self, text: str, generation: int) -> None:
        if self._cancelled(generation) or self._tts_engine is None:
            if self._tts_engine is None and not self._cancelled(generation):
                logger.warning("Nenhum TTS local disponível.")
            return
        self._mark_first_audio()
        self._tts_engine.say(text)
        self._tts_engine.runAndWait()

    def speak(self, text: str, blocking: bool = True) -> None:
        clean = text.replace("*", "").replace("#", "").replace("_", " ").replace("`", "").strip()
        if not clean:
            return

        def run() -> None:
            from agent.core.inference_queue import INFERENCE_QUEUE
            event = threading.Event()
            with self._gen_lock:
                self._cancels.append(event)
                generation = self._generation
            self._playing.set()
            try:
                with INFERENCE_QUEUE.slot("local-gpu", cancel=event) as acquired:
                    if not acquired or self._cancelled(generation):
                        return
                    with self._lock:
                        if self._cancelled(generation):
                            return
                        if self._kokoro_available and self._speak_kokoro(clean, generation):
                            return
                        if self._piper_available and self._speak_piper(clean, generation):
                            return
                        self._speak_fallback(clean, generation)
            finally:
                with self._gen_lock:
                    if event in self._cancels:
                        self._cancels.remove(event)
                self._playing.clear()

        if blocking:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

    def quiet_for_listen(self, timeout: float = 2.0) -> None:
        """Corta a fala atual e espera ela sair, antes de abrir o microfone.

        Assim a voz do próprio Órbita não entra como um comando novo.
        """
        self.stop()
        deadline = time.monotonic() + max(0.0, timeout)
        while self._playing.is_set() and time.monotonic() < deadline:
            time.sleep(0.02)

    def play_beep(self, frequency: float = 440.0, duration: float = 0.2, volume: float = 0.25) -> None:
        try:
            sample_rate = 44100
            time_axis = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
            wave = np.sin(2 * np.pi * frequency * time_axis) * volume
            sd.play(wave.astype(np.float32), sample_rate)
            sd.wait()
        except Exception as error:
            logger.debug("Falha no bipe: %s", error)

    def stop(self) -> None:
        """Corta o pedaço atual e impede os próximos. Não espera o cadeado da fala."""
        with self._gen_lock:
            self._generation += 1
            events = list(self._cancels)
        for event in events:
            event.set()
        try:
            sd.stop()
        except Exception:
            pass
        engine = self._tts_engine
        if engine is not None:
            try:
                engine.stop()
            except Exception:
                pass
