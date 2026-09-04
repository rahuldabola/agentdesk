"""Researcher: runs the plan's subtasks through the MCP tools and registers sources.

This node owns the citation namespace. Tools return their own natural keys
(a Chroma doc id, a URL); the Researcher maps those onto short, stable
source_ids (`rag:handbook.md#2`, `web:1`) that are readable inside a report,
and keeps a `sources` registry so every id can be resolved back to a real
file or URL when the report is served.
"""

import asyncio
import logging

from app.agents.base import node
from app.config import get_settings
from app.mcp.client import call_tool, mcp_session

log = logging.getLogger("agentdesk.researcher")


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
    if not (snippet or title):
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
    return {
        "source_id": source_id,
        "source_type": "web",
        "content": f"{title}: {snippet}".strip(": "),
    }


async def _gather(subtasks: list[str], use_rag: bool, use_web: bool) -> list[tuple]:
    """Issue every (subtask, tool) call concurrently over one session.

    Results come back in request order, so source numbering stays deterministic
    for a given plan regardless of which network call finishes first.
    """
    settings = get_settings()
    limit = asyncio.Semaphore(settings.max_concurrent_tool_calls)

    async def guarded(session, tool, args):
        async with limit:
            return await call_tool(session, tool, args)

    async with mcp_session() as session:
        planned = []
        for subtask in subtasks:
            if use_rag:
                planned.append(
                    (
                        "rag",
                        subtask,
                        guarded(
                            session, "rag_search", {"query": subtask, "k": settings.retrieval_k}
                        ),
                    )
                )
            if use_web:
                planned.append(
                    (
                        "web",
                        subtask,
                        guarded(
                            session,
                            "web_search",
                            {"query": subtask, "max_results": settings.web_results},
                        ),
                    )
                )
        payloads = await asyncio.gather(*(p[2] for p in planned), return_exceptions=True)

    return [
        (kind, subtask, payload)
        for (kind, subtask, _), payload in zip(planned, payloads, strict=True)
    ]


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
    pairs = asyncio.run(_gather(subtasks, use_rag, use_web))
    notes, failures = assemble_notes(pairs, sources, index_web_sources(sources))

    round_label = f"follow-up round {state.get('research_rounds', 0) + 1}" if pending else "initial"
    detail = (
        f"{round_label}: {len(notes)} notes from {len(subtasks)} subtask(s), "
        f"{len(sources)} source(s)"
    )
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
