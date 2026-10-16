"""Síntese de voz local com Kokoro ONNX e fallbacks offline."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import threading

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

    def _speak_kokoro(self, text: str) -> bool:
        if not self._load_kokoro():
            return False
        try:
            for chunk in self._chunks(text):
                samples, sample_rate = self._kokoro.create(
                    chunk,
                    voice=KOKORO_VOICE,
                    speed=KOKORO_SPEED,
                    lang=KOKORO_LANGUAGE,
                )
                sd.play(np.asarray(samples, dtype=np.float32), sample_rate)
                sd.wait()
            return True
        except Exception as error:
            logger.error("Falha no Kokoro TTS: %s", error)
            return False

    def _speak_piper(self, text: str) -> bool:
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            result = subprocess.run(
                [PIPER_EXECUTABLE, "--model", PIPER_VOICE_MODEL, "--config", PIPER_VOICE_CONFIG,
                 "--output_file", tmp_path, "--length_scale", str(1.0 / TTS_SPEED)],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error("Piper retornou erro: %s", result.stderr.decode(errors="replace"))
                return False
            audio, sample_rate = sf.read(tmp_path, dtype="float32")
            sd.play(audio, sample_rate)
            sd.wait()
            return True
        except Exception as error:
            logger.error("Falha no Piper TTS: %s", error)
            return False
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _speak_fallback(self, text: str) -> None:
        if self._tts_engine is None:
            logger.warning("Nenhum TTS local disponível.")
            return
        self._tts_engine.say(text)
        self._tts_engine.runAndWait()

    def speak(self, text: str, blocking: bool = True) -> None:
        clean = text.replace("*", "").replace("#", "").replace("_", " ").replace("`", "").strip()
        if not clean:
            return

        def run() -> None:
            with self._lock:
                if self._kokoro_available and self._speak_kokoro(clean):
                    return
                if self._piper_available and self._speak_piper(clean):
                    return
                self._speak_fallback(clean)

        if blocking:
            run()
        else:
            threading.Thread(target=run, daemon=True).start()

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
        try:
            sd.stop()
        except Exception:
            pass
