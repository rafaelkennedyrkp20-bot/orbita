"""
settings.py — Preferências do usuário que mudam em tempo de execução.

`config.py` guarda constantes técnicas (voz, caminhos). Este módulo guarda o que a
interface altera: perfil ativo, provedor/modelo, modo de permissão, chaves de API
(no `.env`) e o catálogo de provedores de IA.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent.core.config import DATA_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

SETTINGS_FILE = DATA_DIR / "settings.json"
ENV_FILE = PROJECT_ROOT / ".env"

# Catálogo de provedores. "openai" = qualquer API compatível com o formato OpenAI
# (/chat/completions). A lista de modelos é só uma sugestão inicial: a GUI consulta
# o endpoint /models de cada provedor e o campo aceita qualquer nome digitado.
DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "ollama": {
        "type": "ollama",
        "label": "Ollama (local)",
        "base_url": "http://127.0.0.1:11434",
        "models": ["qwen3:14b"],
    },
    "deepseek": {
        "type": "openai",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    "openai": {
        "type": "openai",
        "label": "OpenAI (GPT)",
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "models": ["gpt-5", "gpt-5-mini"],
        "omit_temperature": True,
        "max_tokens_param": "max_completion_tokens",
    },
    "anthropic": {
        "type": "anthropic",
        "label": "Anthropic (Claude)",
        "api_key_env": "ANTHROPIC_API_KEY",
        "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"],
    },
    "grok": {
        # Agente Grok Build da xAI usando a sua conta (login pelo navegador, ver grok_cli.py)
        "type": "grok_cli",
        "label": "Grok Build (conta xAI)",
        "models": ["grok-4.7", "grok-4.7-build-fast", "grok-4.6"],
    },
    "gemini": {
        "type": "openai",
        "label": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_env": "GEMINI_API_KEY",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
    },
    "openrouter": {
        "type": "openai",
        "label": "OpenRouter (centenas de modelos)",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "models": ["deepseek/deepseek-chat", "qwen/qwen3-coder"],
    },
    "groq": {
        "type": "openai",
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "models": [],
    },
    "xai": {
        "type": "openai",
        "label": "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "api_key_env": "XAI_API_KEY",
        "models": [],
    },
    "mistral": {
        "type": "openai",
        "label": "Mistral",
        "base_url": "https://api.mistral.ai/v1",
        "api_key_env": "MISTRAL_API_KEY",
        "models": [],
    },
    "lmstudio": {
        "type": "openai",
        "label": "LM Studio (local)",
        "base_url": "http://127.0.0.1:1234/v1",
        "models": [],
    },
}

DEFAULT_SETTINGS: dict[str, Any] = {
    # Identidade e primeira execução
    "onboarded": False,
    "user_name": "",
    "default_workspace": "",          # pasta de trabalho quando o perfil não define uma
    "theme": "dark",
    "native_notifications": True,     # avisos do Windows quando a janela não está em foco
    "active_profile": "geral",
    # perguntar: confirma tudo que altera algo | auto: confirma só execução/controle do PC
    # livre: nunca pergunta (a IA age com total liberdade)
    "permission_mode": "auto",
    "voice_replies": True,
    # "provedor:modelo" -> id do perfil aplicado automaticamente ao escolher o modelo
    "model_profiles": {},
    "providers": {},
    "ollama_num_ctx": 16384,
    # Mantém o modelo carregado entre as chamadas do loop de ferramentas.
    "ollama_keep_alive": "10m",
    "show_reasoning": True,
    # Economia de tokens: maximo | equilibrado | livre (ver usage.py)
    "economy_mode": "equilibrado",
    # Freio: pausa e pergunta ao passar destes limites (0 = sem limite).
    # Modelos locais (Ollama) não contam no orçamento diário.
    "turn_token_budget": 400000,
    "daily_token_budget": 0,
    # Escolhe automaticamente o melhor modelo por especialidade para subagentes (data/model_catalog.json)
    "auto_routing": True,
    # "provedor:modelo" para subagentes quando o roteador não achar nada (vazio = mesmo modelo)
    "cheap_model": "",
    # "provedor:modelo" para a ferramenta generate_image (ex.: openai:gpt-image-1)
    "image_model": "",
}

PERMISSION_MODES = {
    "perguntar": "Perguntar antes de alterar algo",
    "auto": "Automático (pergunta só para executar/controlar o PC)",
    "livre": "Livre (a IA age sem pedir confirmação)",
}


class Settings:
    """Preferências persistidas em `data/settings.json` (thread-safe)."""

    def __init__(self, path: Path = SETTINGS_FILE):
        self.path = path
        self._lock = threading.RLock()
        self._data = deepcopy(DEFAULT_SETTINGS)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                self._data.update(stored)
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("settings.json inválido, usando padrões: %s", error)

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            self._data[key] = value
        if save:
            self.save()

    # ── Provedores ───────────────────────────────────────────

    def providers(self) -> dict[str, dict[str, Any]]:
        """Catálogo final: padrões + sobrescritas/novos provedores do usuário."""
        merged = deepcopy(DEFAULT_PROVIDERS)
        for name, override in (self.get("providers") or {}).items():
            if isinstance(override, dict):
                merged.setdefault(name, {}).update(override)
        # Permite apontar o Ollama para outra máquina via .env
        if os.environ.get("OLLAMA_BASE_URL"):
            merged["ollama"]["base_url"] = os.environ["OLLAMA_BASE_URL"]
        return merged

    def provider(self, name: str) -> dict[str, Any]:
        providers = self.providers()
        if name not in providers:
            raise KeyError(f"Provedor desconhecido: {name}")
        return providers[name]

    @staticmethod
    def api_key(provider_cfg: dict[str, Any]) -> str:
        env = provider_cfg.get("api_key_env")
        return (os.environ.get(env, "") if env else provider_cfg.get("api_key", "")) or ""

    def has_credentials(self, name: str) -> bool:
        cfg = self.provider(name)
        if cfg.get("type") == "grok_cli":
            from agent.core import grok_cli

            return grok_cli.executable() is not None and grok_cli.is_logged_in()
        return not cfg.get("api_key_env") or bool(self.api_key(cfg))

    @staticmethod
    def save_api_key(env_name: str, value: str) -> None:
        """Grava/atualiza uma chave no `.env` local e no processo atual."""
        from dotenv import set_key

        ENV_FILE.touch(exist_ok=True)
        set_key(str(ENV_FILE), env_name, value, quote_mode="never")
        os.environ[env_name] = value

    # ── Vínculo modelo → perfil ──────────────────────────────

    def profile_for_model(self, provider: str, model: str) -> str | None:
        return (self.get("model_profiles") or {}).get(f"{provider}:{model}")

    def bind_model_profile(self, provider: str, model: str, profile_id: str | None) -> None:
        mapping = dict(self.get("model_profiles") or {})
        key = f"{provider}:{model}"
        if profile_id:
            mapping[key] = profile_id
        else:
            mapping.pop(key, None)
        self.set("model_profiles", mapping)
