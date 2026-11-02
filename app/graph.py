"""The LangGraph state machine wiring the six agents together."""

import logging
import operator
import re
import threading
import uuid
from collections.abc import Iterator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agents.analyst import analyst_node
from app.agents.critic import critic_node
from app.agents.planner import planner_node
from app.agents.researcher import research_node
from app.agents.synthesizer import synthesizer_node
from app.agents.writer import writer_node
from app.config import get_settings, resolve_depth
from app.persistence import get_checkpointer, get_run_store

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
    depth: str  # "quick" | "deep"; see app.config.resolve_depth
    review_plan: bool  # pause after planning for a human to approve or edit the plan

    # Plan
    question_type: str
    success_criteria: list[str]
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
    synthesis: dict
    draft_report: str

    # Critique
    critic_verdict: str
    critic_feedback: str
    unsupported_claims: list[str]
    uncovered_criteria: list[str]
    contradictions: list[str]
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


def build_graph(checkpointer=None):
    """Wire the agents. With a checkpointer, every node's output is persisted per
    run (thread), which is what makes runs resumable and pausable for review."""
    graph = StateGraph(AgentState)
    graph.add_node("plan", planner_node)
    graph.add_node("review_plan", review_plan_node)
    graph.add_node("research", research_node)
    graph.add_node("analyze", analyst_node)
    graph.add_node("synthesize", synthesizer_node)
    graph.add_node("write", writer_node)
    graph.add_node("critique", critic_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "review_plan")
    graph.add_edge("review_plan", "research")
    graph.add_edge("research", "analyze")
    graph.add_edge("analyze", "synthesize")
    graph.add_edge("synthesize", "write")
    graph.add_edge("write", "critique")
    graph.add_conditional_edges(
        "critique",
        route_after_critic,
        {"revise": "write", "research": "research", "done": END},
    )
    return graph.compile(checkpointer=checkpointer)


_graph = None


def get_graph():
    """Compile once and reuse; the node set never changes at runtime."""
    global _graph
    if _graph is None:
        _graph = build_graph(checkpointer=get_checkpointer())
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


# --- Runs: durable, resumable, optionally paused for a human -----------------


class RunNotFound(LookupError):
    """No run with that id exists."""


class RunConflict(RuntimeError):
    """The run exists but cannot do what was asked in its current state."""


# Runs whose graph is executing in this process right now. A row stuck at
# "running" that is *not* in this set was orphaned by a crash or a redeploy,
# and is safe to resume from its last checkpoint.
_active_runs: set[str] = set()
# Executing runs someone asked to stop; honoured at the next node boundary.
_cancel_requests: set[str] = set()
_active_lock = threading.Lock()


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def _initial_state(question: str, depth: str | None = None, review_plan: bool = False) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValueError("question must not be empty")
    return {
        "question": question,
        "depth": resolve_depth(depth),
        "review_plan": bool(review_plan),
        "revision_count": 0,
        "research_rounds": 0,
        "trace": [],
    }


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


def _pending_review(snapshot) -> dict | None:
    """The plan a paused run is waiting on a human to approve, if any."""
    for task in snapshot.tasks or ():
        for pending in getattr(task, "interrupts", ()) or ():
            return dict(pending.value)
    return None


def _claim(run_id: str) -> None:
    with _active_lock:
        if run_id in _active_runs:
            raise RunConflict(f"run {run_id} is already executing")
        _active_runs.add(run_id)


def _release(run_id: str) -> None:
    with _active_lock:
        _active_runs.discard(run_id)
        _cancel_requests.discard(run_id)


def _drive(run_id: str, graph_input) -> Iterator[tuple[str, dict]]:
    """Run (or continue) one thread to its next stopping point.

    Stops at one of three places: a finished report, a plan awaiting review,
    or an exception. The run index records which, so the run can be listed,
    inspected and resumed later.
    """
    graph = get_graph()
    config = _config(run_id)
    store = get_run_store()

    # On a resume, the restored state already carries earlier trace entries;
    # only entries produced from here on are news to the caller.
    emitted = len((graph.get_state(config).values or {}).get("trace", []))
    store.update(run_id, status="running", error=None)
    try:
        for state in graph.stream(graph_input, config, stream_mode="values"):
            if "__interrupt__" in state:  # the pause marker, not a state snapshot
                continue
            trace = state.get("trace", [])
            for entry in trace[emitted:]:
                yield "progress", entry
            emitted = len(trace)
            # Cooperative cancellation, checked at node boundaries: a node in
            # flight finishes (and is checkpointed), nothing after it starts.
            with _active_lock:
                cancelled = run_id in _cancel_requests
            if cancelled:
                store.update(run_id, status="cancelled")
                yield "cancelled", {"run_id": run_id}
                return
    except GeneratorExit:
        store.update(run_id, status="failed", error="stream closed before the run finished")
        raise
    except Exception as exc:
        store.update(run_id, status="failed", error=f"{type(exc).__name__}: {exc}")
        raise

    snapshot = graph.get_state(config)
    plan = _pending_review(snapshot)
    if plan is not None:
        store.update(run_id, status="awaiting_review")
        yield "plan_review", {"run_id": run_id, **plan}
        return

    result = finalize(snapshot.values)
    result["run_id"] = run_id
    store.update(
        run_id,
        status="completed",
        outcome=result["status"],
        citations=len(result["citations"]),
        revisions=result.get("revision_count", 0),
    )
    yield "report", result


def create_run(question: str, depth: str | None = None, review_plan: bool = False) -> str:
    """Validate the question and register a new run; nothing executes yet."""
    initial = _initial_state(question, depth, review_plan)
    run_id = uuid.uuid4().hex[:16]
    get_run_store().create(run_id, initial["question"], initial["depth"], initial["review_plan"])
    return run_id


def stream_run(run_id: str, graph_input) -> Iterator[tuple[str, dict]]:
    """Announce the run, then drive it. Holds the run's execution claim throughout."""
    _claim(run_id)
    try:
        yield "run", {"run_id": run_id}
        yield from _drive(run_id, graph_input)
    finally:
        _release(run_id)


def stream_agentdesk(
    question: str, depth: str | None = None, review_plan: bool = False
) -> Iterator[tuple[str, dict]]:
    """Start a run and stream it.

    Yields ("run", {"run_id"}) first, then ("progress", trace_entry) as each node
    finishes, then either ("report", result) or - when `review_plan` is set -
    ("plan_review", plan), after which the run waits for `resume_run`.
    """
    initial = _initial_state(question, depth, review_plan)
    run_id = create_run(initial["question"], initial["depth"], initial["review_plan"])
    yield from stream_run(run_id, initial)


def run_agentdesk(question: str, depth: str | None = None) -> dict:
    """Blocking, non-interactive run: returns the finished report."""
    for kind, payload in stream_agentdesk(question, depth):
        if kind == "report":
            return payload
    raise RuntimeError("the run ended without a report")


def clean_plan_edits(plan: dict, edits: dict | None) -> dict:
    """Turn a reviewer's (untrusted) plan edits into a safe state update.

    Anything omitted keeps the Planner's value. Blank entries are dropped, the
    subtask count is capped, and a plan cannot end up with no subtasks or with
    both tools switched off - the same invariants the Planner enforces.
    """
    edits = edits if isinstance(edits, dict) else {}
    limit = get_settings().max_plan_subtasks

    def _strings(value, cap: int) -> list[str] | None:
        if not isinstance(value, list):
            return None
        cleaned = [v.strip()[:300] for v in value if isinstance(v, str) and v.strip()]
        return cleaned[:cap] or None

    update: dict = {}
    subtasks = _strings(edits.get("subtasks"), limit)
    if subtasks is not None:
        update["subtasks"] = subtasks
    criteria = _strings(edits.get("success_criteria"), 12)
    if criteria is not None:
        update["success_criteria"] = criteria

    use_rag = edits.get("use_rag", plan.get("use_rag", True))
    use_web = edits.get("use_web", plan.get("use_web", False))
    if isinstance(use_rag, bool) and isinstance(use_web, bool) and (use_rag or use_web):
        update["use_rag"], update["use_web"] = use_rag, use_web
    return update


def review_plan_node(state: dict) -> dict:
    """Human-in-the-loop checkpoint between planning and research.

    A no-op unless the run asked for review. Otherwise `interrupt()` pauses the
    graph here, the checkpointer persists the paused state, and the run resumes
    when a reviewer sends `Command(resume=edits)` - possibly hours later, from
    another process. The node re-runs from the top on resume, so everything
    before `interrupt()` must be side-effect free (it is).

    Not wrapped in @node: the interrupt is control flow, not a failure, and the
    decorator would log it as one.
    """
    if not state.get("review_plan"):
        return {}

    plan = {
        "question": state.get("question"),
        "question_type": state.get("question_type"),
        "subtasks": state.get("subtasks", []),
        "success_criteria": state.get("success_criteria", []),
        "use_rag": state.get("use_rag", True),
        "use_web": state.get("use_web", False),
    }
    # The resume value is wrapped: LangGraph treats a falsy one (an empty
    # "approve with no edits" dict) as no resume at all, and would pause again.
    decision = interrupt(plan)
    edits = decision.get("edits") if isinstance(decision, dict) else None
    update = clean_plan_edits(plan, edits)

    changed = [k for k, v in update.items() if v != plan.get(k)]
    detail = f"edited {', '.join(changed)}" if changed else "approved as planned"
    update["trace"] = [{"node": "reviewer", "detail": detail, "elapsed_ms": 0.0}]
    return update


def resume_run(run_id: str, edits: dict | None = None) -> Iterator[tuple[str, dict]]:
    """Continue a paused or orphaned run from its last checkpoint.

    * awaiting_review: `edits` (possibly empty = approve as-is) resumes the
      interrupt with the reviewer's plan.
    * failed, or "running" but not executing in this process (crash, redeploy):
      re-enter the graph with no new input; finished nodes are not re-run.

    Validates eagerly (raises before returning the stream), so an API can map
    a bad request to a status code before any bytes are sent.
    """
    record = get_run_store().get(run_id)
    if record is None:
        raise RunNotFound(run_id)
    status = record["status"]
    with _active_lock:
        executing = run_id in _active_runs

    if status == "awaiting_review":
        graph_input = Command(resume={"edits": edits or {}})
    elif status == "failed" or (status == "running" and not executing):
        graph_input = None
    else:
        raise RunConflict(f"run {run_id} is {status} and cannot be resumed")
    return stream_run(run_id, graph_input)


def cancel_run(run_id: str) -> dict:
    """Stop a run. The checkpoint is kept for inspection.

    A paused, failed or orphaned run is cancelled on the spot. One executing in
    this process is asked to stop: it finishes its current node and halts
    before the next (`cancel_requested` in the reply; the status flips to
    "cancelled" moments later). Finished runs cannot be cancelled.
    """
    store = get_run_store()
    record = store.get(run_id)
    if record is None:
        raise RunNotFound(run_id)
    with _active_lock:
        executing = run_id in _active_runs
        if executing:
            _cancel_requests.add(run_id)
    if executing:
        return {**record, "cancel_requested": True}
    if record["status"] not in ("awaiting_review", "failed", "running"):
        raise RunConflict(f"run {run_id} is {record['status']} and cannot be cancelled")
    store.update(run_id, status="cancelled")
    return {**store.get(run_id), "cancel_requested": False}  # type: ignore[dict-item]


def get_run(run_id: str) -> dict:
    """The run's index row plus whatever its checkpoint can tell: plan, trace, result."""
    record = get_run_store().get(run_id)
    if record is None:
        raise RunNotFound(run_id)
    snapshot = get_graph().get_state(_config(run_id))
    values = snapshot.values or {}

    record["trace"] = values.get("trace", [])
    record["next"] = list(snapshot.next or ())
    record["pending_review"] = _pending_review(snapshot)
    record["result"] = finalize(values) if values.get("final_report") is not None else None
    record["plan"] = (
        {
            "question_type": values.get("question_type"),
            "subtasks": values.get("subtasks", []),
            "success_criteria": values.get("success_criteria", []),
            "use_rag": values.get("use_rag"),
            "use_web": values.get("use_web"),
        }
        if values.get("subtasks")
        else None
    )
    return record


def list_runs(limit: int = 50) -> list[dict]:
    return get_run_store().list(limit)


def delete_run(run_id: str) -> None:
    """Drop the run and its checkpoints. Refused while it is executing."""
    with _active_lock:
        if run_id in _active_runs:
            raise RunConflict(f"run {run_id} is executing")
    if not get_run_store().delete(run_id):
        raise RunNotFound(run_id)
    get_checkpointer().delete_thread(run_id)
