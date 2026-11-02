"""Cross-cutting behaviour: the node decorator, settings, ingest, and run_agentdesk."""

from unittest.mock import MagicMock, patch

import pytest

from app.agents.base import node
from app.agents.researcher import research_node
from app.config import get_settings
from app.errors import ConfigurationError
from app.graph import run_agentdesk
from app.llm.gemini_client import get_client
from app.rag.ingest import embed_texts

# --- the node decorator -------------------------------------------------------


def test_a_node_reports_its_own_timing_and_detail():
    @node("demo")
    def demo(state):
        return {"value": 1, "_detail": "did a thing"}

    update = demo({})

    assert update["value"] == 1
    assert "_detail" not in update, "the detail must not leak into graph state"
    assert update["trace"] == [
        {
            "node": "demo",
            "detail": "did a thing",
            "elapsed_ms": update["trace"][0]["elapsed_ms"],
            # A node that never calls the LLM still reports (zero) usage.
            "llm_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0.0,
        }
    ]
    assert update["trace"][0]["elapsed_ms"] >= 0


def test_a_node_without_a_detail_still_traces():
    @node("quiet")
    def quiet(state):
        return {}

    entry = quiet({})["trace"][0]

    assert entry["node"] == "quiet"
    assert entry["detail"] == ""
    assert isinstance(entry["elapsed_ms"], float)


def test_a_failing_node_logs_and_re_raises(caplog):
    @node("boom")
    def boom(state):
        raise RuntimeError("kaboom")

    with pytest.raises(RuntimeError, match="kaboom"):
        boom({})

    assert "node boom: failed" in caplog.text


# --- settings -----------------------------------------------------------------


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGENTDESK_MAX_REVISIONS", "7")
    monkeypatch.setenv("AGENTDESK_MAX_DISTANCE", "0.42")

    settings = get_settings()

    assert settings.max_revisions == 7
    assert settings.max_distance == 0.42


def test_blank_environment_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("AGENTDESK_MAX_REVISIONS", "")

    assert get_settings().max_revisions == 2


# --- embeddings ---------------------------------------------------------------


def test_embed_texts_batches_requests(monkeypatch):
    monkeypatch.setenv("AGENTDESK_EMBED_BATCH_SIZE", "2")
    client = MagicMock()
    client.models.embed_content.side_effect = lambda model, contents, config: MagicMock(
        embeddings=[MagicMock(values=[0.0]) for _ in contents]
    )

    vectors = embed_texts(["a", "b", "c", "d", "e"], client=client)

    assert len(vectors) == 5
    assert client.models.embed_content.call_count == 3, "5 texts at batch size 2 is 3 requests"


def test_embed_texts_short_circuits_on_no_input():
    assert embed_texts([], client=MagicMock()) == []


def test_a_missing_gemini_key_is_a_configuration_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        get_client()


# --- the researcher's degenerate case -----------------------------------------


def test_the_researcher_does_nothing_when_the_plan_selected_no_tools():
    update = research_node({"question": "q", "subtasks": ["s"], "use_rag": False, "use_web": False})

    assert update["research_notes"] == []
    assert "no tools" in update["trace"][0]["detail"]


# --- run_agentdesk ------------------------------------------------------------


def test_an_empty_question_is_rejected_before_any_work_happens():
    with pytest.raises(ValueError, match="must not be empty"):
        run_agentdesk("   ")


def test_run_agentdesk_attaches_resolved_citations_and_a_status():
    seen = {}

    def planner(state):
        seen["question"] = state["question"]
        return {"subtasks": ["s"], "use_rag": True, "use_web": False, "trace": []}

    nodes = {
        "planner_node": planner,
        "research_node": lambda s: {
            "sources": {"rag:h.md#0": {"source_id": "rag:h.md#0", "type": "rag", "file": "h.md"}},
            "trace": [],
        },
        "analyst_node": lambda s: {"facts": []},
        "synthesizer_node": lambda s: {"synthesis": {}},
        "writer_node": lambda s: {"draft_report": "d"},
        "critic_node": lambda s: {"final_report": "A claim [rag:h.md#0] and another [web:9]."},
    }
    patches = [patch(f"app.graph.{name}", side_effect=fn) for name, fn in nodes.items()]
    for p in patches:
        p.start()
    try:
        result = run_agentdesk("  a real question  ")
    finally:
        for p in patches:
            p.stop()

    assert seen["question"] == "a real question"
    assert result["status"] == "passed"
    assert result["run_id"]
    # [web:9] was never registered as a source, so it must not be reported as one.
    assert [c["source_id"] for c in result["citations"]] == ["rag:h.md#0"]
