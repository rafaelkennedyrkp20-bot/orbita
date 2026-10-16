"""
teamwork.py — Quando e como a equipe trabalha: o ambiente avisa o modelo, ele decide.

O modelo nem sempre lembra que pode dividir o trabalho. Antes de cada pedido, o ambiente estima o
tamanho da tarefa (partes listadas, "do zero", "completo", vários arquivos/telas...) e, se for grande,
coloca no prompt daquele turno uma sugestão concreta: quantos ajudantes, em que fases. Pedido pequeno
não recebe nada (não vale o custo de coordenar).

Também define quantos ajudantes rodam de verdade ao mesmo tempo: na nuvem, vários; com modelo local,
todos dividem a mesma placa, então mais de 2 só deixa tudo lento (o resto entra na fila).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BUILD = re.compile(r"\b(site|sistema|aplicativo|app|jogo|game|api|backend|front-?end|dashboard|painel|plataforma|"
                   r"loja|e-?commerce|crud|landing|portal|bot|extens[aã]o|biblioteca|servidor|projeto)\b", re.I)
SCOPE = re.compile(r"\b(completo|completa|inteiro|inteira|do zero|v[aá]rios|v[aá]rias|todas? as|todos os|cada|"
                   r"m[uú]ltiplos|m[oó]dulos|telas|p[aá]ginas|refator|migr|reescrev|documenta[çc][aã]o|testes)", re.I)
EXPLICIT = re.compile(r"\b(agentes?|equipe|time|em paralelo|ao mesmo tempo|ajudantes?|subagentes?)\b", re.I)
SMALL = re.compile(r"^\s*(o que|qual|quais|como|por ?que|quando|onde|explique|resuma|traduza|corrija o erro|"
                   r"me diga|liste)\b", re.I)
NUMBERED = re.compile(r"(?m)^\s*(?:\d+[.)-]|[-*•])\s+\S")
NUMBER_WORDS = {"dois": 2, "duas": 2, "três": 3, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8}
LOCAL = {"ollama", "lmstudio"}


@dataclass
class Estimate:
    size: str        # "pequena" | "media" | "grande"
    parts: int       # partes independentes estimadas
    helpers: int     # quantos ajudantes sugerir (0 = fazer sozinho)
    asked: bool      # a pessoa pediu agentes/equipe


def max_parallel(tier: str, provider: str, setting: int = 0) -> int:
    """Quantos ajudantes rodam ao mesmo tempo (os demais esperam na fila)."""
    if setting and setting > 0:
        return max(1, min(int(setting), 8))
    if (provider or "").lower() in LOCAL:
        return 2
    return {"frontier": 6, "standard": 4, "compact": 2}.get(tier, 4)


def _requested_count(text: str) -> int:
    match = re.search(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\s+(?:agentes?|ajudantes?|partes|subagentes?)",
                      text, re.I)
    if not match:
        return 0
    word = match.group(1).lower()
    return int(word) if word.isdigit() else NUMBER_WORDS.get(word, 0)


def estimate(text: str, cap: int) -> Estimate:
    text = text or ""
    asked = bool(EXPLICIT.search(text))
    requested = _requested_count(text)
    words = len(text.split())
    listed = len(NUMBERED.findall(text))
    commas = len(re.findall(r",\s*(?:e\s+)?|\s+e\s+(?:o|a|os|as|um|uma)\s", text))
    score = 0
    score += 2 if BUILD.search(text) else 0
    score += 1 if SCOPE.search(text) else 0
    score += 1 if words > 60 else 0
    score += 2 if words > 160 else 0
    score += 2 if listed >= 3 else (1 if listed == 2 else 0)
    score += 1 if commas >= 3 else 0
    if SMALL.search(text) and not asked and words < 40:
        score = min(score, 1)
    parts = max(listed, requested, min(commas + 1, 6) if score >= 3 else 1)
    if requested:
        size = "grande" if requested >= 3 else "media"
    elif score >= 5 or (score >= 3 and parts >= 4):
        size = "grande"
    elif score >= 3 or asked:
        size = "media"
    else:
        size = "pequena"
    helpers = 0
    if size == "grande":
        helpers = min(max(parts, 3), max(cap, 1) * 2, 8)
    elif size == "media":
        helpers = min(max(parts, 2), 3)
    if requested:
        helpers = min(requested, 8)
    return Estimate(size, parts, helpers, asked or bool(requested))


def turn_hint(text: str, tier: str, cap: int) -> str:
    """Sugestão do ambiente para este pedido (vazio se for pequeno)."""
    e = estimate(text, cap)
    if e.size == "pequena" or e.helpers < 2:
        return ""
    if e.size == "media" and not e.asked:
        return ""   # medido: em tarefa média a equipe custa ~10x mais tokens e não termina antes
    if tier == "compact" and not e.asked:
        return ""   # modelo local pequeno se perde coordenando equipe; só se a pessoa pedir
    waves = "" if e.helpers <= cap else f" Eles rodam {cap} por vez; os demais entram na fila automaticamente."
    return ("## Sugestão do ambiente para este pedido\n"
            f"Tarefa {e.size} (~{e.parts} partes). Considere dividir entre {e.helpers} ajudantes com delegate_task."
            f"{waves} Fluxo recomendado:\n"
            "1. Fase 1 — você mesmo: entenda o pedido, defina o contrato (nomes, arquivos, interfaces) ou crie o "
            "esqueleto.\n"
            "2. Fase 2 — equipe: uma chamada delegate_task com as partes independentes e o mesmo `contract`; cada "
            "parte com seus `files` e critérios de aceite.\n"
            "3. Fase 3 — você: integre, corrija o que a checagem de integração apontar e faça UMA verificação "
            "proporcional (sites: check_web_page com width=390 para o celular). Corrija erros reais (JS, links, "
            "vazamento) e encerre; não persiga detalhe de pixel nem instale ferramentas de teste.\n"
            "Custo medido no Órbita: num site de 4 páginas, um agente sozinho levou ~1 min e ~80 mil tokens; com 4 "
            "ajudantes, ~9 min e ~1,2 milhão (resultado mais caprichado). Dividir compensa quando cada parte é "
            "grande e independente (backend + frontend + testes, vários módulos, muitas telas); para arquivos "
            "pequenos ou partes que dependem umas das outras, faça sozinho."
            + (" O usuário pediu trabalho em equipe: atenda." if e.asked else ""))
