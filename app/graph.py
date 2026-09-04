"""The LangGraph state machine wiring the five agents together."""

import logging
import operator
import re
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.analyst import analyst_node
from app.agents.critic import critic_node
from app.agents.planner import planner_node
from app.agents.researcher import research_node
from app.agents.writer import writer_node

log = logging.getLogger("agentdesk.graph")

CITATION_RE = re.compile(r"\[([A-Za-z0-9_:.#/\-]+)\]")


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
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def resolve_citations(report: str, sources: dict) -> list[dict]:
    """Report the sources the finished report actually cites, in order of appearance.

    Derived from the report text rather than from the fact list, so the answer
    is what the reader can verify, not what the Writer was offered.
    """
    seen, citations = set(), []
    for source_id in CITATION_RE.findall(report or ""):
        if source_id in sources and source_id not in seen:
            seen.add(source_id)
            citations.append(sources[source_id])
    return citations


def run_agentdesk(question: str) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty")

    initial_state = {
        "question": question,
        "revision_count": 0,
        "research_rounds": 0,
        "trace": [],
    }
    result = dict(get_graph().invoke(initial_state))
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
