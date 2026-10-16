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
import re
import threading
import time
import unicodedata
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
    "recent_workspaces": [],          # projetos abertos recentemente (diálogo "Projeto")
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

_RESERVED_FOLDER_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def resolve_workspace(profile_workspace: str, default_workspace: str, *, home: Path | None = None) -> Path:
    """Pasta em que o agente trabalha: a do perfil, senão a do projeto, senão a pasta do usuário."""
    fallback = home or Path.home()
    chosen = (profile_workspace or default_workspace or "").strip()
    if not chosen:
        return fallback
    try:
        path = Path(chosen).expanduser()
    except (OSError, RuntimeError, ValueError):
        return fallback
    return path if path.is_dir() else fallback


def project_folder_name(name: str) -> str:
    """Nome seguro para uma pasta nova de projeto no Windows."""
    clean = (name or "").strip().rstrip(". ")
    if not clean or re.search(r'[<>:"/\\|?*\x00-\x1f]', clean):
        raise ValueError('Use um nome simples, sem \\ / : * ? " < > |')
    if clean.split(".")[0].upper() in _RESERVED_FOLDER_NAMES:
        raise ValueError("Esse nome é reservado pelo Windows. Escolha outro.")
    if len(clean) > 80:
        raise ValueError("O nome está longo demais.")
    return clean


def _provider_slug(label: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_") or "api"


class Settings:
    """Preferências persistidas em `data/settings.json` (thread-safe)."""

    _grok_cred_cache: tuple[Any, float, bool] | None = None

    def __init__(self, path: Path = SETTINGS_FILE):
        self.path = path
        self._lock = threading.RLock()
        self._data = deepcopy(DEFAULT_SETTINGS)
        self._providers_cache: tuple[Any, dict[str, dict[str, Any]]] | None = None
        self._load()

    def _load(self) -> None:
        self._providers_cache = None
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
            if key == "providers":
                self._providers_cache = None
        if save:
            self.save()

    # ── Provedores ───────────────────────────────────────────

    def _merged_providers(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            user_providers = self._data.get("providers") or {}
            ollama_env = os.environ.get("OLLAMA_BASE_URL", "")
            cache_key = (id(user_providers), len(user_providers), ollama_env)
            if self._providers_cache is not None and self._providers_cache[0] == cache_key:
                return self._providers_cache[1]
            merged: dict[str, dict[str, Any]] = {
                k: {**v, "models": list(v.get("models", []))}
                for k, v in DEFAULT_PROVIDERS.items()
            }
            for name, override in user_providers.items():
                if isinstance(override, dict):
                    base = merged.setdefault(name, {})
                    base.update(override)
                    if "models" in base:
                        base["models"] = list(base["models"])
            if ollama_env:
                merged["ollama"]["base_url"] = ollama_env
            self._providers_cache = (cache_key, merged)
            return merged

    def providers(self) -> dict[str, dict[str, Any]]:
        """Catálogo final: padrões + sobrescritas/novos provedores do usuário."""
        return {
            k: {**v, "models": list(v.get("models", []))}
            for k, v in self._merged_providers().items()
        }

    def provider(self, name: str) -> dict[str, Any]:
        providers = self._merged_providers()
        if name not in providers:
            raise KeyError(f"Provedor desconhecido: {name}")
        cfg = providers[name]
        return {**cfg, "models": list(cfg.get("models", []))}

    def add_custom_provider(self, *, label: str, base_url: str, api_key: str = "",
                            models: list[str] | None = None) -> str:
        """Registra uma API compatível com a OpenAI. A chave, se houver, vai para o .env."""
        label = (label or "").strip()
        base_url = (base_url or "").strip().rstrip("/")
        if not label:
            raise ValueError("Dê um nome para essa API.")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("O endereço precisa começar com http:// ou https://.")
        provider_id = self._unique_provider_id(_provider_slug(label))
        clean_models = []
        for model in models or []:
            text = str(model).strip()
            if text and text not in clean_models:
                clean_models.append(text)
        entry: dict[str, Any] = {
            "type": "openai",
            "label": label,
            "base_url": base_url,
            "models": clean_models[:40],
        }
        key = (api_key or "").strip()
        if key:
            env = "ORBITA_" + re.sub(r"[^A-Z0-9]", "_", provider_id.upper()) + "_API_KEY"
            entry["api_key_env"] = env
            self.save_api_key(env, key)
        stored = dict(self.get("providers") or {})
        stored[provider_id] = entry
        self.set("providers", stored)
        return provider_id

    def remove_custom_provider(self, provider_id: str) -> None:
        if provider_id in DEFAULT_PROVIDERS:
            raise ValueError("Esse provedor faz parte do Órbita e não pode ser removido.")
        stored = dict(self.get("providers") or {})
        if provider_id not in stored:
            raise ValueError("API não encontrada.")
        stored.pop(provider_id)
        self.set("providers", stored, save=False)
        if self.get("provider") == provider_id:
            self.set("provider", "ollama", save=False)
            self.set("model", "", save=False)
        self.save()

    def _unique_provider_id(self, base: str) -> str:
        existing = set(self._merged_providers())
        candidate = base or "api"
        number = 2
        while candidate in existing:
            candidate = f"{base}_{number}"
            number += 1
        return candidate

    @staticmethod
    def api_key(provider_cfg: dict[str, Any]) -> str:
        env = provider_cfg.get("api_key_env")
        return (os.environ.get(env, "") if env else provider_cfg.get("api_key", "")) or ""

    def has_credentials(self, name: str) -> bool:
        providers = self._merged_providers()
        if name not in providers:
            raise KeyError(f"Provedor desconhecido: {name}")
        cfg = providers[name]
        if cfg.get("type") == "grok_cli":
            from agent.core import grok_cli

            key = (grok_cli.executable, grok_cli.is_logged_in, os.environ.get("XAI_API_KEY", ""), os.environ.get("PATH", ""))
            now = time.monotonic()
            cached = Settings._grok_cred_cache
            if cached is not None and cached[0] == key and (now - cached[1]) < 15.0:
                return cached[2]
            ok = grok_cli.executable() is not None and grok_cli.is_logged_in()
            Settings._grok_cred_cache = (key, now, ok)
            return ok
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
