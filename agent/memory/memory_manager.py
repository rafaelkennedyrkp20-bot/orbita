"""
memory_manager.py — Gerencia memória de curto e longo prazo do agente.
Log do dia em JSONL (append) e fatos de longo prazo. As conversas completas ficam em
core/conversations.py.
"""

import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent.core.config import (
    DAILY_LOGS_DIR, LONG_TERM_DIR, LEGACY_DAILY_LOGS_DIR, LEGACY_LONG_TERM_DIR,
    DAILY_LOG_MAX_ENTRIES, USER_PROFILE,
)

logger = logging.getLogger(__name__)


def migrate_memory(daily_dir: Path, long_dir: Path, legacy_daily: Path, legacy_long: Path) -> None:
    """Copia logs e fatos antigos para data/memory. Repetir não duplica nem apaga a origem."""
    if legacy_long.resolve() == long_dir.resolve() and legacy_daily.resolve() == daily_dir.resolve():
        return
    long_dir.mkdir(parents=True, exist_ok=True)
    daily_dir.mkdir(parents=True, exist_ok=True)
    source = legacy_long / "memory.json"
    target = long_dir / "memory.json"
    if source.is_file() and not target.exists():
        backup = long_dir / "backup"
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup / "memory.json")
        shutil.copy2(source, target)
    if legacy_daily.is_dir():
        for item in legacy_daily.iterdir():
            if item.suffix.lower() not in {".json", ".jsonl"} or not item.is_file():
                continue
            dest = daily_dir / item.name
            if dest.exists():
                continue
            shutil.copy2(item, dest)


class MemoryManager:
    """
    Gerencia dois tipos de memória:
    - Diária: arquivo JSONL por dia (uma interação por linha), usado pela ferramenta `recall`.
    - Longo prazo: padrões, preferências e resumos persistentes.
    """

    def __init__(self, daily_dir: Path | None = None, long_dir: Path | None = None,
                 legacy_daily: Path | None = None, legacy_long: Path | None = None,
                 profile_path: Path | None = None):
        self.daily_dir = Path(daily_dir or DAILY_LOGS_DIR)
        self.long_dir = Path(long_dir or LONG_TERM_DIR)
        self.profile_path = Path(profile_path or USER_PROFILE)
        migrate_memory(self.daily_dir, self.long_dir, legacy_daily or LEGACY_DAILY_LOGS_DIR,
                       legacy_long or LEGACY_LONG_TERM_DIR)
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        self.long_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path.parent.mkdir(parents=True, exist_ok=True)

        # Log da sessão atual (em memória)
        self._session_log: list[dict] = []
        self._today = datetime.now().strftime("%Y-%m-%d")

        # Carrega dados de hoje se já existirem
        self._load_today()

        # Carrega memória de longo prazo
        self._facts_cache: Optional[list[str]] = None
        self._long_term = self._load_long_term()
        self._profile = self._load_profile()

        logger.info("MemoryManager inicializado.")

    # ─────────────────────────────────────────────
    # Memória Diária
    # ─────────────────────────────────────────────

    @property
    def _today_jsonl_file(self) -> Path:
        """Log append-only de hoje: uma interação por linha (nunca reescreve o arquivo inteiro)."""
        return self.daily_dir / f"{self._today}.jsonl"

    def _load_today(self):
        """Carrega as interações de hoje (JSON antigo, se existir, + JSONL) para o `recall`."""
        entries: list[dict] = []
        legacy = self.daily_dir / f"{self._today}.json"
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

        words = {w for w in query.lower().split() if len(w) > 3}
        if not words:
            return None

        # Pontuação simples baseada em palavras em comum
        scored = []
        for entry in self._session_log[-50:]:  # Analisa as últimas 50 entradas
            entry_text = entry.get("_lower")
            if entry_text is None:
                entry_text = (entry.get("user", "") + " " + entry.get("agent", "")).lower()
                entry["_lower"] = entry_text
            score = sum(1 for w in words if w in entry_text)
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
        return self.long_dir / "memory.json"

    def _load_long_term(self) -> dict:
        """Carrega memória de longo prazo do disco."""
        self._facts_cache = None
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

    def _records(self) -> list[dict]:
        raw = self._long_term.setdefault("facts", [])
        changed = False
        records = []
        for index, item in enumerate(raw):
            if isinstance(item, str):
                item = {"fact": item}
                changed = True
            if not isinstance(item, dict):
                continue
            fact = str(item.get("fact") or "").strip()
            if not fact:
                continue
            if not item.get("id"):
                item["id"] = f"legacy-{index}-{uuid.uuid4().hex[:8]}"
                changed = True
            item["fact"] = fact
            item["origin"] = item.get("origin") or "legacy"
            if item.get("scope") not in ("global", "project"):
                item["scope"] = "global"
                changed = True
            item["project"] = str(item.get("project") or "")
            records.append(item)
        if changed:
            self._long_term["facts"] = records
            self._facts_cache = None
            self.save_long_term()
        return records

    def remember_fact(self, fact: str, scope: str = "global", project: str = "", origin: str = "user"):
        """Registra um fato. Escopo project só volta quando o mesmo projeto está aberto."""
        fact = (fact or "").strip()
        if not fact:
            return
        if scope not in ("global", "project"):
            scope = "global"
        project = str(Path(project).resolve()) if scope == "project" and project else ""
        if scope == "project" and not project:
            scope = "global"
        facts = self._records()
        if any(item.get("fact", "").lower() == fact.lower() and item.get("scope") == scope
               and item.get("project") == project for item in facts):
            return
        facts.append({
            "id": uuid.uuid4().hex[:12],
            "fact": fact,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "origin": origin or "user",
            "scope": scope,
            "project": project,
        })
        self._long_term["facts"] = facts[-100:]
        self._facts_cache = None
        self.save_long_term()
        logger.info("Fato registrado: %s", fact[:60])

    def list_facts(self, project: str = "") -> list[dict]:
        return [dict(item) for item in self._visible(project)]

    def update_fact(self, fact_id: str, fact: str) -> bool:
        fact = (fact or "").strip()
        if not fact:
            return False
        for item in self._records():
            if item.get("id") == fact_id:
                item["fact"] = fact[:500]
                self._facts_cache = None
                self.save_long_term()
                return True
        return False

    def delete_fact(self, fact_id: str) -> bool:
        records = self._records()
        kept = [item for item in records if item.get("id") != fact_id]
        if len(kept) == len(records):
            return False
        self._long_term["facts"] = kept
        self._facts_cache = None
        self.save_long_term()
        return True

    def _visible(self, project: str = "") -> list[dict]:
        current = str(Path(project).resolve()) if project else ""
        visible = []
        for item in self._records():
            if item.get("scope") != "project":
                visible.append(item)
            elif current and item.get("project") == current:
                visible.append(item)
        return visible

    def _all_facts(self, project: str = "") -> list[str]:
        return [item["fact"] for item in self._visible(project)]

    def facts(self, limit: int = 40, project: str = "") -> list[str]:
        """Fatos visíveis neste projeto: globais e os do projeto aberto."""
        all_f = self._all_facts(project)
        return all_f[-limit:] if limit else list(all_f)

    def search_facts(self, query: str, limit: int = 15, project: str = "") -> list[str]:
        words = {w for w in query.lower().split() if len(w) > 2}
        if not words:
            return []
        scored = []
        for text in self._all_facts(project):
            low = text.lower()
            score = sum(1 for w in words if w in low)
            if score:
                scored.append((score, text))
        scored.sort(key=lambda pair: -pair[0])
        return [text for _, text in scored[:limit]]

    def _load_profile(self) -> dict:
        """Carrega o perfil do usuário."""
        if self.profile_path.exists():
            try:
                with open(self.profile_path, "r", encoding="utf-8") as f:
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
            with open(self.profile_path, "w", encoding="utf-8") as f:
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
