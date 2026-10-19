"""
main.py — Ponto de entrada do Órbita.
Liga todos os módulos e inicia o agente no modo escolhido.
"""

import argparse
import logging
import re
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


# Bibliotecas do sistema que a janela (QtWebEngine) usa no Linux e que distros enxutas não trazem.
# Medido num Ubuntu 24.04 do WSL: sem libxkbfile1 o Órbita fechava com ImportError antes de abrir.
LINUX_QT_PACKAGES = {
    "libxkbfile.so.1": "libxkbfile1", "libxcb-icccm.so.4": "libxcb-icccm4",
    "libxcb-keysyms.so.1": "libxcb-keysyms1", "libxcb-shape.so.0": "libxcb-shape0",
    "libxcb-cursor.so.0": "libxcb-cursor0", "libxkbcommon-x11.so.0": "libxkbcommon-x11-0",
    "libEGL.so.1": "libegl1", "libOpenGL.so.0": "libopengl0", "libnss3.so": "libnss3",
    "libpcsclite.so.1": "libpcsclite1",
}
LINUX_QT_APT = "sudo apt install " + " ".join(LINUX_QT_PACKAGES.values())


def window_problem(error: ImportError | None = None) -> str:
    """Por que a janela não abre, em texto para a pessoa; vazio quando abre."""
    if error is None:
        try:
            import importlib

            importlib.import_module("PyQt6.QtWebEngineWidgets")
            return ""
        except ImportError as exc:
            error = exc
    missing = re.search(r"([\w.+-]+\.so[\w.]*): cannot open shared object file", str(error))
    if not missing:
        return f"{error} → pip install -r requirements.txt"
    library = missing.group(1)
    package = LINUX_QT_PACKAGES.get(library)
    return (f"falta a biblioteca do sistema {library}" + (f" (pacote {package})" if package else "") + ".\n"
            f"   → Debian/Ubuntu: {LINUX_QT_APT}\n"
            f"   → Fedora/Arch: instale o pacote que fornece {library}")


def run_health_check():
    """Verifica se todas as dependências estão ok."""
    print("\n" + "═" * 60)
    from agent import __version__
    print(f"  Órbita {__version__} — Verificação de Saúde")
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

    # 2. Pacotes opcionais (voz, atalhos, web)
    import importlib.util

    for mod_name, label, hint in (
        ("faster_whisper", "faster-whisper", "pip install faster-whisper"),
        ("keyboard", "keyboard", "pip install keyboard"),
        ("ddgs", "ddgs (busca web)", "pip install ddgs"),
        ("bs4", "BeautifulSoup (leitura web)", "pip install beautifulsoup4"),
    ):
        found = importlib.util.find_spec(mod_name) is not None
        print(f"{'✅' if found else '❌'} {label}: {'instalado.' if found else 'não instalado. → ' + hint}")
        checks.append(found)

    # 3. Janela (QtWebEngine): no Linux depende de bibliotecas do sistema
    problem = window_problem()
    print("✅ Janela (Qt WebEngine): carrega." if not problem else f"❌ Janela (Qt WebEngine): {problem}")
    checks.append(not problem)

    # Silero VAD é opcional (saiu do requirements: puxava o PyTorch); sem ele o ditado usa o volume
    try:
        import torch
        from silero_vad import load_silero_vad
        load_silero_vad(onnx=True)
        device = "CUDA" if torch.cuda.is_available() else "CPU"
        print(f"✅ Silero VAD: instalado ({device}).")
    except ImportError:
        print("ℹ️  Silero VAD: não instalado (opcional; o ditado detecta a fala pelo volume).")
    except Exception as e:
        print(f"⚠️  Silero VAD: erro ({e}); o ditado detecta a fala pelo volume.")

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
        try:
            from agent.gui import launch_gui
        except ImportError as error:
            logger.exception("A janela não abriu")
            print(f"\n[Órbita] A janela não abre: {window_problem(error)}\n", file=sys.stderr, flush=True)
            sys.exit(1)
        launch_gui(brain)
    elif mode == "voice":
        brain.run_voice_mode()
    else:
        brain.run_text_mode()


if __name__ == "__main__":
    main()
