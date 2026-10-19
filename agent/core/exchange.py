"""Exportação e importação no formato do Órbita. Nada daqui executa ferramenta.

Chaves, tokens e sessão externa ficam de fora. Importar o mesmo pacote duas
vezes não cria uma segunda cópia.
"""

from __future__ import annotations

import re
from typing import Any

from agent.core.conversations import new_id

_CONVERSATION_ID = re.compile(r"^[a-f0-9]{12}$")
from agent.core.profiles import Profile

FORMAT_CONVERSATION = "orbita.conversation"
FORMAT_PROFILE = "orbita.profile"
VERSION = 1
_SECRET_KEY = re.compile(r"(api[_-]?key|token|secret|password|authorization|credential)", re.IGNORECASE)
_SECRET_VALUE = re.compile(r"\b(?:sk|sk-ant|sk-or|gsk|xai|ghp|hf_|pplx|r8_|AIza)[-_A-Za-z0-9]{12,}\b")
_ROLES = {"user", "assistant", "tool", "system"}
_MESSAGE_KEYS = ("role", "content", "name", "tool_call_id", "tool_calls")


def _strip(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(key or ""):
        return None
    if isinstance(value, str):
        return _SECRET_VALUE.sub("[removido]", value)
    if isinstance(value, list):
        return [_strip(item, key) for item in value]
    if isinstance(value, dict):
        cleaned = {}
        for child_key, child in value.items():
            if _SECRET_KEY.search(str(child_key)):
                continue
            cleaned[str(child_key)] = _strip(child, str(child_key))
        return cleaned
    return value


def _require(payload: dict, kind: str) -> dict:
    if not isinstance(payload, dict) or payload.get("format") != kind:
        raise ValueError("Este arquivo não é um pacote do Órbita.")
    if payload.get("version") != VERSION:
        raise ValueError("Versão de pacote não suportada.")
    return payload


def export_conversation(data: dict) -> dict:
    messages = []
    for message in data.get("messages") or []:
        if not isinstance(message, dict) or message.get("role") not in _ROLES:
            continue
        kept = {key: message.get(key) for key in _MESSAGE_KEYS if key in message}
        messages.append(_strip(kept))
    body = {
        "id": data.get("id") or "",
        "title": _strip(data.get("title") or "Conversa"),
        "profile": data.get("profile") or "",
        "model": data.get("model") or "",
        "project": data.get("project") or "",
        "summary": _strip(data.get("summary") or ""),
        "pinned_prompt": _strip(data.get("pinned_prompt") or ""),
        "goal": _strip(data.get("goal") or ""),
        "pinned_title": bool(data.get("pinned_title")),
        "messages": messages,
    }
    return {"format": FORMAT_CONVERSATION, "version": VERSION, "conversation": body}


def conversation_markdown(data: dict) -> str:
    package = data if data.get("format") == FORMAT_CONVERSATION else export_conversation(data)
    conversation = package["conversation"]
    lines = [f"# {conversation.get('title') or 'Conversa'}", ""]
    names = {"user": "Você", "assistant": "Órbita", "tool": "Ferramenta", "system": "Sistema"}
    for message in conversation.get("messages") or []:
        lines.append(f"## {names.get(message.get('role'), message.get('role'))}")
        lines.append(str(message.get("content") or ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _same_messages(left: list, right: list) -> bool:
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if (a.get("role"), a.get("content"), a.get("name")) != (b.get("role"), b.get("content"), b.get("name")):
            return False
    return True


def import_conversation(store, payload: dict) -> str:
    """Grava a conversa como dado. Não chama ferramenta nem liga permissão."""
    _require(payload, FORMAT_CONVERSATION)
    raw = payload.get("conversation")
    if not isinstance(raw, dict):
        raise ValueError("O pacote não tem uma conversa.")
    exported = export_conversation(raw)["conversation"]
    wanted = str(exported.get("id") or "")
    for meta in store.list():
        current = store.load(meta["id"])
        if current and _same_messages(current.get("messages") or [], exported["messages"]) \
                and (current.get("title") or "") == (exported.get("title") or ""):
            return current["id"]
    if not _CONVERSATION_ID.match(wanted) or store.load(wanted):
        wanted = new_id()
    store.save({
        "id": wanted,
        "title": exported["title"] or "Conversa",
        "pinned_title": exported["pinned_title"],
        "pinned_prompt": exported["pinned_prompt"],
        "goal": exported["goal"],
        "profile": exported["profile"],
        "provider": "",
        "model": exported["model"],
        "project": exported["project"],
        "messages": exported["messages"],
        "summary": exported["summary"],
        "external_session": None,
    })
    return wanted


def export_profile(profile) -> dict:
    data = profile if isinstance(profile, dict) else {
        "id": profile.id, "name": profile.name, "icon": profile.icon, "description": profile.description,
        "system_prompt": profile.system_prompt, "startup_prompt": profile.startup_prompt,
        "auto_startup": profile.auto_startup, "provider": profile.provider, "model": profile.model,
        "temperature": profile.temperature, "max_tokens": profile.max_tokens, "effort": profile.effort,
        "workspace": profile.workspace, "tool_groups": list(profile.tool_groups),
        "mcp_servers": list(profile.mcp_servers), "max_steps": profile.max_steps,
        "in_team": profile.in_team, "skills_tags": list(profile.skills_tags),
    }
    return {"format": FORMAT_PROFILE, "version": VERSION, "profile": _strip(data)}


def _profile_body(data: dict) -> dict:
    """Campos conhecidos do perfil, sem id e sem chaves desconhecidas."""
    seed = dict(data)
    seed["id"] = "tmp"
    seed["name"] = data.get("name") or "tmp"
    body = export_profile(Profile.from_dict(seed))["profile"]
    body.pop("id", None)
    return body


def import_profile(manager, payload: dict) -> str:
    _require(payload, FORMAT_PROFILE)
    raw = payload.get("profile")
    if not isinstance(raw, dict):
        raise ValueError("O pacote não tem um perfil.")
    data = export_profile(raw)["profile"]
    if not data.get("name"):
        raise ValueError("O perfil precisa de um nome.")
    wanted_body = _profile_body(data)
    for profile in manager.list():
        if _profile_body(export_profile(profile)["profile"]) == wanted_body:
            return profile.id
    wanted = str(data.get("id") or "")
    if not re.fullmatch(r"[a-z0-9_\-]+", wanted) or wanted in manager.profiles:
        base = manager.slugify(str(data.get("name") or "perfil"))
        wanted = base
        number = 2
        while wanted in manager.profiles:
            wanted = f"{base}_{number}"
            number += 1
    data["id"] = wanted
    manager.save(Profile.from_dict(data))
    return wanted
