"""
config.py — Configurações centralizadas do AgentePessoal
Edite este arquivo para personalizar o comportamento do agente.
"""

import os
from pathlib import Path

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

# Raiz do projeto (pasta AgentePessoal)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Variáveis do .env (chaves de API, LLM_MODEL, LOG_LEVEL...) valem para todo o programa.
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

MODELS_DIR     = PROJECT_ROOT / "models"
DATA_DIR       = PROJECT_ROOT / "data"
LOGS_DIR       = DATA_DIR / "logs"
USER_PROFILE   = DATA_DIR / "user_profile" / "profile.json"
DAILY_LOGS_DIR = PROJECT_ROOT / "agent" / "memory" / "daily_logs"
LONG_TERM_DIR  = PROJECT_ROOT / "agent" / "memory" / "long_term"
TTS_MODEL_DIR  = MODELS_DIR / "tts"
STT_MODEL_DIR  = MODELS_DIR / "stt"

# ─────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────

# Modelo local padrão (Ollama). Provedores, chaves, perfis e prompts de injeção ficam em
# data/settings.json e data/profiles/ — editáveis pela interface (ver settings.py/profiles.py).
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:14b")

# ─────────────────────────────────────────────
# STT — Reconhecimento de Voz (faster-whisper)
# ─────────────────────────────────────────────

# Tamanho do modelo Whisper: tiny | base | small | medium | large-v3
# Recomendado: "small" para equilíbrio velocidade/precisão
STT_MODEL_SIZE = "small"

# Idioma forçado (None = autodetecção)
STT_LANGUAGE = "pt"

# Dispositivo de computação: "cpu" ou "cuda" (GPU NVIDIA)
STT_DEVICE = "cpu"

# Tipo de quantização: "int8" (mais rápido), "float16", "float32"
STT_COMPUTE_TYPE = "int8"

# Duração máxima da gravação em segundos
STT_MAX_RECORD_SECONDS = 30

# Silêncio mínimo para encerrar a captura após a fala (segundos)
STT_SILENCE_THRESHOLD = 1.8

# Tempo máximo aguardando a pessoa começar a falar (segundos)
STT_NO_SPEECH_TIMEOUT = 5.0

# Volume mínimo para considerar que existe fala
STT_SILENCE_RMS_LIMIT = 300

# Detector de atividade de voz executado em CPU. Ele é usado apenas enquanto
# o botão do microfone estiver em captura e reduz falsos disparos por ruído.
STT_USE_SILERO_VAD = True
STT_VAD_SPEECH_THRESHOLD = 0.5

# Tempo mínimo de fala antes de aceitar silêncio para encerrar
STT_MIN_SPEECH_DURATION = 0.4

# Parâmetro de VAD interno do Whisper (milissegundos)
STT_VAD_MIN_SILENCE_MS = 700

# Descarrega o modelo Whisper após cada uso para poupar RAM/VRAM
STT_KEEP_MODEL_LOADED = False

# Taxa de amostragem do microfone
STT_SAMPLE_RATE = 16000

# ─────────────────────────────────────────────
# TTS — Síntese de Voz (piper-tts)
# ─────────────────────────────────────────────

# Caminho para o executável do piper
PIPER_EXECUTABLE = str(TTS_MODEL_DIR / "piper" / "piper.exe")

# Modelo Piper opcional. A GUI usa a voz feminina do Windows por padrão para
# garantir uma voz feminina em PT-BR sem depender de classificação do modelo.
# Vozes PT-BR disponíveis em: https://huggingface.co/rhasspy/piper-voices
PIPER_VOICE_MODEL = str(TTS_MODEL_DIR / "dii_pt-BR.onnx")
PIPER_VOICE_CONFIG = str(TTS_MODEL_DIR / "dii_pt-BR.onnx.json")

# Velocidade da fala (0.5 = lento, 1.0 = normal, 1.5 = rápido)
TTS_SPEED = 1.0

# "kokoro" usa a voz neural local; os demais servem como fallback.
TTS_ENGINE = "kokoro"

# Kokoro 82M ONNX: voz feminina brasileira local, sem uso de GPU.
KOKORO_MODEL_PATH = str(TTS_MODEL_DIR / "kokoro" / "kokoro-v1.0.onnx")
KOKORO_VOICES_PATH = str(TTS_MODEL_DIR / "kokoro" / "voices-v1.0.bin")
KOKORO_VOICE = "pf_dora"
KOKORO_LANGUAGE = "pt-br"
KOKORO_SPEED = 1.0

# Preferência de fallback do TTS do sistema
TTS_FALLBACK_PREFERRED_GENDER = "female"
TTS_SYSTEM_VOICE_NAME = "Microsoft Maria"

# ─────────────────────────────────────────────
# GUI — Clique para falar
# ─────────────────────────────────────────────

# No modo GUI, o microfone funciona por clique e encerra ao detectar
# alguns segundos de silêncio.
# Depois que a fala começa, aguarda 5 segundos de silêncio antes de enviar.
# O microfone só é aberto por um clique no botão da GUI.
GUI_VOICE_SILENCE_SECONDS = 5.0
GUI_VOICE_NO_SPEECH_TIMEOUT = 5.0
GUI_VOICE_MAX_RECORD_SECONDS = 30

# ─────────────────────────────────────────────
# WAKE WORD / ATIVAÇÃO
# ─────────────────────────────────────────────

# Tecla de atalho para ativar o agente (modo push-to-talk)
# Exemplos: "ctrl+space", "f9", "ctrl+alt+a"
HOTKEY_ACTIVATE = "ctrl+space"

# Modo padrão ao rodar main.py sem argumentos: "gui", "text" ou "voice"
INPUT_MODE = "gui"

# ─────────────────────────────────────────────
# MEMÓRIA
# ─────────────────────────────────────────────

# Número máximo de entradas no log diário antes de compactar
DAILY_LOG_MAX_ENTRIES = 200


# ─────────────────────────────────────────────
# WEB SEARCH
# ─────────────────────────────────────────────

# Número máximo de resultados retornados por busca
WEB_SEARCH_MAX_RESULTS = 8
WEB_SEARCH_BACKEND = "auto"
WEB_RESEARCH_MAX_SITES = 3
WEB_RESEARCH_MAX_CHARS_PER_SITE = 3500
WEB_RESEARCH_TIMEOUT_SECONDS = 7

# ─────────────────────────────────────────────
# LOGS
# ─────────────────────────────────────────────

# Nível de log: DEBUG | INFO | WARNING | ERROR
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

# Arquivo de log técnico
LOG_FILE = str(LOGS_DIR / "agent.log")
