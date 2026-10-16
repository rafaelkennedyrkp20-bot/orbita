"""
memory_manager.py — Gerencia memória de curto e longo prazo do agente.
Salva um log JSON por dia e mantém padrões de uso em memória persistente.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent.core.config import (
    DAILY_LOGS_DIR, LONG_TERM_DIR,
    DAILY_LOG_MAX_ENTRIES, USER_PROFILE, CHAT_AUTOSAVE_EVERY_INTERACTION
)

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Gerencia dois tipos de memória:
    - Diária: arquivo JSON por dia com interações detalhadas.
    - Longo prazo: padrões, preferências e resumos persistentes.
    """

    def __init__(self):
        # Garante que as pastas existem
        DAILY_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        LONG_TERM_DIR.mkdir(parents=True, exist_ok=True)
        USER_PROFILE.parent.mkdir(parents=True, exist_ok=True)

        # Log da sessão atual (em memória)
        self._session_log: list[dict] = []
        self._today = datetime.now().strftime("%Y-%m-%d")

        # Carrega dados de hoje se já existirem
        self._load_today()

        # Carrega memória de longo prazo
        self._long_term = self._load_long_term()
        self._profile = self._load_profile()

        logger.info("MemoryManager inicializado.")

    # ─────────────────────────────────────────────
    # Memória Diária
    # ─────────────────────────────────────────────

    @property
    def _today_file(self) -> Path:
        """Caminho do arquivo de log de hoje."""
        return DAILY_LOGS_DIR / f"{self._today}.json"

    def _load_today(self):
        """Carrega o log de hoje se existir."""
        if self._today_file.exists():
            try:
                with open(self._today_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._session_log = data.get("interactions", [])
                logger.debug(f"Log de hoje carregado: {len(self._session_log)} entradas.")
            except Exception as e:
                logger.error(f"Erro ao carregar log de hoje: {e}")
                self._session_log = []

    def log_interaction(self, user_input: str, agent_response: str, intent: str = "chat"):
        """
        Registra uma interação na sessão atual.

        Args:
            user_input: Texto do usuário.
            agent_response: Resposta do agente.
            intent: Intenção detectada.
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "intent": intent,
            "user": user_input,
            "agent": agent_response,
        }
        self._session_log.append(entry)

        # Compacta se exceder o limite
        if len(self._session_log) > DAILY_LOG_MAX_ENTRIES:
            self._session_log = self._session_log[-DAILY_LOG_MAX_ENTRIES:]

        logger.debug(f"Interação registrada. Total hoje: {len(self._session_log)}")
        if CHAT_AUTOSAVE_EVERY_INTERACTION:
            self.save_daily_log()

    @staticmethod
    def _read_log_file(log_file: Path) -> dict:
        """Lê um log diário, retornando uma estrutura vazia se estiver inválido."""
        try:
            with open(log_file, "r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as error:
            logger.warning("Não foi possível ler o histórico %s: %s", log_file.name, error)
            return {}

    @staticmethod
    def _is_valid_log_date(date: str) -> bool:
        """Evita que a interface use nomes de arquivo fora do diretório de históricos."""
        try:
            datetime.strptime(date, "%Y-%m-%d")
            return len(date) == 10
        except (TypeError, ValueError):
            return False

    def save_daily_log(self):
        """Salva o log do dia atual em disco."""
        data = {
            "date": self._today,
            "total_interactions": len(self._session_log),
            "interactions": self._session_log,
        }

        temporary_file = self._today_file.with_suffix(".json.tmp")
        try:
            with open(temporary_file, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(temporary_file, self._today_file)
            logger.debug(f"Log diário salvo: {self._today_file}")
        except Exception as e:
            temporary_file.unlink(missing_ok=True)
            logger.error(f"Erro ao salvar log diário: {e}")

    def list_chat_logs(self) -> list[dict]:
        """Lista conversas salvas para a interface de histórico."""
        entries = []
        for log_file in sorted(DAILY_LOGS_DIR.glob("????-??-??.json"), reverse=True):
            data = self._read_log_file(log_file)
            interactions = data.get("interactions", [])
            entries.append({
                "date": data.get("date", log_file.stem),
                "count": len(interactions) if isinstance(interactions, list) else 0,
            })
        return entries

    def load_chat_log(self, date: str) -> list[dict]:
        """Retorna as mensagens de uma conversa salva, sem alterar o contexto atual."""
        if not self._is_valid_log_date(date):
            return []
        data = self._read_log_file(DAILY_LOGS_DIR / f"{date}.json")
        interactions = data.get("interactions", [])
        return interactions if isinstance(interactions, list) else []

    def delete_chat_log(self, date: str) -> bool:
        """Apaga um dia de histórico. O dia atual é limpo e salvo vazio."""
        if not self._is_valid_log_date(date):
            return False
        if date == self._today:
            self._session_log = []
            self.save_daily_log()
            return True

        log_file = DAILY_LOGS_DIR / f"{date}.json"
        try:
            log_file.unlink(missing_ok=False)
            logger.info("Histórico removido: %s", log_file)
            return True
        except FileNotFoundError:
            return False
        except OSError as error:
            logger.error("Não foi possível apagar o histórico %s: %s", log_file, error)
            return False

    def get_relevant_context(self, query: str, max_entries: int = 5) -> Optional[str]:
        """
        Busca entradas relevantes no histórico para enriquecer o contexto.

        Args:
            query: Consulta do usuário.
            max_entries: Máximo de entradas relevantes a retornar.

        Returns:
            String com contexto relevante, ou None.
        """
        if not self._session_log:
            return None

        query_lower = query.lower()
        words = set(query_lower.split())

        # Pontuação simples baseada em palavras em comum
        scored = []
        for entry in self._session_log[-50:]:  # Analisa as últimas 50 entradas
            entry_text = (entry.get("user", "") + " " + entry.get("agent", "")).lower()
            score = sum(1 for w in words if w in entry_text and len(w) > 3)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:max_entries]

        if not top:
            return None

        context_parts = []
        for _, entry in top:
            ts = entry.get("timestamp", "")[:16]
            context_parts.append(
                f"[{ts}] Você: {entry['user'][:100]}\n"
                f"         Agente: {entry['agent'][:150]}"
            )

        return "Conversas anteriores relevantes:\n" + "\n\n".join(context_parts)

    # ─────────────────────────────────────────────
    # Memória de Longo Prazo
    # ─────────────────────────────────────────────

    @property
    def _long_term_file(self) -> Path:
        return LONG_TERM_DIR / "memory.json"

    def _load_long_term(self) -> dict:
        """Carrega memória de longo prazo do disco."""
        if self._long_term_file.exists():
            try:
                with open(self._long_term_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Erro ao carregar memória longa: {e}")
        return {"facts": [], "preferences": {}, "topics": {}}

    def save_long_term(self):
        """Salva memória de longo prazo em disco."""
        try:
            temporary_file = self._long_term_file.with_suffix(".json.tmp")
            with open(temporary_file, "w", encoding="utf-8") as f:
                json.dump(self._long_term, f, ensure_ascii=False, indent=2)
            os.replace(temporary_file, self._long_term_file)
            logger.debug("Memória de longo prazo salva.")
        except Exception as e:
            logger.error(f"Erro ao salvar memória longa: {e}")

    def remember_fact(self, fact: str):
        """
        Registra um fato importante na memória longa.

        Args:
            fact: Fato a ser lembrado.
        """
        facts = self._long_term.setdefault("facts", [])
        if any(item.get("fact", "").lower() == fact.lower() for item in facts):
            return
        entry = {"fact": fact, "timestamp": datetime.now().isoformat()}
        facts.append(entry)
        # Limita a 100 fatos
        if len(self._long_term["facts"]) > 100:
            self._long_term["facts"] = self._long_term["facts"][-100:]
        self.save_long_term()
        logger.info(f"Fato registrado: {fact[:60]}")

    def facts(self, limit: int = 40) -> list[str]:
        """Fatos mais recentes, para o prompt de sistema."""
        return [item.get("fact", "") for item in self._long_term.get("facts", [])[-limit:] if item.get("fact")]

    def search_facts(self, query: str, limit: int = 15) -> list[str]:
        words = {w for w in query.lower().split() if len(w) > 2}
        scored = []
        for item in self._long_term.get("facts", []):
            text = item.get("fact", "")
            score = sum(1 for w in words if w in text.lower())
            if score:
                scored.append((score, text))
        scored.sort(key=lambda pair: -pair[0])
        return [text for _, text in scored[:limit]]

    def forget_fact(self, index: int) -> bool:
        facts = self._long_term.get("facts", [])
        if 0 <= index < len(facts):
            facts.pop(index)
            self.save_long_term()
            return True
        return False

    def set_preference(self, key: str, value: str):
        """
        Salva uma preferência do usuário.

        Args:
            key: Nome da preferência.
            value: Valor da preferência.
        """
        self._long_term["preferences"][key] = {
            "value": value,
            "updated": datetime.now().isoformat()
        }
        self.save_long_term()

    def get_preference(self, key: str, default=None):
        """Recupera uma preferência do usuário."""
        entry = self._long_term["preferences"].get(key)
        if entry:
            return entry.get("value", default)
        return default

    # ─────────────────────────────────────────────
    # Perfil do Usuário
    # ─────────────────────────────────────────────

    def _load_profile(self) -> dict:
        """Carrega o perfil do usuário."""
        if USER_PROFILE.exists():
            try:
                with open(USER_PROFILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "name": "Usuário",
            "created": datetime.now().isoformat(),
            "preferences": {},
            "notes": [],
        }

    def save_profile(self):
        """Salva o perfil do usuário."""
        try:
            with open(USER_PROFILE, "w", encoding="utf-8") as f:
                json.dump(self._profile, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Erro ao salvar perfil: {e}")

    @property
    def user_name(self) -> str:
        return self._profile.get("name", "Usuário")

    @user_name.setter
    def user_name(self, name: str):
        self._profile["name"] = name
        self.save_profile()
