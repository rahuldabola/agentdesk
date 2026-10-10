"""Researcher: runs the plan's subtasks through the MCP tools and registers sources.

This node owns the citation namespace. Tools return their own natural keys
(a Chroma doc id, a URL); the Researcher maps those onto short, stable
source_ids (`rag:handbook.md#2`, `web:1`) that are readable inside a report,
and keeps a `sources` registry so every id can be resolved back to a real
file or URL when the report is served.

Inside the node two specialist lanes run concurrently over one MCP session:

* the internal lane searches the knowledge base and, for a query that came back
  empty, rewords it once in the vocabulary a policy or engineering doc would use;
* the web lane searches the web and then reads the top results in full, since a
  two-sentence snippet is thin evidence.

Both degrade quietly: a failed rewrite or page fetch leaves the original
snippet-level result in place rather than failing the run.
"""

import asyncio
import logging

from app.agents.base import node
from app.config import agent_model, get_settings
from app.llm.gemini_client import structured_call
from app.mcp.client import call_tool, mcp_session

log = logging.getLogger("agentdesk.researcher")

REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One reworded query per input query, in the same order",
        }
    },
    "required": ["queries"],
}

REWRITE_SYSTEM = (
    "You are the internal Researcher. These search queries returned nothing from the "
    "company's knowledge base, which holds engineering handbooks, API documentation and "
    "security policies. Reword each one the way such a document would phrase it: expand "
    "abbreviations, drop conversational filler, prefer concrete nouns and the formal term "
    "for a thing. Keep the meaning exactly - do not broaden or change what is asked. Return "
    "one query per input, in the same order."
)


def _register_rag(result: dict, sources: dict) -> dict | None:
    content = (result.get("content") or "").strip()
    if not content:
        return None
    source_id = f"rag:{result['doc_id']}"
    sources.setdefault(
        source_id,
        {
            "source_id": source_id,
            "type": "rag",
            "file": result.get("file"),
            "chunk_index": result.get("chunk_index"),
            "score": result.get("score"),
        },
    )
    return {"source_id": source_id, "source_type": "rag", "content": content}


def _register_web(result: dict, sources: dict, url_index: dict) -> dict | None:
    snippet = (result.get("snippet") or "").strip()
    title = (result.get("title") or "").strip()
    url = (result.get("url") or "").strip()
    page_text = (result.get("page_text") or "").strip()
    if not (snippet or title or page_text):
        return None

    key = url or f"{title}|{snippet}"
    source_id = url_index.get(key)
    if source_id is None:
        source_id = f"web:{len(url_index) + 1}"
        url_index[key] = source_id
        sources[source_id] = {
            "source_id": source_id,
            "type": "web",
            "title": title,
            "url": url,
        }
    # The page text, when we could read it, subsumes the snippet.
    body = page_text or snippet
    return {
        "source_id": source_id,
        "source_type": "web",
        "content": f"{title}: {body}".strip(": "),
    }


def rewrite_queries(question: str, queries: list[str]) -> list[str]:
    """Reword `queries` for the knowledge base. Always returns one entry per input."""
    listed = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(queries))
    data = structured_call(
        system=REWRITE_SYSTEM,
        user_prompt=f"Original question: {question}\n\nQueries that found nothing:\n{listed}",
        tool_name="submit_queries",
        tool_description="Submit the reworded queries",
        input_schema=REWRITE_SCHEMA,
        max_tokens=512,
        model=agent_model("researcher"),
    )
    out = [q.strip() for q in data.get("queries") or [] if isinstance(q, str)]
    return [out[i] if i < len(out) and out[i] else q for i, q in enumerate(queries)]


def _is_empty(payload) -> bool:
    """A search that ran fine and found nothing - the only case a reword can fix."""
    return isinstance(payload, dict) and not payload.get("error") and not payload.get("results")


async def _internal_lane(session, subtasks, guarded, question, activity, deep) -> list[tuple]:
    settings = get_settings()

    async def search(queries):
        calls = (
            guarded(session, "rag_search", {"query": q, "k": settings.retrieval_k}) for q in queries
        )
        return await asyncio.gather(*calls, return_exceptions=True)

    queries = list(subtasks)
    payloads = list(await search(queries))

    empty = [i for i, p in enumerate(payloads) if _is_empty(p)]
    if empty and settings.query_rewrite and deep:
        try:
            reworded = await asyncio.to_thread(
                rewrite_queries, question, [queries[i] for i in empty]
            )
        except Exception as exc:
            # The rewrite is a bonus; the original (empty) result stands.
            log.warning("query rewrite failed: %s: %s", type(exc).__name__, exc)
            reworded = []
        retry = [
            (i, new)
            for i, new in zip(empty, reworded, strict=False)
            if new.strip().lower() != queries[i].strip().lower()
        ]
        if retry:
            retried = await search([new for _, new in retry])
            activity["rewritten"] = len(retry)
            for (i, new), payload in zip(retry, retried, strict=True):
                if not isinstance(payload, BaseException) and not _is_empty(payload):
                    queries[i], payloads[i] = new, payload
                    activity["recovered"] = activity.get("recovered", 0) + 1

    return [("rag", q, p) for q, p in zip(queries, payloads, strict=True)]


def _pages_to_read(payloads, limit: int) -> list[str]:
    """Distinct result URLs, best-ranked first across all subtasks, up to `limit`."""
    ranked = [
        (rank, order, r.get("url", ""))
        for order, p in enumerate(payloads)
        if isinstance(p, dict)
        for rank, r in enumerate(p.get("results", []))
    ]
    urls: list[str] = []
    for _, _, url in sorted(ranked):
        if len(urls) >= limit:
            break
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    return urls


async def _web_lane(session, subtasks, guarded, activity, deep) -> list[tuple]:
    settings = get_settings()
    searches = (
        guarded(session, "web_search", {"query": q, "max_results": settings.web_results})
        for q in subtasks
    )
    payloads = await asyncio.gather(*searches, return_exceptions=True)

    urls = _pages_to_read(payloads, settings.fetch_pages if deep else 0)
    if urls:
        fetches = (
            guarded(session, "fetch_page", {"url": u, "max_chars": settings.fetch_max_chars})
            for u in urls
        )
        pages = await asyncio.gather(*fetches, return_exceptions=True)
        text_by_url = {
            u: page["text"]
            for u, page in zip(urls, pages, strict=True)
            if isinstance(page, dict) and page.get("text") and not page.get("error")
        }
        for payload in payloads:
            if isinstance(payload, dict):
                for result in payload.get("results", []):
                    if result.get("url") in text_by_url:
                        result["page_text"] = text_by_url[result["url"]]
        activity["pages_read"] = len(text_by_url)
        activity["pages_failed"] = len(urls) - len(text_by_url)

    return [("web", q, p) for q, p in zip(subtasks, payloads, strict=True)]


async def _gather(
    subtasks: list[str], use_rag: bool, use_web: bool, question: str, deep: bool = True
) -> tuple[list[tuple], dict]:
    """Run the internal and web lanes concurrently over one session.

    Pairs come back lane by lane in request order, so source numbering stays
    deterministic for a given plan regardless of which network call finishes first.
    """
    settings = get_settings()
    limit = asyncio.Semaphore(settings.max_concurrent_tool_calls)
    activity: dict = {}

    async def guarded(session, tool, args):
        async with limit:
            return await call_tool(session, tool, args)

    async with mcp_session() as session:
        lanes = []
        if use_rag:
            lanes.append(_internal_lane(session, subtasks, guarded, question, activity, deep))
        if use_web:
            lanes.append(_web_lane(session, subtasks, guarded, activity, deep))
        results = await asyncio.gather(*lanes)

    return [pair for lane in results for pair in lane], activity


def assemble_notes(pairs, sources: dict, url_index: dict) -> tuple[list[dict], list[str]]:
    """Turn raw tool payloads into notes, registering each source as it goes.

    Kept pure and separate from the async fetch above so the mapping logic -
    where citation identity is decided - can be tested directly on fixtures.
    """
    notes: list[dict] = []
    failures: list[str] = []

    for kind, subtask, payload in pairs:
        if isinstance(payload, BaseException):
            failures.append(f"{kind}({subtask[:40]}): {type(payload).__name__}")
            log.warning("%s tool call failed for %r: %s", kind, subtask, payload)
            continue
        if payload.get("error"):
            failures.append(f"{kind}: {payload['error'][:80]}")
        for result in payload.get("results", []):
            note = (
                _register_rag(result, sources)
                if kind == "rag"
                else _register_web(result, sources, url_index)
            )
            if note:
                notes.append(note)

    return notes, failures


def index_web_sources(sources: dict) -> dict:
    """Rebuild the url -> source_id map so a follow-up round reuses existing ids."""
    return {
        (meta.get("url") or f"{meta.get('title', '')}|"): source_id
        for source_id, meta in sources.items()
        if meta.get("type") == "web"
    }


def _activity_detail(activity: dict) -> str:
    detail = ""
    if activity.get("pages_read") or activity.get("pages_failed"):
        detail += f"; read {activity.get('pages_read', 0)} page(s) in full"
        if activity.get("pages_failed"):
            detail += f" ({activity['pages_failed']} unreadable)"
    if activity.get("rewritten"):
        n = activity["rewritten"]
        detail += (
            f"; reworded {n} empty {'query' if n == 1 else 'queries'} "
            f"({activity.get('recovered', 0)} recovered)"
        )
    return detail


@node("researcher")
def research_node(state: dict) -> dict:
    # A follow-up round researches only the gaps the Critic identified.
    pending = state.get("pending_subtasks") or []
    subtasks = pending or state.get("subtasks") or [state["question"]]
    use_rag = state.get("use_rag", True)
    use_web = state.get("use_web", False)

    if not (use_rag or use_web):
        return {
            "_detail": "planner selected no tools; no research performed",
            "research_notes": [],
            "pending_subtasks": [],
        }

    sources: dict = dict(state.get("sources") or {})
    deep = state.get("depth", "deep") != "quick"
    pairs, activity = asyncio.run(_gather(subtasks, use_rag, use_web, state["question"], deep))
    notes, failures = assemble_notes(pairs, sources, index_web_sources(sources))

    round_label = f"follow-up round {state.get('research_rounds', 0) + 1}" if pending else "initial"
    detail = (
        f"{round_label}: {len(notes)} notes from {len(subtasks)} subtask(s), "
        f"{len(sources)} source(s)"
    ) + _activity_detail(activity)
    if failures:
        detail += f"; degraded: {'; '.join(failures)}"

    update = {
        "_detail": detail,
        "research_notes": notes,  # merged + deduped by the graph's reducer
        "sources": sources,
        "pending_subtasks": [],
    }
    if pending:
        update["research_rounds"] = state.get("research_rounds", 0) + 1
    return update
