"""
brain.py — Liga todos os módulos: provedores, perfis, ferramentas, MCP, skills, memória e voz.

A decisão do que fazer é do próprio modelo (loop agêntico em agent_loop.py). O Brain
cuida da seleção de perfil/modelo, da criação de sessões e dos modos texto/voz do terminal.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent.core.agent_loop import AgentSession, ApproveFn, EventFn
from agent.core.config import LLM_MODEL
from agent.core.conversations import ConversationStore, title_from, to_ui_blocks
from agent.core.conversations import new_id as new_conversation_id
from agent.core.mcp_hub import MCPHub
from agent.core import routing
from agent.core.profiles import Profile, ProfileManager
from agent.core.providers import get_provider
from agent.core.settings import Settings, project_folder_name, resolve_workspace
from agent.core.skills import SkillManager
from agent.core.tools import ToolRegistry
from agent.core.usage import UsageTracker
from agent.memory.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

EXIT_COMMANDS = {
    "sair", "exit", "quit", "encerrar agente", "encerrar o agente", "fechar agente", "fechar o agente",
    "desligar agente", "desligar o agente", "sair do agente", "encerrar conversa", "encerrar a conversa",
}


def _normalize_command(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[!?.,;:]+$", "", text)
    return re.sub(r"\s+", " ", text)


def is_exit_command(text: str) -> bool:
    """Aceita encerramento apenas com comandos explícitos."""
    return _normalize_command(text) in EXIT_COMMANDS


class Brain:

    def __init__(self, start_mcp: bool = True):
        logger.info("Inicializando Brain...")
        self.settings = Settings()
        self.memory = MemoryManager()
        self.usage = UsageTracker()
        self.profiles = ProfileManager()
        self.skills = SkillManager()
        self.registry = ToolRegistry()
        self.mcp = MCPHub(self.registry, plugin_configs=self.skills.plugin_mcp_configs)
        self._system = None
        self._speaker = None
        self._listener = None
        self._local_models: Optional[tuple[float, list[str]]] = None

        from agent.actions.builtin_tools import register_builtin_tools
        from agent.actions.image_gen import register_image_tool

        register_builtin_tools(self.registry, self)
        register_image_tool(self.registry, self)
        if start_mcp:
            self.mcp.start()
        self.session: Optional[AgentSession] = None
        self.conversations = ConversationStore()
        self.conversation_id: Optional[str] = None
        self.conversation_title = ""
        logger.info("Brain pronto: %d ferramentas, %d skills, %d perfis.",
                    len(self.registry.all()), len(self.skills.skills), len(self.profiles.profiles))

    # ── Serviços carregados sob demanda (abertura mais rápida) ──

    @property
    def system(self):
        if self._system is None:
            from agent.actions.system_control import SystemControl
            self._system = SystemControl()
        return self._system

    @property
    def speaker(self):
        if self._speaker is None:
            from agent.voice.speaker import Speaker
            self._speaker = Speaker()
        return self._speaker

    @property
    def listener(self):
        if self._listener is None:
            from agent.voice.listener import Listener
            self._listener = Listener()
        return self._listener

    # ── Perfil e modelo ──────────────────────────────────────

    @property
    def profile(self) -> Profile:
        return self.profiles.get(self.settings.get("active_profile", "geral"))

    @property
    def current_model(self) -> tuple[str, str]:
        provider = self.settings.get("provider") or "ollama"
        model = self.settings.get("model") or (LLM_MODEL if provider == "ollama" else "")
        if provider not in self.settings.providers():
            provider, model = "ollama", LLM_MODEL
        return provider, model

    def select_profile(self, profile_id: str) -> Profile:
        """Ativa um perfil; se ele define modelo próprio, troca o modelo também."""
        profile = self.profiles.get(profile_id)
        self.settings.set("active_profile", profile.id)
        if profile.provider and profile.model:
            self.settings.set("provider", profile.provider, save=False)
            self.settings.set("model", profile.model)
        return profile

    def select_model(self, provider: str, model: str) -> Optional[Profile]:
        """Troca o modelo; se houver perfil vinculado a ele, ativa o perfil. Retorna o perfil aplicado."""
        self.settings.set("provider", provider, save=False)
        self.settings.set("model", model)
        bound = self.settings.profile_for_model(provider, model)
        if bound and bound in self.profiles.profiles:
            self.settings.set("active_profile", bound)
            return self.profiles.get(bound)
        return None

    def resolve_model(self, ref: str, fallback: tuple[str, str]) -> tuple[str, str]:
        """'provedor:modelo' → (provedor, modelo), caindo no fallback se faltar chave/provedor."""
        ref = (ref or "").strip()
        if not ref:
            return fallback
        providers = self.settings.providers()
        provider, _, model = ref.partition(":")
        if provider not in providers:
            # Só o nome do modelo: procura um provedor que o liste
            owner = next((name for name, cfg in providers.items() if ref in cfg.get("models", [])), None)
            provider, model = (owner, ref) if owner else (fallback[0], ref)
        if not model or not self.settings.has_credentials(provider):
            logger.info("Modelo %s indisponível (sem chave); usando %s:%s", ref, *fallback)
            return fallback
        return provider, model

    def local_models(self) -> list[str]:
        """Modelos instalados no Ollama (cache de 5 min; vazio se o Ollama estiver parado)."""
        if self._local_models and time.time() - self._local_models[0] < 300:
            return self._local_models[1]
        try:
            models = get_provider("ollama", self.settings).installed_models()
        except Exception:
            models = []
        self._local_models = (time.time(), models)
        return models

    def route_model(self, specialty: str) -> Optional[str]:
        """Melhor 'provedor:modelo' com acesso para a especialidade (catálogo + modo de economia)."""
        if not self.settings.get("auto_routing", True):
            return None
        return routing.best(specialty, self.settings, self.current_model, self.local_models())

    def models_table(self) -> str:
        """Capacidades dos modelos disponíveis, para o agente principal escolher na delegação."""
        return routing.table_text(self.settings, self.current_model, self.local_models())

    def list_models(self, provider: str) -> list[str]:
        return get_provider(provider, self.settings).list_models()

    def effective_workspace(self) -> Path:
        return resolve_workspace(self.profile.workspace, self.settings.get("default_workspace") or "")

    def set_workspace(self, folder: str | Path) -> Path:
        """Define a pasta do projeto. Se o perfil ativo tem pasta própria, ela acompanha."""
        path = Path(folder).expanduser()
        if not path.is_dir():
            raise ValueError("Essa pasta não existe.")
        resolved = str(path.resolve())
        profile = self.profile
        if (profile.workspace or "").strip():
            profile.workspace = resolved
            self.profiles.save(profile)
        recent = [resolved] + [p for p in (self.settings.get("recent_workspaces") or []) if p != resolved]
        self.settings.set("recent_workspaces", recent[:8], save=False)
        self.settings.set("default_workspace", resolved)
        return path

    def recent_workspaces(self) -> list[str]:
        """Projetos abertos recentemente que ainda existem (o mais recente primeiro)."""
        return [p for p in (self.settings.get("recent_workspaces") or []) if Path(p).is_dir()]

    @staticmethod
    def default_projects_parent() -> Path:
        documents = Path.home() / "Documents"
        return documents if documents.is_dir() else Path.home()

    def create_workspace(self, parent: str, name: str) -> Path:
        """Cria uma pasta de projeto dentro de `parent` e passa a trabalhar nela."""
        parent_path = Path(parent).expanduser() if (parent or "").strip() else self.default_projects_parent()
        if not parent_path.is_dir():
            raise ValueError("Escolha uma pasta que já existe para criar o projeto dentro dela.")
        folder = parent_path / project_folder_name(name)
        folder.mkdir(exist_ok=True)
        return self.set_workspace(folder)

    # ── Sessões ──────────────────────────────────────────────

    def new_session(self, events: Optional[EventFn] = None, approve: Optional[ApproveFn] = None) -> AgentSession:
        provider, model = self.current_model
        self.session = AgentSession(self, self.profile, provider, model, events=events, approve=approve)
        return self.session

    # ── Conversas salvas ─────────────────────────────────────

    def new_conversation(self) -> None:
        self.session = None
        self.conversation_id = None
        self.conversation_title = ""

    def open_conversation(self, conversation_id: str) -> Optional[dict]:
        """Reabre uma conversa salva; devolve os dados (com blocos para a interface)."""
        data = self.conversations.load(conversation_id)
        if not data:
            return None
        session = self.new_session()
        session.messages = data.get("messages", [])
        session.summary = data.get("summary")
        if data.get("provider") == self.current_model[0]:
            session.external_session = data.get("external_session")
        self.conversation_id = data["id"]
        self.conversation_title = data.get("title", "")
        data["blocks"] = to_ui_blocks(session.messages)
        return data

    def save_conversation(self) -> Optional[str]:
        session = self.session
        if session is None or not session.messages:
            return None
        if not self.conversation_id:
            self.conversation_id = new_conversation_id()
            first = next((m.get("content", "") for m in session.messages if m["role"] == "user"), "")
            self.conversation_title = title_from(first)
        existing = self.conversations.load(self.conversation_id) or {}
        provider, model = self.current_model
        self.conversations.save({
            "id": self.conversation_id,
            "title": existing.get("title") if existing.get("pinned_title") else self.conversation_title,
            "pinned_title": existing.get("pinned_title", False),
            "created": existing.get("created") or datetime.now().isoformat(timespec="seconds"),
            "profile": self.profile.id, "provider": provider, "model": model,
            "messages": session.messages, "summary": session.summary,
            "external_session": session.external_session,
        })
        return self.conversation_id

    def run_turn(self, text: str, images: Optional[list[str]] = None, events: Optional[EventFn] = None,
                 approve: Optional[ApproveFn] = None) -> str:
        """Executa um pedido na sessão atual, atualizando perfil/modelo se mudaram."""
        session = self.session
        provider, model = self.current_model
        if session is None:
            session = self.new_session(events, approve)
        else:
            session.profile = self.profile
            if (session.provider_name, session.model) != (provider, model):
                session.external_session = None   # outra IA: a sessão do Grok Build não vale mais
                session.prompted_tools = False
            session.provider_name, session.model = provider, model
            if events:
                session.events = events
            if approve:
                session.approve = approve
        response = session.run(text, images)
        self.memory.log_interaction(text, response, f"{provider}:{model}")
        try:
            self.save_conversation()
        except OSError:
            logger.exception("Não foi possível salvar a conversa")
        return response

    def startup_prompt(self) -> Optional[str]:
        profile = self.profile
        if profile.auto_startup and profile.startup_prompt.strip():
            return profile.startup_prompt.strip()
        return None

    def stop(self) -> None:
        if self.session is not None:
            self.session.cancel.set()
        if self._speaker is not None:
            self._speaker.stop()
        if self._listener is not None:
            self._listener.cancel_recording()

    # ── Modos de terminal ────────────────────────────────────

    @staticmethod
    def _terminal_approve(request: dict) -> str:
        if request["type"] == "budget":
            question = request["message"]
        else:
            args = str(request.get("args", ""))[:300]
            question = f"[{request.get('agent')}] Permitir {request['tool']}({args})?"
        answer = input(f"\n⚠️  {question} [s]im / [t]odas / [n]ão: ").strip().lower()
        return {"s": "yes", "t": "always"}.get(answer[:1], "no")

    @staticmethod
    def _terminal_events(kind: str, data: dict) -> None:
        if kind == "text":
            print(data["text"], end="", flush=True)
        elif kind == "tool_start":
            print(f"\n  🔧 {data['name']} {str(data.get('args', ''))[:120]}", flush=True)
        elif kind == "subagent_start":
            print(f"\n  👥 {data['agent']} ({data['model']}) começou", flush=True)

    def run_text_mode(self) -> None:
        provider, model = self.current_model
        print("\n" + "═" * 60)
        print(f"  Órbita — Modo Texto | {self.profile.name} | {provider}:{model}")
        print("  Digite sua mensagem ou 'sair' para encerrar.")
        print("═" * 60 + "\n")
        startup = self.startup_prompt()
        if startup:
            print("(prompt inicial do perfil enviado)\nAgente: ", end="")
            self.run_turn(startup, events=self._terminal_events, approve=self._terminal_approve)
            print("\n")
        while True:
            try:
                user_input = input("Você: ").strip()
                if not user_input:
                    continue
                if is_exit_command(user_input):
                    break
                print("Agente: ", end="")
                self.run_turn(user_input, events=self._terminal_events, approve=self._terminal_approve)
                print("\n")
            except KeyboardInterrupt:
                break
            except Exception as error:
                logger.exception("Erro no modo texto")
                print(f"Erro: {error}")
        self.shutdown()

    def run_voice_mode(self) -> None:
        from agent.voice.wake_word import WakeWord

        wake_word = WakeWord()
        print("\n" + "═" * 60)
        print("  Órbita — Modo Voz | pressione o atalho para falar | Ctrl+C encerra")
        print("═" * 60 + "\n")
        self.speaker.speak("Agente pessoal inicializado. Pronto para ouvir você.")
        try:
            while True:
                print("⏳ Aguardando ativação...", end="\r")
                wake_word.wait_for_activation()
                self.speaker.play_beep(frequency=880, duration=0.15)
                user_input = self.listener.listen()
                if not user_input:
                    print("❌ Não entendi. Tente novamente.")
                    continue
                print(f"Você: {user_input}")
                if is_exit_command(user_input):
                    self.speaker.speak("Encerrando o agente. Até logo!")
                    break
                response = self.run_turn(user_input, approve=self._terminal_approve)
                print(f"Agente: {response}\n")
                self.speaker.speak(response)
        except KeyboardInterrupt:
            pass
        finally:
            wake_word.cleanup()
            self.shutdown()

    def shutdown(self) -> None:
        logger.info("Encerrando agente.")
        self.mcp.shutdown()
        self.memory.save_long_term()
