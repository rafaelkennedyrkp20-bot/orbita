"""
main.py — Ponto de entrada do Órbita.
Liga todos os módulos e inicia o agente no modo escolhido.
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

# Evita falha do console Windows ao imprimir mensagens em português e símbolos.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Garante que o projeto está no path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.core.config import LOG_LEVEL, LOG_FILE, INPUT_MODE
from agent.core.brain import Brain


def setup_logging():
    """Configura o sistema de logging."""
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

    # Cria pasta de logs se não existir
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")]
        + ([logging.StreamHandler(sys.stdout)] if sys.stdout is not None else []),  # pythonw: sem console
    )

    # Silencia logs muito verbosos de libs externas
    for noisy in ["httpx", "httpcore", "urllib3", "faster_whisper"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Analisa os argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description="Órbita — seu agente pessoal de IA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modos de execução:
  python agent/main.py                        → interface gráfica (padrão)
  python agent/main.py --text                 → modo texto (terminal)
  python agent/main.py --voice                → modo voz (microfone + atalho)
  python agent/main.py --check                → verifica dependências, provedores e MCP
  python agent/main.py --text --model deepseek:deepseek-chat --profile programador
        """,
    )
    parser.add_argument("--text", action="store_true", help="Forçar modo texto")
    parser.add_argument("--voice", action="store_true", help="Forçar modo voz")
    parser.add_argument("--gui", action="store_true", help="Forçar modo interface gráfica")
    parser.add_argument("--check", action="store_true", help="Verificar configurações")
    parser.add_argument("--model", type=str, help="provedor:modelo (ex: deepseek:deepseek-chat)")
    parser.add_argument("--profile", type=str, help="Perfil a usar (ex: programador)")
    return parser.parse_args()


def run_health_check():
    """Verifica se todas as dependências estão ok."""
    print("\n" + "═" * 60)
    print("  Órbita — Verificação de Saúde")
    print("═" * 60)

    checks = []

    # 1. Provedores de IA
    from agent.core.providers import get_provider
    from agent.core.settings import Settings

    settings = Settings()
    for name, cfg in settings.providers().items():
        if name == "ollama":
            models = get_provider(name, settings).list_models()
            ok = bool(models) and models != cfg.get("models")
            print(f"{'✅' if ok else '❌'} Ollama: {'modelos: ' + ', '.join(models) if ok else 'servidor não respondeu'}")
            checks.append(ok)
        elif cfg.get("type") == "grok_cli":
            from agent.core import grok_cli

            info = grok_cli.status()
            state = "conectado" if info["logged_in"] else ("instalado, sem login" if info["installed"] else "não instalado")
            print(f"{'✅' if info['logged_in'] else 'ℹ️ '} Grok Build (conta xAI): {state} {info['version']}")
        elif cfg.get("api_key_env") and settings.has_credentials(name):
            print(f"✅ {cfg['label']}: chave {cfg['api_key_env']} configurada.")

    # 2. faster-whisper
    try:
        import faster_whisper
        print("✅ faster-whisper: instalado.")
        checks.append(True)
    except ImportError:
        print("❌ faster-whisper: não instalado.")
        print("   → pip install faster-whisper")
        checks.append(False)

    # 3. Silero VAD
    try:
        import torch
        from silero_vad import load_silero_vad
        load_silero_vad(onnx=True)
        device = "CUDA" if torch.cuda.is_available() else "CPU"
        print(f"✅ Silero VAD: instalado ({device}).")
        checks.append(True)
    except Exception as e:
        print(f"❌ Silero VAD: erro ({e})")
        checks.append(False)

    # 4. sounddevice
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_count = sum(1 for d in devices if d["max_input_channels"] > 0)
        print(f"✅ sounddevice: {input_count} dispositivos de entrada encontrados.")
        checks.append(True)
    except Exception as e:
        print(f"❌ sounddevice: erro ({e})")
        checks.append(False)

    # 5. keyboard
    try:
        import keyboard
        print("✅ keyboard: instalado.")
        checks.append(True)
    except ImportError:
        print("❌ keyboard: não instalado.")
        print("   → pip install keyboard")
        checks.append(False)

    # 6. Busca web
    try:
        from ddgs import DDGS
        print("✅ ddgs: busca web instalada.")
        checks.append(True)
    except ImportError:
        print("❌ ddgs: busca web não instalada.")
        print("   → pip install ddgs")
        checks.append(False)

    # 7. Leitura de páginas da web
    try:
        import bs4
        print("✅ Leitura de páginas: BeautifulSoup instalado.")
        checks.append(True)
    except ImportError:
        print("❌ Leitura de páginas: BeautifulSoup não instalado.")
        checks.append(False)

    # 8. pyautogui
    try:
        import pyautogui
        size = pyautogui.size()
        print(f"✅ pyautogui: tela {size[0]}x{size[1]}px detectada.")
        checks.append(True)
    except Exception as e:
        print(f"❌ pyautogui: erro ({e})")
        checks.append(False)

    # 9. TTS
    from agent.core.config import (
        KOKORO_MODEL_PATH,
        KOKORO_VOICE,
        KOKORO_VOICES_PATH,
        PIPER_EXECUTABLE,
        PIPER_VOICE_MODEL,
        TTS_ENGINE,
        TTS_SYSTEM_VOICE_NAME,
    )
    import os
    if TTS_ENGINE.lower() == "kokoro":
        try:
            from kokoro_onnx import Kokoro
            if not (os.path.isfile(KOKORO_MODEL_PATH) and os.path.isfile(KOKORO_VOICES_PATH)):
                raise RuntimeError("arquivos do modelo ou vozes não encontrados")
            Kokoro(KOKORO_MODEL_PATH, KOKORO_VOICES_PATH)
            print(f"✅ Kokoro TTS: voz neural local {KOKORO_VOICE} pronta.")
            checks.append(True)
        except Exception as e:
            print(f"❌ Kokoro TTS: erro ({e})")
            checks.append(False)
    elif TTS_ENGINE.lower() == "system":
        try:
            from agent.voice.speaker import Speaker
            speaker = Speaker()
            selected_voice = speaker._tts_engine.getProperty("voice") if speaker._tts_engine else ""
            if selected_voice:
                print(f"✅ TTS Windows: voz feminina configurada ({TTS_SYSTEM_VOICE_NAME}).")
                checks.append(True)
            else:
                raise RuntimeError("Nenhuma voz do sistema disponível")
        except Exception as e:
            print(f"❌ TTS Windows: erro ({e})")
            checks.append(False)
    elif os.path.isfile(PIPER_EXECUTABLE) and os.path.isfile(PIPER_VOICE_MODEL):
        print("✅ Piper TTS: executável e modelo encontrados.")
        checks.append(True)
    else:
        print("⚠️  Piper TTS: não encontrado (usando fallback pyttsx3).")
        print(f"   → Esperado em: {PIPER_EXECUTABLE}")
        print("   → Baixe em: https://github.com/rhasspy/piper/releases")
        checks.append(True)  # Não bloqueante (tem fallback)

    # 10. MCP e skills
    try:
        from agent.core.mcp_hub import MCPHub
        from agent.core.skills import SkillManager
        from agent.core.tools import ToolRegistry

        servers = MCPHub(ToolRegistry()).load_config()
        enabled = [n for n, c in servers.items() if c.get("enabled", True)]
        print(f"✅ MCP: servidores ativos: {', '.join(enabled) or 'nenhum'}")
        print(f"✅ Skills: {len(SkillManager().skills)} encontradas")
        checks.append(True)
    except Exception as e:
        print(f"❌ MCP: erro ({e}) → pip install mcp")
        checks.append(False)
    if not shutil.which("npx"):
        print("⚠️  Node.js/npx não encontrado: servidores MCP via npx (como o REA) não vão iniciar.")

    print("\n" + "─" * 60)
    ok = sum(checks)
    total = len(checks)
    if ok == total:
        print(f"🎉 Tudo OK! ({ok}/{total} verificações passaram)")
    else:
        failed = total - ok
        print(f"⚠️  {failed}/{total} verificações falharam.")
        print("   Instale as dependências: pip install -r requirements.txt")
    print("═" * 60 + "\n")


def main():
    """Função principal."""
    setup_logging()
    logger = logging.getLogger(__name__)

    args = parse_args()

    # Modo de verificação
    if args.check:
        run_health_check()
        return

    logger.info("Órbita iniciando...")
    brain = Brain()
    if args.profile:
        brain.select_profile(args.profile)
    if args.model:
        provider, _, model = args.model.partition(":")
        if provider in brain.settings.providers() and model:
            brain.select_model(provider, model)
        else:
            brain.select_model("ollama", args.model)

    # Determina o modo de operação
    if args.gui:
        mode = "gui"
    elif args.text:
        mode = "text"
    elif args.voice:
        mode = "voice"
    else:
        mode = INPUT_MODE

    logger.info(f"Modo: {mode} | perfil: {brain.profile.name} | modelo: {':'.join(brain.current_model)}")

    if mode == "gui":
        from agent.gui import launch_gui
        launch_gui(brain)
    elif mode == "voice":
        brain.run_voice_mode()
    else:
        brain.run_text_mode()


if __name__ == "__main__":
    main()
