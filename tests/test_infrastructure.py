"""Cross-cutting behaviour: the node decorator, settings, ingest, and run_agentdesk."""

from unittest.mock import MagicMock, patch

import openai
import pytest

from app.agents.base import node
from app.agents.researcher import research_node
from app.config import get_settings
from app.errors import ConfigurationError
from app.graph import run_agentdesk
from app.rag.ingest import _embeddings_retryable, embed_texts, get_openai_client

# --- the node decorator -------------------------------------------------------


def test_a_node_reports_its_own_timing_and_detail():
    @node("demo")
    def demo(state):
        return {"value": 1, "_detail": "did a thing"}

    update = demo({})

    assert update["value"] == 1
    assert "_detail" not in update, "the detail must not leak into graph state"
    assert update["trace"] == [
        {"node": "demo", "detail": "did a thing", "elapsed_ms": update["trace"][0]["elapsed_ms"]}
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
    client.embeddings.create.side_effect = lambda model, input: MagicMock(
        data=[MagicMock(embedding=[0.0]) for _ in input]
    )

    vectors = embed_texts(["a", "b", "c", "d", "e"], client=client)

    assert len(vectors) == 5
    assert client.embeddings.create.call_count == 3, "5 texts at batch size 2 is 3 requests"


def test_embed_texts_short_circuits_on_no_input():
    assert embed_texts([], client=MagicMock()) == []


def test_a_missing_openai_key_is_a_configuration_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        get_openai_client()


@pytest.mark.parametrize(
    "exc,expected",
    [
        (openai.APIConnectionError(request=MagicMock()), True),
        (ValueError("nope"), False),
    ],
)
def test_only_transient_embedding_failures_are_retried(exc, expected):
    assert _embeddings_retryable(exc) is expected


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
    graph = MagicMock()
    graph.invoke.return_value = {
        "final_report": "A claim [rag:h.md#0] and another [web:9].",
        "sources": {"rag:h.md#0": {"source_id": "rag:h.md#0", "type": "rag", "file": "h.md"}},
        "revision_count": 0,
        "research_rounds": 0,
    }

    with patch("app.graph.get_graph", return_value=graph):
        result = run_agentdesk("  a real question  ")

    assert graph.invoke.call_args[0][0]["question"] == "a real question"
    assert result["status"] == "passed"
    # [web:9] was never registered as a source, so it must not be reported as one.
    assert [c["source_id"] for c in result["citations"]] == ["rag:h.md#0"]
