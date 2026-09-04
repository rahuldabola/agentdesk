"""Control-flow tests: the graph is a state machine, so test it as one."""

from unittest.mock import patch

import pytest

from app.graph import (
    build_graph,
    merge_notes,
    resolve_citations,
    route_after_critic,
    stream_agentdesk,
)


def _default_nodes():
    return {
        "planner_node": lambda s: {
            "subtasks": ["s1"],
            "use_rag": True,
            "use_web": False,
            "trace": [{"node": "planner"}],
        },
        "research_node": lambda s: {
            "research_notes": [{"source_id": "rag:a#0", "content": "x"}],
            "sources": {"rag:a#0": {"source_id": "rag:a#0"}},
            "trace": [{"node": "researcher"}],
        },
        "analyst_node": lambda s: {"facts": [], "trace": [{"node": "analyst"}]},
        "writer_node": lambda s: {"draft_report": "Report v1", "trace": [{"node": "writer"}]},
        "critic_node": lambda s: {
            "critic_verdict": "pass",
            "final_report": "Report v1",
            "status": "passed",
            "trace": [{"node": "critic"}],
        },
    }


def _run(**overrides):
    nodes = _default_nodes()
    nodes.update(overrides)
    patches = [patch(f"app.graph.{name}", side_effect=fn) for name, fn in nodes.items()]
    for p in patches:
        p.start()
    try:
        return build_graph().invoke(
            {"question": "q", "revision_count": 0, "research_rounds": 0, "trace": []}
        )
    finally:
        for p in patches:
            p.stop()


def test_route_after_critic_prefers_finishing():
    assert route_after_critic({"final_report": "r", "missing_information": ["x"]}) == "done"


def test_route_after_critic_sends_evidence_gaps_to_research():
    assert route_after_critic({"missing_information": ["x"]}) == "research"


def test_route_after_critic_sends_everything_else_to_the_writer():
    assert route_after_critic({"missing_information": []}) == "revise"


def test_happy_path_visits_every_node_once():
    result = _run()

    assert result["final_report"] == "Report v1"
    assert [t["node"] for t in result["trace"]] == [
        "planner",
        "researcher",
        "analyst",
        "writer",
        "critic",
    ]


def test_a_rewrite_loop_reruns_only_the_writer():
    calls = {"critic": 0, "research": 0}

    def critic(state):
        calls["critic"] += 1
        if calls["critic"] == 1:
            return {
                "critic_verdict": "revise",
                "critic_feedback": "tighten it",
                "revision_count": 1,
                "missing_information": [],
                "trace": [{"node": "critic"}],
            }
        return {
            "critic_verdict": "pass",
            "final_report": state["draft_report"],
            "status": "passed",
            "trace": [{"node": "critic"}],
        }

    def research(state):
        calls["research"] += 1
        return {"research_notes": [], "trace": [{"node": "researcher"}]}

    def writer(state):
        version = state.get("revision_count", 0) + 1
        return {"draft_report": f"Report v{version}", "trace": [{"node": "writer"}]}

    result = _run(critic_node=critic, research_node=research, writer_node=writer)

    assert calls == {"critic": 2, "research": 1}
    assert result["final_report"] == "Report v2"


def test_an_evidence_gap_reruns_research_and_analysis():
    calls = {"critic": 0, "research": 0, "analyst": 0}

    def critic(state):
        calls["critic"] += 1
        if calls["critic"] == 1:
            return {
                "critic_verdict": "revise",
                "missing_information": ["gap"],
                "pending_subtasks": ["gap"],
                "trace": [{"node": "critic"}],
            }
        return {
            "critic_verdict": "pass",
            "final_report": state["draft_report"],
            "status": "passed",
            "missing_information": [],
            "trace": [{"node": "critic"}],
        }

    def research(state):
        calls["research"] += 1
        note_id = "rag:r{}".format(calls["research"])
        return {
            "research_notes": [{"source_id": note_id, "content": "c"}],
            "research_rounds": calls["research"] - 1,
            "trace": [{"node": "researcher"}],
        }

    def analyst(state):
        calls["analyst"] += 1
        return {"facts": [], "trace": [{"node": "analyst"}]}

    result = _run(critic_node=critic, research_node=research, analyst_node=analyst)

    assert calls["research"] == 2, "the evidence gap must trigger a second research round"
    assert calls["analyst"] == 2, "new evidence must be re-analysed before rewriting"
    # The reducer must accumulate notes across rounds rather than overwrite them.
    assert len(result["research_notes"]) == 2


def test_the_graph_terminates_when_the_critic_never_passes():
    """Both loops are capped, so an unhappy Critic cannot spin forever."""
    calls = {"critic": 0}

    def critic(state):
        calls["critic"] += 1
        revisions = state.get("revision_count", 0)
        if revisions >= 2:
            return {
                "critic_verdict": "revise",
                "final_report": state["draft_report"],
                "status": "revision_limit_reached",
                "trace": [{"node": "critic"}],
            }
        return {
            "critic_verdict": "revise",
            "revision_count": revisions + 1,
            "missing_information": [],
            "trace": [{"node": "critic"}],
        }

    result = _run(critic_node=critic)

    assert result["status"] == "revision_limit_reached"
    assert calls["critic"] == 3


def test_merge_notes_deduplicates_by_source_id():
    a = [{"source_id": "x", "content": "1"}]
    b = [{"source_id": "x", "content": "2"}, {"source_id": "y", "content": "3"}]

    assert [n["source_id"] for n in merge_notes(a, b)] == ["x", "y"]


def test_resolve_citations_reports_what_the_report_actually_cites():
    sources = {"web:1": {"source_id": "web:1"}, "rag:a#0": {"source_id": "rag:a#0"}}
    report = "Claim one [rag:a#0]. Claim two [web:1]. Repeat [rag:a#0]. Bogus [web:9]."

    assert resolve_citations(report, sources) == [sources["rag:a#0"], sources["web:1"]]


def test_resolve_citations_is_empty_for_an_uncited_report():
    assert resolve_citations("No citations here.", {"web:1": {}}) == []


# --- streaming ----------------------------------------------------------------


def _stream(**overrides):
    nodes = _default_nodes()
    nodes.update(overrides)
    patches = [patch(f"app.graph.{name}", side_effect=fn) for name, fn in nodes.items()]
    for p in patches:
        p.start()
    try:
        return list(stream_agentdesk("a question"))
    finally:
        for p in patches:
            p.stop()


def test_streaming_emits_each_node_once_then_the_finished_report():
    events = _stream()

    kinds = [kind for kind, _ in events]
    assert kinds == ["progress"] * 5 + ["report"]
    assert [payload["node"] for kind, payload in events if kind == "progress"] == [
        "planner",
        "researcher",
        "analyst",
        "writer",
        "critic",
    ]

    _, result = events[-1]
    assert result["final_report"] == "Report v1"
    assert result["status"] == "passed"


def test_streaming_does_not_replay_trace_entries_across_a_loop():
    """Each node's progress event must be emitted exactly once, loops included."""
    calls = {"critic": 0}

    def critic(state):
        calls["critic"] += 1
        if calls["critic"] == 1:
            return {
                "critic_verdict": "revise",
                "revision_count": 1,
                "missing_information": [],
                "trace": [{"node": "critic"}],
            }
        return {
            "critic_verdict": "pass",
            "final_report": state["draft_report"],
            "status": "passed",
            "trace": [{"node": "critic"}],
        }

    events = _stream(critic_node=critic)
    progress = [payload["node"] for kind, payload in events if kind == "progress"]

    # planner, researcher, analyst, writer, critic, writer, critic - no repeats
    # of already-emitted entries when the state is re-yielded.
    assert progress == [
        "planner",
        "researcher",
        "analyst",
        "writer",
        "critic",
        "writer",
        "critic",
    ]
    assert len([k for k, _ in events if k == "report"]) == 1


def test_streaming_rejects_an_empty_question_before_running():
    with pytest.raises(ValueError, match="must not be empty"):
        list(stream_agentdesk("  "))
