"""
memory_manager.py — Gerencia memória de curto e longo prazo do agente.
Log do dia em JSONL (append) e fatos de longo prazo. As conversas completas ficam em
core/conversations.py.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent.core.config import (
    DAILY_LOGS_DIR, LONG_TERM_DIR,
    DAILY_LOG_MAX_ENTRIES, USER_PROFILE,
)

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Gerencia dois tipos de memória:
    - Diária: arquivo JSONL por dia (uma interação por linha), usado pela ferramenta `recall`.
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
    def _today_jsonl_file(self) -> Path:
        """Log append-only de hoje: uma interação por linha (nunca reescreve o arquivo inteiro)."""
        return DAILY_LOGS_DIR / f"{self._today}.jsonl"

    def _load_today(self):
        """Carrega as interações de hoje (JSON antigo, se existir, + JSONL) para o `recall`."""
        entries: list[dict] = []
        legacy = DAILY_LOGS_DIR / f"{self._today}.json"
        if legacy.exists():
            try:
                entries += json.loads(legacy.read_text(encoding="utf-8")).get("interactions", [])
            except (OSError, ValueError, AttributeError) as error:
                logger.warning("Log antigo de hoje ilegível: %s", error)
        if self._today_jsonl_file.exists():
            try:
                for line in self._today_jsonl_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        entries.append(json.loads(line))
            except (OSError, ValueError) as error:
                logger.warning("Log de hoje ilegível: %s", error)
        self._session_log = entries[-DAILY_LOG_MAX_ENTRIES:]

    def log_interaction(self, user_input: str, agent_response: str, intent: str = "chat"):
        """Registra uma interação (memória + uma linha no JSONL do dia)."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "intent": intent,
            "user": user_input,
            "agent": agent_response,
        }
        self._session_log.append(entry)
        if len(self._session_log) > DAILY_LOG_MAX_ENTRIES:
            self._session_log = self._session_log[-DAILY_LOG_MAX_ENTRIES:]
        try:
            with open(self._today_jsonl_file, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as error:
            logger.error("Não foi possível gravar o log do dia: %s", error)

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
