"""
dictation.py — Ditado: fala vira texto no campo de mensagem, enquanto a pessoa fala.

Um clique no microfone começa a gravar; outro clique termina (Esc cancela). A cada ~1 s o áudio
acumulado é transcrito rapidamente e o texto parcial aparece no campo; no fim, uma transcrição
completa (mais precisa, com pontuação) substitui o parcial. Nada é enviado sozinho.

Dois motores, escolhidos em gui.py:
- nuvem (Groq ou OpenAI, com a chave já configurada): como no ChatGPT/Claude — o PC só grava e envia,
  então funciona igual em computador fraco;
- neste PC (Whisper): leve por padrão (tiny no parcial, base no final). GPU (CUDA) só se a pessoa
  instalar as bibliotecas pelo botão opcional; senão, CPU. O modelo é liberado após minutos parado.

Roda nas próprias threads, então funciona mesmo com o agente trabalhando.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

from agent.core.config import STT_LANGUAGE, STT_MODEL_DIR, STT_SAMPLE_RATE

logger = logging.getLogger(__name__)

MAX_SECONDS = 180          # trava de segurança
AUTO_STOP_SILENCE = 8.0    # depois de já ter falado, tantos segundos calado encerram sozinho
PARTIAL_EVERY = 1.0
PARTIAL_EVERY_CLOUD = 1.5  # na nuvem cada parcial é uma chamada de API
PARTIAL_MAX_SECONDS = 30   # o parcial cobre os primeiros 30 s; o texto completo vem no fim
PARTIAL_MODEL_CPU = "tiny" # na CPU o parcial usa o modelo mínimo (~75 MB, ~0,5 s); o final usa o escolhido
DEFAULT_LOCAL_MODEL = "base"   # leve (~150 MB): funciona em PC fraco; maiores são opcionais
# Transcrição na nuvem (como no ChatGPT/Claude): rápida em qualquer PC, usa a chave já configurada.
CLOUD_MODELS = {"groq": "whisper-large-v3-turbo", "openai": "gpt-4o-mini-transcribe"}
SPEECH_RMS = 0.012         # volume que conta como fala
IDLE_UNLOAD = 600          # libera o modelo depois de 10 min sem uso
PROMPT = "Transcrição em português do Brasil, com pontuação correta."

Push = Callable[[dict], None]


def add_cuda_dlls() -> bool:
    """Bibliotecas CUDA instaladas pelo pip (nvidia-cublas-cu12/nvidia-cudnn-cu12) entram no caminho de DLLs."""
    found = False
    try:
        import nvidia
        roots = list(getattr(nvidia, "__path__", []))
    except ImportError:
        return False
    for root in roots:
        for lib in ("cublas", "cudnn", "cuda_runtime"):
            for sub in ("bin", "lib"):
                folder = os.path.join(root, lib, sub)
                if os.path.isdir(folder):
                    found = True
                    if hasattr(os, "add_dll_directory"):
                        os.add_dll_directory(folder)
                    os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
    return found


class _Whisper:
    """Carrega os modelos (GPU se der, senão CPU) e os mantém enquanto estiverem em uso."""

    def __init__(self):
        self._models: dict[tuple, object] = {}
        self._lock = threading.Lock()
        self._cpu_only = False
        self._dlls = False
        self._last_use = 0.0
        self._timer: Optional[threading.Timer] = None

    def gpu(self) -> bool:
        if self._cpu_only:
            return False
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() <= 0:
                return False
        except Exception:
            return False
        if not self._dlls:
            self._dlls = True
            add_cuda_dlls()
        return True

    def get(self, size: str):
        with self._lock:
            device = "cuda" if self.gpu() else "cpu"
            key = (size, device)
            if key not in self._models:
                os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
                from faster_whisper import WhisperModel
                compute = "float16" if device == "cuda" else "int8"
                logger.info("Carregando Whisper %s (%s/%s)", size, device, compute)
                self._models[key] = WhisperModel(size, device=device, compute_type=compute,
                                                 download_root=str(STT_MODEL_DIR))
            self._last_use = time.time()
            self._schedule_unload()
            return self._models[key]

    def warm(self, size: str) -> None:
        """Primeira inferência na GPU inicializa a placa (vários segundos): faz isso enquanto a pessoa começa a falar."""
        model = self.get(size)
        key = (size, self.device_of(size))
        if key in getattr(self, "_warm", set()):
            return
        import numpy as np
        list(model.transcribe(np.zeros(STT_SAMPLE_RATE // 2, dtype="float32"), language=STT_LANGUAGE, beam_size=1)[0])
        self._warm = getattr(self, "_warm", set()) | {key}

    def device_of(self, size: str) -> str:
        return "cuda" if (size, "cuda") in self._models and not self._cpu_only else "cpu"

    def fall_back_to_cpu(self) -> None:
        """CUDA presente mas sem cuBLAS/cuDNN: o erro só aparece na primeira transcrição."""
        with self._lock:
            self._cpu_only = True
            self._models = {k: m for k, m in self._models.items() if k[1] == "cpu"}

    def _schedule_unload(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(IDLE_UNLOAD, self._unload_if_idle)
        self._timer.daemon = True
        self._timer.start()

    def _unload_if_idle(self) -> None:
        with self._lock:
            if time.time() - self._last_use >= IDLE_UNLOAD - 1:
                self._models.clear()
                logger.info("Whisper liberado da memória (sem uso).")

    def partial_size(self, size: str) -> str:
        """Na GPU o próprio modelo escolhido é rápido; na CPU o parcial usa um modelo leve."""
        return size if self.gpu() else PARTIAL_MODEL_CPU

    def transcribe(self, size: str, audio, final: bool) -> str:
        for attempt in range(2):
            model = self.get(size)
            on_gpu = not self._cpu_only and (size, "cuda") in self._models
            try:
                segments, _ = model.transcribe(audio, language=STT_LANGUAGE, beam_size=5 if final else 1,
                                               vad_filter=final, initial_prompt=PROMPT,
                                               condition_on_previous_text=False)
                return " ".join(s.text.strip() for s in segments).strip()
            except RuntimeError as error:
                if attempt == 0 and on_gpu:
                    logger.warning("Whisper na GPU falhou (%s); usando CPU.", error)
                    self.fall_back_to_cpu()
                    continue
                raise
        return ""


WHISPER = _Whisper()


def wav_bytes(audio) -> bytes:
    """float32 mono 16 kHz → WAV PCM 16 bits (o que as APIs de transcrição aceitam)."""
    import io
    import wave

    import numpy as np
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(STT_SAMPLE_RATE)
        out.writeframes(pcm)
    return buffer.getvalue()


def cloud_transcribe(engine: dict, audio, timeout: float = 30) -> str:
    """POST /audio/transcriptions (padrão OpenAI, também na Groq)."""
    import httpx
    response = httpx.post(
        engine["base_url"].rstrip("/") + "/audio/transcriptions",
        headers={"Authorization": f"Bearer {engine['key']}"},
        files={"file": ("fala.wav", wav_bytes(audio), "audio/wav")},
        data={"model": engine["model"], "language": STT_LANGUAGE, "response_format": "json", "prompt": PROMPT},
        timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"{engine['label']} recusou a transcrição (HTTP {response.status_code}): "
                           f"{response.text[:200]}")
    return (response.json().get("text") or "").strip()


class Dictation:
    """`engine()` devolve {"kind": "cloud", ...} ou {"kind": "local", "size": ...} (escolhido em gui.py)."""

    def __init__(self, push: Push, engine: Callable[[], dict]):
        self.push = push
        self.engine = engine
        self._lock = threading.Lock()
        self._frames: list = []
        self._active = False
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> Optional[str]:
        with self._lock:
            if self._active:
                return "O ditado já está gravando."
            self._active = True
            self._frames = []
            self._stop.clear()
            self._cancel.clear()
        self._thread = threading.Thread(target=self._run, name="ditado", daemon=True)
        self._thread.start()
        return None

    def stop(self) -> None:
        self._stop.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._stop.set()

    def _audio(self):
        import numpy as np
        with self._lock:
            return np.concatenate(self._frames) if self._frames else np.zeros(0, dtype="float32")

    def _run(self) -> None:
        try:
            self._record()
        except Exception as error:   # microfone ausente, driver, modelo...
            logger.exception("Ditado falhou")
            self.push({"type": "dictation", "state": "error", "message": _friendly(error)})
        finally:
            self._active = False

    def _record(self) -> None:
        import numpy as np
        import sounddevice as sd

        engine = self.engine() or {"kind": "local"}
        cloud = engine.get("kind") == "cloud"
        size = engine.get("size") or DEFAULT_LOCAL_MODEL
        state = {"spoke": False, "silence": 0.0, "level_at": 0.0}
        block = int(STT_SAMPLE_RATE * 0.1)

        def callback(indata, frames, time_info, status):
            chunk = indata[:, 0].copy()
            rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) else 0.0
            with self._lock:
                self._frames.append(chunk)
            if rms >= SPEECH_RMS:
                state["spoke"], state["silence"] = True, 0.0
            elif state["spoke"]:
                state["silence"] += len(chunk) / STT_SAMPLE_RATE
            now = time.time()
            if now - state["level_at"] >= 0.08:
                state["level_at"] = now
                self.push({"type": "dictation", "state": "level", "level": round(min(1.0, rms * 12), 3)})

        # Local: os modelos carregam em paralelo à gravação, para estarem prontos quando a pessoa terminar.
        # Nuvem: nada para carregar — o PC só grava e envia (funciona em computador fraco).
        quick = WHISPER.partial_size(size)
        loader = threading.Thread(target=lambda: None if cloud else _safe(lambda: WHISPER.warm(quick)), daemon=True)
        final_loader = threading.Thread(target=lambda: _safe(lambda: WHISPER.warm(size)), daemon=True)
        loader.start()
        if not cloud and size != quick:
            final_loader.start()   # o modelo preciso carrega em paralelo, só para o texto final
        every = PARTIAL_EVERY_CLOUD if cloud else PARTIAL_EVERY

        def partial(audio):
            if cloud:
                return cloud_transcribe(engine, audio, timeout=10)
            return WHISPER.transcribe(WHISPER.partial_size(size), audio, final=False)   # muda se a GPU falhar

        started = time.time()
        with sd.InputStream(samplerate=STT_SAMPLE_RATE, channels=1, dtype="float32", blocksize=block, callback=callback):
            self.push({"type": "dictation", "state": "recording", "engine": engine.get("label", "")})
            last_partial, last_text = 0.0, ""
            while not self._stop.is_set():
                time.sleep(0.05)
                elapsed = time.time() - started
                if elapsed >= MAX_SECONDS or (state["spoke"] and state["silence"] >= AUTO_STOP_SILENCE):
                    break
                if state["spoke"] and time.time() - last_partial >= every and not loader.is_alive():
                    audio = self._audio()[: PARTIAL_MAX_SECONDS * STT_SAMPLE_RATE]
                    text = _safe(lambda: partial(audio)) or ""
                    last_partial = time.time()
                    if text and text != last_text:
                        last_text = text
                        self.push({"type": "dictation", "state": "partial", "text": text})
        if self._cancel.is_set():
            self.push({"type": "dictation", "state": "cancelled"})
            return
        audio = self._audio()
        if not state["spoke"] or len(audio) < STT_SAMPLE_RATE * 0.3:
            self.push({"type": "dictation", "state": "done", "text": "",
                       "message": "Não ouvi nada. Confira o microfone em Configurações › Voz."})
            return
        self.push({"type": "dictation", "state": "finishing"})
        if cloud:
            try:
                text = cloud_transcribe(engine, audio, timeout=60)
            except Exception as error:
                if not last_text:
                    raise
                # Sem internet ou chave recusada no fim: fica o último parcial, com aviso.
                self.push({"type": "dictation", "state": "done", "text": last_text,
                           "message": f"A transcrição final falhou ({error}); ficou o texto parcial."})
                return
        else:
            loader.join()
            if final_loader.is_alive():
                final_loader.join()
            text = WHISPER.transcribe(size, audio, final=True)
        self.push({"type": "dictation", "state": "done", "text": text})


def _safe(fn):
    try:
        return fn()
    except Exception as error:
        logger.warning("Ditado: %s", error)
        return None


def _friendly(error: Exception) -> str:
    text = str(error)
    if "PortAudio" in text or "device" in text.lower() or "Invalid" in text:
        return f"Não consegui abrir o microfone ({text}). Confira se ele está conectado e liberado para apps."
    return f"O ditado falhou: {text}"
