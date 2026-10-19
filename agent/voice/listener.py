"""
listener.py — Captura e transcreve áudio do microfone usando faster-whisper.
Inclui detecção automática de silêncio para parar a gravação.
"""

import gc
import logging
import os
import threading
import time
import numpy as np
import sounddevice as sd

# Suprime aviso de token do HuggingFace Hub (não necessário para uso offline)
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

from faster_whisper import WhisperModel


from agent.core.config import (
    STT_MODEL_SIZE, STT_LANGUAGE, STT_DEVICE,
    STT_COMPUTE_TYPE, STT_SAMPLE_RATE,
    STT_MAX_RECORD_SECONDS, STT_SILENCE_THRESHOLD,
    STT_MODEL_DIR, STT_NO_SPEECH_TIMEOUT,
    STT_SILENCE_RMS_LIMIT, STT_MIN_SPEECH_DURATION,
    STT_VAD_MIN_SILENCE_MS, STT_KEEP_MODEL_LOADED,
    STT_USE_SILERO_VAD, STT_VAD_SPEECH_THRESHOLD,
)

logger = logging.getLogger(__name__)


class Listener:
    """
    Captura áudio do microfone e transcreve para texto usando faster-whisper.
    Detecta automaticamente quando o usuário parou de falar.
    """

    def __init__(self):
        self._model: WhisperModel | None = None
        self._model_lock = threading.Lock()
        self._vad_model = None
        self._vad_lock = threading.Lock()
        self._cancel_recording = threading.Event()
        self._loading = False
        logger.info("Listener criado. Modelo será carregado na primeira chamada.")

    def _load_vad(self) -> bool:
        """Carrega o VAD ONNX em CPU somente quando uma captura for iniciada."""
        if not STT_USE_SILERO_VAD:
            return False
        if self._vad_model is not None:
            return True

        with self._vad_lock:
            if self._vad_model is not None:
                return True
            try:
                import torch
                from silero_vad import load_silero_vad

                torch.set_num_threads(1)
                self._vad_model = load_silero_vad(onnx=True)
                logger.info("Silero VAD carregado em CPU.")
                return True
            except Exception as e:
                logger.warning(f"Silero VAD indisponível; usando detecção por volume: {e}")
                return False

    def _is_speech(self, audio_chunk: np.ndarray) -> bool:
        """Classifica um chunk de áudio com Silero VAD; usa RMS como fallback."""
        if self._vad_model is not None:
            try:
                import torch

                # O modelo Silero 16 kHz recebe janelas de 512 amostras.
                for start in range(0, len(audio_chunk), 512):
                    window = audio_chunk[start:start + 512]
                    if len(window) < 512:
                        window = np.pad(window, (0, 512 - len(window)))
                    probability = self._vad_model(torch.from_numpy(window), STT_SAMPLE_RATE).item()
                    if probability >= STT_VAD_SPEECH_THRESHOLD:
                        return True
                return False
            except Exception as e:
                logger.warning(f"Falha durante classificação Silero VAD: {e}")

        rms = np.sqrt(np.mean(audio_chunk ** 2)) * 32768
        return rms >= STT_SILENCE_RMS_LIMIT

    def _load_model(self):
        """Carrega o modelo Whisper (lazy loading para não atrasar a inicialização)."""
        if self._model is not None:
            return

        with self._model_lock:
            if self._model is not None:
                return

            logger.info(f"Carregando modelo Whisper '{STT_MODEL_SIZE}'...")
            try:
                self._model = WhisperModel(
                    STT_MODEL_SIZE,
                    device=STT_DEVICE,
                    compute_type=STT_COMPUTE_TYPE,
                    download_root=str(STT_MODEL_DIR),
                )
                logger.info("Modelo Whisper carregado com sucesso.")
            except Exception as e:
                logger.error(f"Erro ao carregar modelo Whisper: {e}")
                raise

    def unload_model(self):
        """Libera o modelo da memória quando ele não precisa ficar residente."""
        with self._model_lock:
            if self._model is None:
                return

            logger.info("Descarregando modelo Whisper da memória.")
            self._model = None

        gc.collect()

        if STT_DEVICE == "cuda":
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass

    def cancel_recording(self) -> None:
        """Solicita o fim imediato da captura atual, se houver uma."""
        self._cancel_recording.set()

    def record(
        self,
        max_seconds: float = None,
        silence_threshold: float = None,
        no_speech_timeout: float = None,
        silence_rms_limit: int = None,
        min_speech_duration: float = None,
    ) -> np.ndarray:
        """
        Grava áudio do microfone com detecção de silêncio automática.

        Args:
            max_seconds: Duração máxima em segundos.

        Returns:
            Array numpy com os dados de áudio.
        """
        max_seconds = max_seconds or STT_MAX_RECORD_SECONDS
        silence_threshold = silence_threshold or STT_SILENCE_THRESHOLD
        no_speech_timeout = no_speech_timeout or STT_NO_SPEECH_TIMEOUT
        silence_rms_limit = silence_rms_limit or STT_SILENCE_RMS_LIMIT
        min_speech_duration = min_speech_duration or STT_MIN_SPEECH_DURATION
        self._cancel_recording.clear()
        vad_available = self._load_vad()
        if vad_available:
            self._vad_model.reset_states()

        # Parâmetros de gravação
        chunk_duration = 0.1       # segundos por chunk
        chunk_samples = int(STT_SAMPLE_RATE * chunk_duration)

        frames = []
        silence_duration = 0.0
        no_speech_duration = 0.0
        speech_duration = 0.0
        detected_speech = False
        recording = True

        def audio_callback(indata, frame_count, time_info, status):
            nonlocal silence_duration, no_speech_duration, speech_duration
            nonlocal detected_speech, recording

            if not recording or self._cancel_recording.is_set():
                recording = False
                return

            audio_chunk = indata[:, 0].copy()  # canal mono
            frames.append(audio_chunk)

            is_speech = self._is_speech(audio_chunk)
            if not is_speech:
                if detected_speech:
                    silence_duration += chunk_duration
                else:
                    no_speech_duration += chunk_duration
            else:
                detected_speech = True
                silence_duration = 0.0
                speech_duration += chunk_duration

            if not detected_speech and no_speech_duration >= no_speech_timeout:
                recording = False
                return

            # Para se houver silêncio após fala suficiente
            if (speech_duration >= min_speech_duration and
                    silence_duration >= silence_threshold):
                recording = False

        try:
            with sd.InputStream(
                samplerate=STT_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=chunk_samples,
                callback=audio_callback,
            ):
                start = time.time()
                while recording and not self._cancel_recording.is_set() and (time.time() - start) < max_seconds:
                    time.sleep(0.05)

        except Exception as e:
            logger.error(f"Erro na captura de áudio: {e}")
            return np.array([])

        if self._cancel_recording.is_set() or not frames:
            return np.array([])

        if not detected_speech or speech_duration < min_speech_duration:
            logger.info("Nenhuma fala válida detectada durante a captura.")
            return np.array([])

        audio = np.concatenate(frames, axis=0)
        logger.debug(f"Gravação finalizada: {len(audio)/STT_SAMPLE_RATE:.1f}s")
        return audio

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Transcreve um array de áudio para texto.

        Args:
            audio: Array numpy com dados de áudio (float32, 16kHz).

        Returns:
            Texto transcrito.
        """
        if audio is None or len(audio) == 0:
            return ""

        self._load_model()

        try:
            from agent.core.inference_queue import INFERENCE_QUEUE
            with INFERENCE_QUEUE.slot("local-gpu") as acquired:
                if not acquired:
                    return ""
                segments, info = self._model.transcribe(
                    audio,
                    language=STT_LANGUAGE,
                    beam_size=5,
                    vad_filter=True,          # filtra silêncio automaticamente
                    vad_parameters={
                        "min_silence_duration_ms": STT_VAD_MIN_SILENCE_MS,
                        "speech_pad_ms": 200,
                    },
                )

            text = " ".join(seg.text.strip() for seg in segments)
            logger.debug(f"Transcrição: '{text}'")
            return text.strip()

        except Exception as e:
            logger.error(f"Erro na transcrição: {e}")
            return ""

    def listen(
        self,
        max_seconds: float = None,
        silence_threshold: float = None,
        no_speech_timeout: float = None,
    ) -> str:
        """
        Grava o microfone e retorna o texto transcrito.
        Método principal para uso no brain.py.

        Returns:
            Texto transcrito do que foi falado.
        """
        logger.info("Iniciando captura de voz...")
        try:
            audio = self.record(
                max_seconds=max_seconds,
                silence_threshold=silence_threshold,
                no_speech_timeout=no_speech_timeout,
            )

            if len(audio) == 0:
                logger.warning("Nenhum áudio capturado.")
                return ""

            text = self.transcribe(audio)
            return text
        finally:
            if not STT_KEEP_MODEL_LOADED:
                self.unload_model()
