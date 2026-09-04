"""Tool implementations behind the MCP server.

Both tools return a JSON document rather than prose. The caller needs the
source identity of every passage to cite it, and recovering structure from a
formatted string by splitting on blank lines is lossy the moment a passage
contains one - which markdown passages routinely do.
"""

import json
import logging
import os

import requests
from bs4 import BeautifulSoup

from app.config import get_settings
from app.rag.retriever import rag_search as _rag_search

log = logging.getLogger("agentdesk.tools")

TAVILY_URL = "https://api.tavily.com/search"
DDG_URL = "https://html.duckduckgo.com/html/"


def _payload(results: list[dict], provider: str, error: str | None = None) -> str:
    doc: dict = {"provider": provider, "results": results}
    if error:
        doc["error"] = error
    return json.dumps(doc, ensure_ascii=False)


def _tavily_search(query: str, max_results: int, timeout: float) -> list[dict]:
    resp = requests.post(
        TAVILY_URL,
        json={"query": query, "max_results": max_results},
        headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
        }
        for r in resp.json().get("results", [])[:max_results]
    ]


def _duckduckgo_search(query: str, max_results: int, timeout: float) -> list[dict]:
    resp = requests.get(
        DDG_URL,
        params={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (compatible; AgentDesk/1.0)"},
        timeout=timeout,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for block in soup.select(".result__body")[:max_results]:
        title_el = block.select_one(".result__a")
        if not title_el:
            continue
        snippet_el = block.select_one(".result__snippet")
        results.append(
            {
                "title": title_el.get_text(strip=True),
                "url": title_el.get("href", ""),
                "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
            }
        )
    return results


def web_search_impl(query: str, max_results: int | None = None) -> str:
    """Search the public web. Tavily when a key is set, else a DuckDuckGo HTML scrape."""
    settings = get_settings()
    max_results = settings.web_results if max_results is None else max_results
    timeout = settings.tool_timeout
    errors = []

    if os.environ.get("TAVILY_API_KEY"):
        try:
            results = _tavily_search(query, max_results, timeout)
            if results:
                return _payload(results, "tavily")
        except Exception as exc:
            # Fall through to the scrape rather than reporting the error as a result.
            log.warning("tavily search failed for %r: %s", query, exc)
            errors.append(f"tavily: {exc}")

    try:
        results = _duckduckgo_search(query, max_results, timeout)
        if results:
            return _payload(results, "duckduckgo")
        errors.append("duckduckgo: no results parsed from the response")
    except Exception as exc:
        log.warning("duckduckgo search failed for %r: %s", query, exc)
        errors.append(f"duckduckgo: {exc}")

    return _payload([], "none", error="; ".join(errors))


def rag_search_impl(query: str, k: int | None = None) -> str:
    """Search the local internal knowledge base for passages relevant to the query."""
    try:
        return _payload(_rag_search(query, k=k), "chroma")
    except Exception as exc:
        log.warning("rag search failed for %r: %s", query, exc)
        return _payload([], "chroma", error=str(exc))
