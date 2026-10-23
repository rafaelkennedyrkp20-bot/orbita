"""
capabilities.py — Quanta liberdade cada modelo recebe.

Modelos de ponta (Claude, GPT-5, Fable, Grok 4, Gemini Pro, DeepSeek...) trabalham melhor com
autonomia: mais passos e menos cerimônia. Modelos locais
pequenos se perdem com isso e rendem mais em "modo foco": uma coisa por vez, instruções curtas.
O nível só ajusta o prompt e o limite de passos; permissões continuam as do usuário.
"""

from __future__ import annotations

import re

FRONTIER = re.compile(
    r"claude|fable|gpt-5|gpt-4\.1(?!-(mini|nano))|(^|[/:-])o[134](-|$)|grok-[4-9]|gemini-(2\.5-pro|[3-9])"
    r"|deepseek-(v[3-9]|r1|reasoner|chat)|kimi-k2|kimi-k3($|\.1-pro)|qwen3-(max|coder-plus|235b)|glm-[4-9]\.[5-9]|glm-[5-9]"
    r"|mistral-large|llama-4-maverick|nemotron-.*(super|ultra)", re.I)
COMPACT_NAME = re.compile(r"(^|[^a-z])(mini|nano|lite|tiny|small)([^a-z]|$)", re.I)
PARAMS = re.compile(r"(\d+(?:\.\d+)?)\s*b(?![a-z])", re.I)
LOCAL_PROVIDERS = {"ollama", "lmstudio"}

FRONTIER_PROMPT = (
    "## Autonomia (modelo de ponta)\n"
    "Você tem liberdade para conduzir o trabalho de ponta a ponta: planeje, execute vários passos seguidos, "
    "corrija o que falhar e só pare quando estiver pronto e verificado. Não peça confirmação para passos óbvios; "
    "pergunte apenas decisões que mudam o resultado (ex.: tecnologia, custo, apagar algo).")
COMPACT_PROMPT = (
    "## Modo foco\n"
    "Faça uma coisa por vez: uma ferramenta por passo, confira o resultado e siga. Prefira passos pequenos e "
    "respostas curtas. Não delegue para outros agentes, a menos que o usuário peça.")


def model_params(model: str) -> float:
    """Bilhões de parâmetros escritos no nome (qwen3:14b, Llama-3.3-70B...); 0 se não houver."""
    found = [float(m) for m in PARAMS.findall(model or "")]
    found = [n for n in found if 0.5 <= n <= 2000]
    return max(found) if found else 0.0


def tier(provider: str, model: str) -> str:
    """'frontier' | 'standard' | 'compact'."""
    provider, model = (provider or "").lower(), model or ""
    if provider == "grok":   # Grok Build: agente externo de ponta
        return "frontier"
    if FRONTIER.search(model):
        return "frontier"
    params = model_params(model)
    if provider in LOCAL_PROVIDERS and (0 < params <= 14 or (not params and COMPACT_NAME.search(model))):
        return "compact"
    if COMPACT_NAME.search(model) or 0 < params <= 9:
        return "compact"
    return "standard"


# Janela de contexto por modelo (tokens), a primeira regra que casa vence. Claude: guia oficial da Anthropic
# (2026-10): da linha 4.6 em diante e o Haiku 5.5 têm 1M sem cabeçalho beta; Haiku 4.5 e anteriores, 200K.
CONTEXT_WINDOWS = [
    (re.compile(r"(^|/)kimi-k3($|\.1-pro(-highspeed)?$)", re.I), 1_000_000),
    (re.compile(r"claude-(3|haiku-4|(opus|sonnet)-4($|-\d{8}|[-.]?[0-5]($|[^0-9])))", re.I), 200_000),
    (re.compile(r"claude|fable|mythos", re.I), 1_000_000),
    (re.compile(r"gpt-4\.1", re.I), 1_047_576),
    (re.compile(r"gpt-5", re.I), 400_000),
    (re.compile(r"(^|[/:-])o[134](-|$)", re.I), 200_000),
    (re.compile(r"gemini", re.I), 1_048_576),
    (re.compile(r"grok-4(\.\d)?-fast", re.I), 2_000_000),
    (re.compile(r"grok", re.I), 256_000),
    (re.compile(r"llama-4", re.I), 1_000_000),
]
DEFAULT_CONTEXT = 128_000   # modelo de nuvem desconhecido: valor seguro na maioria das APIs
MAX_CONTEXT = 1_000_000     # teto do Órbita, mesmo quando o modelo aceita mais


def context_window(provider: str, model: str) -> int:
    """Quantos tokens de contexto o modelo aceita (estimativa pelo nome; desconhecido = 128K)."""
    return next((tokens for pattern, tokens in CONTEXT_WINDOWS if pattern.search(model or "")), DEFAULT_CONTEXT)


def step_multiplier(level: str) -> float:
    return {"frontier": 2.0, "compact": 1.0}.get(level, 1.0)


def prompt_section(level: str) -> str:
    if level == "frontier":
        return FRONTIER_PROMPT
    if level == "compact":
        return COMPACT_PROMPT
    return ""
