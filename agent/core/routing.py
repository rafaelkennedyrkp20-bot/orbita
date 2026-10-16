"""
routing.py — Escolhe o melhor modelo para cada especialidade.

Catálogo editável em `data/model_catalog.json`. Cada entrada casa com "provedor:modelo" por
padrão glob (a primeira que casar vale) e dá notas de 0 a 3 por especialidade, mais um custo
relativo (0 = local/grátis ... 3 = caro). Entradas com "ref" fixo descrevem modelos que não
aparecem na lista de chat (ex.: modelos de imagem).

    codigo · revisao · pesquisa · raciocinio · visao · imagem · geral

A escolha só considera modelos com acesso configurado (chave no .env, conta Grok logada ou
Ollama local) e pesa custo × qualidade conforme o modo de economia:
    maximo       o mais barato que resolve
    equilibrado  equilíbrio entre nota e custo
    livre        o melhor, quase sem olhar o custo
"""

from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path
from typing import Optional

from agent.core.config import DATA_DIR

logger = logging.getLogger(__name__)

CATALOG_FILE = DATA_DIR / "model_catalog.json"
SPECIALTIES = ["codigo", "revisao", "pesquisa", "raciocinio", "visao", "imagem", "geral"]
SPECIALTY_LABELS = {"codigo": "código", "revisao": "revisão", "pesquisa": "pesquisa", "raciocinio": "raciocínio",
                    "visao": "visão", "imagem": "imagem", "geral": "geral"}
COST_WEIGHT = {"maximo": 1.2, "equilibrado": 0.5, "livre": 0.1}

# Perfis da equipe → especialidade usada quando o perfil não fixa um modelo.
PROFILE_SPECIALTY = {"programador": "codigo", "lider_dev": "codigo", "revisor": "revisao",
                     "pesquisador": "pesquisa", "engenharia_reversa": "raciocinio", "designer": "geral",
                     "automacao_pc": "visao", "grok_build": "codigo"}
TAG_SPECIALTY = {"código": "codigo", "codigo": "codigo", "testes": "codigo", "revisão": "revisao",
                 "segurança": "revisao", "pesquisa": "pesquisa", "documentação": "pesquisa",
                 "raciocínio": "raciocinio", "matemática": "raciocinio", "visão": "visao", "imagem": "imagem"}

DEFAULT_CATALOG: list[dict] = [
    # Modelos de imagem (não são de chat): usados pela ferramenta generate_image
    {"ref": "openai:gpt-image-1", "imagem": 3, "cost": 2, "only": "imagem"},
    {"ref": "openrouter:google/gemini-2.5-flash-image", "imagem": 3, "cost": 1, "only": "imagem"},
    # Locais (custo zero; qualidade depende do tamanho)
    {"match": "ollama:*27b*", "codigo": 2, "revisao": 2, "pesquisa": 2, "raciocinio": 2, "geral": 2, "cost": 0},
    {"match": "ollama:*32b*", "codigo": 2, "revisao": 2, "pesquisa": 2, "raciocinio": 2, "geral": 2, "cost": 0},
    {"match": "ollama:*vl*", "visao": 2, "geral": 1, "cost": 0},
    {"match": "ollama:*", "codigo": 1, "revisao": 1, "pesquisa": 1, "raciocinio": 1, "geral": 1, "cost": 0},
    # Nuvem
    {"match": "deepseek:deepseek-reasoner", "codigo": 3, "revisao": 3, "pesquisa": 2, "raciocinio": 3, "geral": 2, "cost": 1},
    {"match": "deepseek:*", "codigo": 3, "revisao": 2, "pesquisa": 2, "raciocinio": 2, "geral": 3, "cost": 1},
    {"match": "anthropic:claude-fable*", "codigo": 3, "revisao": 3, "pesquisa": 3, "raciocinio": 3, "visao": 3, "geral": 3, "cost": 3},
    {"match": "anthropic:claude-opus*", "codigo": 3, "revisao": 3, "pesquisa": 3, "raciocinio": 3, "visao": 3, "geral": 3, "cost": 3},
    {"match": "anthropic:claude-sonnet*", "codigo": 3, "revisao": 3, "pesquisa": 3, "raciocinio": 3, "visao": 3, "geral": 3, "cost": 2},
    {"match": "anthropic:claude-haiku*", "codigo": 2, "revisao": 2, "pesquisa": 2, "raciocinio": 2, "visao": 2, "geral": 2, "cost": 1},
    {"match": "openai:gpt-5-mini*", "codigo": 2, "revisao": 2, "pesquisa": 2, "raciocinio": 2, "visao": 2, "geral": 2, "cost": 1},
    {"match": "openai:gpt-5*", "codigo": 3, "revisao": 3, "pesquisa": 3, "raciocinio": 3, "visao": 3, "geral": 3, "cost": 2},
    {"match": "gemini:*flash*", "codigo": 2, "revisao": 2, "pesquisa": 2, "raciocinio": 2, "visao": 3, "geral": 2, "cost": 1},
    {"match": "gemini:*pro*", "codigo": 3, "revisao": 3, "pesquisa": 3, "raciocinio": 3, "visao": 3, "geral": 3, "cost": 2},
    # Grok Build é um agente completo; cada turno tem custo-base alto (~16k tokens)
    {"match": "grok:*", "codigo": 3, "revisao": 2, "pesquisa": 2, "raciocinio": 3, "geral": 2, "cost": 2},
    {"match": "*", "codigo": 1, "revisao": 1, "pesquisa": 1, "raciocinio": 1, "geral": 1, "cost": 1},
]


def load_catalog(path: Optional[Path] = None) -> list[dict]:
    """Lê o catálogo do usuário; cria o arquivo padrão na primeira vez."""
    path = path or CATALOG_FILE
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(DEFAULT_CATALOG, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            return list(DEFAULT_CATALOG)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else list(DEFAULT_CATALOG)
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("model_catalog.json inválido (%s); usando o padrão.", error)
        return list(DEFAULT_CATALOG)


def entry_for(ref: str, catalog: list[dict]) -> dict:
    for entry in catalog:
        if entry.get("ref") == ref or (entry.get("match") and fnmatch.fnmatchcase(ref.lower(), entry["match"].lower())):
            return entry
    return {"geral": 1, "cost": 1}


def candidate_refs(settings, current: Optional[tuple[str, str]] = None, catalog: Optional[list[dict]] = None,
                   local_models: Optional[list[str]] = None) -> list[str]:
    """Modelos utilizáveis agora: atual + locais instalados + provedores com acesso + refs fixos do catálogo."""
    refs: list[str] = [f"ollama:{model}" for model in local_models or []]
    providers = settings.providers()
    for name, cfg in providers.items():
        if name == "ollama" or not settings.has_credentials(name):
            continue
        # Provedores locais sem chave (LM Studio...) só entram se o usuário listou modelos
        refs += [f"{name}:{model}" for model in cfg.get("models", [])]
    if current and current[0] in providers:
        refs.insert(0, f"{current[0]}:{current[1]}")
    for entry in catalog or []:
        ref = entry.get("ref")
        if ref and ref.partition(":")[0] in providers and settings.has_credentials(ref.partition(":")[0]):
            refs.append(ref)
    return list(dict.fromkeys(refs))


def specialty_for(profile=None, explicit: str = "") -> str:
    if explicit in SPECIALTIES:
        return explicit
    if profile is not None:
        if profile.id in PROFILE_SPECIALTY:
            return PROFILE_SPECIALTY[profile.id]
        for tag in profile.skills_tags:
            if tag.lower() in TAG_SPECIALTY:
                return TAG_SPECIALTY[tag.lower()]
    return "geral"


def rank(specialty: str, refs: list[str], catalog: list[dict], mode: str = "equilibrado",
         prefer: str = "") -> list[tuple[float, str]]:
    """Ordena candidatos por pontuação (maior primeiro)."""
    weight = COST_WEIGHT.get(mode, 0.5)
    scored = []
    for ref in refs:
        entry = entry_for(ref, catalog)
        if entry.get("only") and entry["only"] != specialty:
            continue
        quality = entry.get(specialty, 0 if specialty in ("imagem", "visao") else entry.get("geral", 1))
        if quality <= 0:
            continue
        score = quality - weight * entry.get("cost", 1) + (0.05 if ref == prefer else 0)
        scored.append((round(score, 3), ref))
    scored.sort(key=lambda item: -item[0])
    return scored


def best(specialty: str, settings, current: Optional[tuple[str, str]] = None,
         local_models: Optional[list[str]] = None) -> Optional[str]:
    """O melhor 'provedor:modelo' para a especialidade, ou None se nada servir."""
    catalog = load_catalog()
    refs = candidate_refs(settings, current, catalog, local_models)
    prefer = f"{current[0]}:{current[1]}" if current else ""
    ranked = rank(specialty, refs, catalog, settings.get("economy_mode", "equilibrado"), prefer)
    return ranked[0][1] if ranked else None


def table_text(settings, current: Optional[tuple[str, str]] = None, local_models: Optional[list[str]] = None,
               limit: int = 8) -> str:
    """Resumo compacto das capacidades dos modelos disponíveis (para o prompt do agente principal)."""
    catalog = load_catalog()
    refs = [r for r in candidate_refs(settings, current, catalog, local_models)
            if not entry_for(r, catalog).get("only")]
    lines = []
    for ref in refs[:limit]:
        entry = entry_for(ref, catalog)
        strong = [SPECIALTY_LABELS[s] for s in SPECIALTIES if entry.get(s, 0) >= 3]
        good = [SPECIALTY_LABELS[s] for s in SPECIALTIES if entry.get(s, 0) == 2]
        cost = "local/grátis" if entry.get("cost", 1) == 0 else "$" * entry.get("cost", 1)
        detail = (f"forte em {', '.join(strong)}" if strong else "") + \
                 (("; bom em " if strong else "bom em ") + ", ".join(good) if good else "")
        lines.append(f"- {ref} ({cost}): {detail or 'uso geral básico'}")
    return "\n".join(lines)
