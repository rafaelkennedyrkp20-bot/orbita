"""Destino dos dados nos fluxos gerenciados.

Um endereço em localhost não prova que a inferência é local. Só Ollama e
LM Studio (ou a mesma API na porta conhecida desses motores) em loopback
recebem o selo local. Terminal, web e MCP ficam de fora dessa promessa:
o Órbita não controla a saída deles.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from agent.core.local_engines import is_loopback_url

_CLOUD_TYPES = {"anthropic", "grok_cli"}
_KNOWN_PORTS = {11434, 1234}
_BLOCKED_TOOLS = {"run_shell", "web_search", "fetch_url"}
_BLOCKED = (
    "Modo somente local: esta ação pode sair do computador e o Órbita não "
    "controla o destino desses dados. Terminal, pesquisa na web e servidores "
    "MCP ficam bloqueados nesse modo. Downloads e atualizações do programa "
    "continuam sendo pedidos explícitos seus."
)


def local_only(settings) -> bool:
    return bool(settings) and settings.get("execution_policy") == "local_only"


def _port(url: str) -> int | None:
    try:
        return urlsplit(url).port
    except ValueError:
        return None


def data_destination(name: str, cfg: dict | None) -> str:
    """'local', 'cloud' ou 'unknown'. Nunca promove um gateway só por ser localhost."""
    cfg = cfg or {}
    kind = cfg.get("type") or ""
    url = (cfg.get("base_url") or "").strip()
    if not url and kind == "ollama":
        url = "http://127.0.0.1:11434"
    loopback = bool(url) and is_loopback_url(url)
    known_engine = kind == "ollama" or (name or "").lower() == "lmstudio" or (
        kind == "openai" and _port(url) in _KNOWN_PORTS
    )
    if known_engine and loopback:
        return "local"
    if kind in _CLOUD_TYPES or (url and not loopback):
        return "cloud"
    return "unknown"


def refusal(settings, name: str, cfg: dict | None, *, what: str = "esta conversa") -> str | None:
    """Mensagem que impede o envio, ou None quando o destino é permitido."""
    if not local_only(settings):
        return None
    destination = data_destination(name, cfg)
    if destination == "local":
        return None
    if destination == "cloud":
        where = "um serviço de nuvem"
    else:
        where = "um endereço local cujo destino da inferência não foi verificado"
    return (
        f"Modo somente local: {what} não foi enviada para {where} ({name}). "
        "Escolha Ollama ou LM Studio neste computador, ou desligue o modo em "
        "Configurações › Modelos."
    )


def tool_block(settings, tool) -> str | None:
    if not local_only(settings) or tool is None:
        return None
    source = getattr(tool, "source", "") or ""
    if source.startswith("mcp:") or getattr(tool, "name", "") in _BLOCKED_TOOLS:
        return _BLOCKED
    return None
