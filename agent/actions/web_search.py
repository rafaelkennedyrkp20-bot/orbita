"""Pesquisa pública na web e retorna fontes formatadas para o LLM."""

import logging
import ipaddress
import os
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
try:
    from ddgs import DDGS
except ImportError:  # Compatibilidade para instalações anteriores.
    from duckduckgo_search import DDGS

from agent.core.config import (
    WEB_RESEARCH_MAX_CHARS_PER_SITE,
    WEB_RESEARCH_MAX_SITES,
    WEB_RESEARCH_TIMEOUT_SECONDS,
    WEB_SEARCH_BACKEND,
    WEB_SEARCH_MAX_RESULTS,
)

logger = logging.getLogger(__name__)


def _search_results(query: str, max_results: int, region: str) -> list[dict]:
    """DuckDuckGo primeiro; Brave e Google configurados cobrem erro ou busca vazia."""
    limit = max(1, min(int(max_results), 100))
    failed = False
    for label, search in (
        ("DuckDuckGo", lambda: _ddgs_results(query, limit, region)),
        ("Brave", lambda: _brave_results(query, limit)),
        ("Google", lambda: _google_results(query, limit)),
    ):
        try:
            results = _unique_results(search(), limit)
        except Exception as error:
            # HTTPError pode trazer a URL inteira, inclusive a chave do Google.
            logger.warning("Busca %s indisponível (%s).", label, type(error).__name__)
            failed = True
            continue
        if results:
            return results
    if failed:
        raise RuntimeError("Serviços de busca indisponíveis. Confira a conexão e as credenciais configuradas.")
    return []


def _ddgs_results(query: str, limit: int, region: str) -> list[dict]:
    with DDGS() as ddgs:
        return list(ddgs.text(query, region=region, safesearch="moderate",
                              max_results=limit, backend=WEB_SEARCH_BACKEND))


def _brave_results(query: str, limit: int) -> list[dict]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    if not key:
        return []
    response = requests.get("https://api.search.brave.com/res/v1/web/search",
                            params={"q": query, "count": min(limit, 20)},
                            headers={"Accept": "application/json", "X-Subscription-Token": key},
                            timeout=WEB_RESEARCH_TIMEOUT_SECONDS, allow_redirects=False)
    response.raise_for_status()
    return [{"title": row.get("title"), "href": row.get("url"), "body": row.get("description")}
            for row in response.json().get("web", {}).get("results", []) if isinstance(row, dict)]


def _google_results(query: str, limit: int) -> list[dict]:
    key = os.environ.get("GOOGLE_SEARCH_API_KEY", "").strip()
    cx = os.environ.get("GOOGLE_SEARCH_CX", "").strip()
    if not key or not cx:
        return []
    response = requests.get("https://www.googleapis.com/customsearch/v1",
                            params={"key": key, "cx": cx, "q": query, "num": min(limit, 10)},
                            timeout=WEB_RESEARCH_TIMEOUT_SECONDS, allow_redirects=False)
    response.raise_for_status()
    return [{"title": row.get("title"), "href": row.get("link"), "body": row.get("snippet")}
            for row in response.json().get("items", []) if isinstance(row, dict)]


def _unique_results(raw_results: list[dict], limit: int) -> list[dict]:
    results, seen_urls = [], set()
    for result in raw_results:
        if not isinstance(result, dict):
            continue
        url = str(result.get("href") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen_urls:
            continue
        seen_urls.add(url)
        results.append({"title": str(result.get("title") or "Sem título"), "href": url,
                        "body": str(result.get("body") or "Sem descrição")})
        if len(results) >= limit:
            break
    return results


def web_search(query: str, max_results: int = None, region: str = "br-pt") -> str:
    """
    Realiza uma busca no DuckDuckGo e retorna resultados formatados.

    Args:
        query: Termo de busca.
        max_results: Número máximo de resultados (padrão: config).
        region: Região para resultados localizados (padrão: Brasil PT).

    Returns:
        String formatada com título, URL e resumo de cada resultado.
    """
    max_results = max_results or WEB_SEARCH_MAX_RESULTS
    logger.info(f"Pesquisando: '{query}' ({max_results} resultados)")

    try:
        results = _search_results(query, max_results, region)

        if not results:
            return f"Nenhum resultado encontrado para: '{query}'"

        formatted = []
        for r in results:
            title = r.get("title", "Sem título")
            url = r.get("href", "")
            body = r.get("body", "Sem descrição")[:500]
            formatted.append(f"Fonte {len(formatted) + 1}: {title}\nURL: {url}\nResumo: {body}")

        output = "\n\n".join(formatted)
        logger.debug(f"Busca retornou {len(results)} resultados.")
        return output

    except Exception as e:
        logger.error(f"Erro na busca web: {e}")
        return f"Erro ao pesquisar: {e}"


def _is_public_web_url(url: str) -> bool:
    """Bloqueia esquemas e endereços locais antes de baixar uma página."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, None)}
        return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)
    except (OSError, ValueError):
        return False


def _read_public_page(result: dict, max_chars: int = WEB_RESEARCH_MAX_CHARS_PER_SITE) -> Optional[dict]:
    """Extrai texto útil de uma fonte de busca pública, com limites rígidos."""
    url = result.get("href", "")
    if not _is_public_web_url(url):
        return None
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "AgentePessoal/1.0 (local research)"},
            timeout=WEB_RESEARCH_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
        if not response.ok or "text/html" not in response.headers.get("content-type", "").lower():
            return None
        if not _is_public_web_url(response.url):
            return None
        response.encoding = response.apparent_encoding or response.encoding
        soup = BeautifulSoup(response.text, "html.parser")
        for node in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
            node.decompose()
        paragraphs = [
            " ".join(node.get_text(" ", strip=True).split())
            for node in soup.select("article p, main p, p, li")
        ]
        # "article p, main p, p" casam o mesmo parágrafo várias vezes: remove repetições.
        text = "\n".join(dict.fromkeys(item for item in paragraphs if len(item) >= 50))
        if not text:
            return None
        return {
            "title": result.get("title", "Sem título"),
            "url": response.url,
            "text": text[:max_chars],
        }
    except Exception as error:
        logger.debug("Não foi possível ler %s: %s", url, error)
        return None


def web_research(query: str, region: str = "br-pt") -> str:
    """Busca e lê páginas públicas para fornecer evidência ao modelo local."""
    try:
        results = _search_results(query, WEB_SEARCH_MAX_RESULTS, region)
        if not results:
            return f"Nenhuma fonte encontrada para: '{query}'"

        sources_by_rank = {}
        with ThreadPoolExecutor(max_workers=WEB_RESEARCH_MAX_SITES) as executor:
            futures = {
                executor.submit(_read_public_page, result): rank
                for rank, result in enumerate(results[:WEB_RESEARCH_MAX_SITES])
            }
            for future in as_completed(futures):
                source = future.result()
                if source:
                    sources_by_rank[futures[future]] = source

        sources = [sources_by_rank[rank] for rank in sorted(sources_by_rank)]

        if not sources:
            return "A busca encontrou resultados, mas as páginas não puderam ser lidas.\n\n" + web_search(query, region=region)

        formatted = []
        for index, source in enumerate(sources, 1):
            formatted.append(
                f"FONTE {index}: {source['title']}\nURL: {source['url']}\nCONTEÚDO EXTRAÍDO:\n{source['text']}"
            )
        return "\n\n---\n\n".join(formatted)
    except Exception as error:
        logger.error("Erro na pesquisa aprofundada: %s", error)
        return f"Erro ao pesquisar e ler fontes: {error}"


def web_search_news(query: str, max_results: int = 5) -> str:
    """
    Busca notícias recentes sobre um tema.

    Args:
        query: Termo de busca.
        max_results: Número máximo de notícias.

    Returns:
        String com as notícias encontradas.
    """
    logger.info(f"Buscando notícias: '{query}'")

    try:
        with DDGS() as ddgs:
            results = list(ddgs.news(
                query,
                region="br-pt",
                safesearch="moderate",
                max_results=max_results,
            ))

        if not results:
            return f"Nenhuma notícia encontrada para: '{query}'"

        formatted = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "Sem título")
            url = r.get("url", "")
            date = r.get("date", "")
            source = r.get("source", "")
            body = r.get("body", "")[:200]
            formatted.append(
                f"{i}. **{title}** ({source} — {date})\n   {url}\n   {body}"
            )

        return "\n\n".join(formatted)

    except Exception as e:
        logger.error(f"Erro na busca de notícias: {e}")
        return f"Erro ao buscar notícias: {e}"


def fetch_page(url: str, max_chars: int = 12000) -> str:
    """Lê uma página pública e devolve o texto principal (para a ferramenta fetch_url)."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    page = _read_public_page({"href": url, "title": url}, max_chars=max_chars)
    if not page:
        return f"Não foi possível ler texto de {url} (bloqueada, sem HTML, endereço local ou sem conteúdo)."
    return f"TÍTULO/URL: {page['url']}\n\n{page['text']}"
