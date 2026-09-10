"""The LangGraph state machine wiring the five agents together."""

import logging
import operator
import re
from collections.abc import Iterator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.analyst import analyst_node
from app.agents.critic import critic_node
from app.agents.planner import planner_node
from app.agents.researcher import research_node
from app.agents.writer import writer_node

log = logging.getLogger("agentdesk.graph")

CITATION_RE = re.compile(r"\[([A-Za-z0-9_:.#/\-]+(?:\s*,\s*[A-Za-z0-9_:.#/\-]+)*)\]")


def extract_citation_ids(report: str) -> list[str]:
    """Every source_id cited in `report`, in order of appearance.

    The Writer is told to put one source_id per bracket, but a model
    occasionally packs several into one anyway (`[rag:a#0, web:1]`) - split
    those out too, so a formatting slip doesn't silently drop a citation.
    """
    ids = []
    for group in CITATION_RE.findall(report or ""):
        ids.extend(part.strip() for part in group.split(","))
    return ids


def merge_notes(existing: list, new: list) -> list:
    """Accumulate notes across research rounds, deduped by source_id."""
    merged = list(existing or [])
    seen = {n["source_id"] for n in merged}
    for note in new or []:
        if note["source_id"] not in seen:
            seen.add(note["source_id"])
            merged.append(note)
    return merged


def merge_sources(existing: dict, new: dict) -> dict:
    return {**(existing or {}), **(new or {})}


class AgentState(TypedDict, total=False):
    question: str

    # Plan
    subtasks: list[str]
    use_rag: bool
    use_web: bool

    # Research. Reducers make these accumulate across the research loop instead
    # of each round overwriting the last one's findings.
    research_notes: Annotated[list[dict], merge_notes]
    sources: Annotated[dict, merge_sources]
    pending_subtasks: list[str]
    research_rounds: int

    # Analysis and drafting
    facts: list[dict]
    draft_report: str

    # Critique
    critic_verdict: str
    critic_feedback: str
    unsupported_claims: list[str]
    missing_information: list[str]
    revision_count: int

    # Output
    final_report: str
    status: str
    citations: list[dict]

    trace: Annotated[list[dict], operator.add]


def route_after_critic(state: dict) -> str:
    """pass/limit -> finish, evidence gap -> research again, otherwise rewrite."""
    if state.get("final_report") is not None:
        return "done"
    if state.get("missing_information"):
        return "research"
    return "revise"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("plan", planner_node)
    graph.add_node("research", research_node)
    graph.add_node("analyze", analyst_node)
    graph.add_node("write", writer_node)
    graph.add_node("critique", critic_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "research")
    graph.add_edge("research", "analyze")
    graph.add_edge("analyze", "write")
    graph.add_edge("write", "critique")
    graph.add_conditional_edges(
        "critique",
        route_after_critic,
        {"revise": "write", "research": "research", "done": END},
    )
    return graph.compile()


_graph = None


def get_graph():
    """Compile once and reuse; the node set never changes at runtime."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def reset_graph() -> None:
    """Drop the compiled graph.

    A compiled StateGraph captures its node functions by reference at build
    time, so a cached graph would ignore later patching. Tests reset between
    cases to keep that cache from leaking across them.
    """
    global _graph
    _graph = None


def resolve_citations(report: str, sources: dict) -> list[dict]:
    """Report the sources the finished report actually cites, in order of appearance.

    Derived from the report text rather than from the fact list, so the answer
    is what the reader can verify, not what the Writer was offered.
    """
    seen, citations = set(), []
    for source_id in extract_citation_ids(report):
        if source_id in sources and source_id not in seen:
            seen.add(source_id)
            citations.append(sources[source_id])
    return citations


def _initial_state(question: str) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty")
    return {"question": question, "revision_count": 0, "research_rounds": 0, "trace": []}


def finalize(state: dict) -> dict:
    """Attach the resolved citations and a status to a finished run."""
    result = dict(state)
    result["citations"] = resolve_citations(
        result.get("final_report", ""), result.get("sources", {})
    )
    result.setdefault("status", "passed")
    log.info(
        "run complete: status=%s revisions=%d research_rounds=%d citations=%d",
        result["status"],
        result.get("revision_count", 0),
        result.get("research_rounds", 0),
        len(result["citations"]),
    )
    return result


def run_agentdesk(question: str) -> dict:
    return finalize(get_graph().invoke(_initial_state(question)))


def stream_agentdesk(question: str) -> Iterator[tuple[str, dict]]:
    """Yield ("progress", trace_entry) as each node finishes, then ("report", result).

    A full run takes tens of seconds; this lets a caller show the pipeline
    working rather than holding a blank connection open until the end.
    """
    emitted = 0
    state: dict = {}
    for state in get_graph().stream(_initial_state(question), stream_mode="values"):
        trace = state.get("trace", [])
        for entry in trace[emitted:]:
            yield "progress", entry
        emitted = len(trace)

    yield "report", finalize(state)
