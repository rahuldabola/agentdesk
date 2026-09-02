import os

import requests
from bs4 import BeautifulSoup

from app.rag.retriever import rag_search as _rag_search


def web_search_impl(query: str, max_results: int = 4) -> str:
    """Search the public web. Prefers Tavily if TAVILY_API_KEY is set, else scrapes DuckDuckGo HTML."""
    tavily_key = os.environ.get("TAVILY_API_KEY")
    results = []

    if tavily_key:
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": tavily_key, "query": query, "max_results": max_results},
                timeout=10,
            )
            resp.raise_for_status()
            for r in resp.json().get("results", [])[:max_results]:
                results.append(f"- {r['title']}: {r['content']} ({r['url']})")
        except Exception as e:
            results.append(f"[tavily_error] {e}")

    if not results:
        try:
            resp = requests.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for r in soup.select(".result__body")[:max_results]:
                title_el = r.select_one(".result__a")
                snippet_el = r.select_one(".result__snippet")
                if title_el:
                    title = title_el.get_text(strip=True)
                    url = title_el.get("href", "")
                    snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                    results.append(f"- {title}: {snippet} ({url})")
        except Exception as e:
            results.append(f"[duckduckgo_error] {e}")

    return "\n".join(results) if results else "No results found."


def rag_search_impl(query: str, k: int = 4) -> str:
    """Search the local internal knowledge base (engineering/policy docs) for relevant passages."""
    notes = _rag_search(query, k=k)
    if not notes:
        return "No relevant internal documents found."
    return "\n\n".join(f"[{n['source_id']}] {n['content']}" for n in notes)
