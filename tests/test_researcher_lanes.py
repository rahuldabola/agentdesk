"""The Researcher's two lanes: query rewriting (internal) and reading pages in full (web)."""

import json
from unittest.mock import patch

import pytest

from app.agents.researcher import _pages_to_read, research_node, rewrite_queries

CHUNK = {
    "doc_id": "handbook.md#1",
    "file": "handbook.md",
    "chunk_index": 1,
    "score": 0.2,
    "content": "Unacknowledged pages escalate to the secondary after 10 minutes.",
}


def _rag_state(**extra):
    return {
        "question": "What happens when nobody answers a page?",
        "subtasks": ["nobody answers the page"],
        "use_rag": True,
        "use_web": False,
        **extra,
    }


def _fake_rag(answers_to):
    """A knowledge base that only has something to say for one phrasing."""

    def search(query, k=None):
        return [CHUNK] if query == answers_to else []

    return patch("app.mcp.tools._rag_search", side_effect=search)


@pytest.fixture
def rewriting(monkeypatch):
    monkeypatch.setenv("AGENTDESK_QUERY_REWRITE", "1")


# --- internal lane: rewrite an empty query once -------------------------------


def test_an_empty_query_is_reworded_and_retried(real_mcp_session, rewriting):
    with (
        _fake_rag("unacknowledged page escalation"),
        patch(
            "app.agents.researcher.structured_call",
            return_value={"queries": ["unacknowledged page escalation"]},
        ) as llm,
    ):
        update = research_node(_rag_state())

    assert [n["source_id"] for n in update["research_notes"]] == ["rag:handbook.md#1"]
    assert "reworded 1 empty query (1 recovered)" in update["trace"][0]["detail"]
    assert "nobody answers the page" in llm.call_args.kwargs["user_prompt"]


def test_no_rewrite_when_the_first_query_found_something(real_mcp_session, rewriting):
    with (
        _fake_rag("nobody answers the page"),
        patch("app.agents.researcher.structured_call") as llm,
    ):
        update = research_node(_rag_state())

    llm.assert_not_called()
    assert len(update["research_notes"]) == 1


def test_rewriting_can_be_switched_off(real_mcp_session):
    with _fake_rag("something else"), patch("app.agents.researcher.structured_call") as llm:
        update = research_node(_rag_state())

    llm.assert_not_called()
    assert update["research_notes"] == []


def test_a_rewrite_that_changes_nothing_is_not_retried(real_mcp_session, rewriting):
    with (
        _fake_rag("never matches") as rag,
        patch(
            "app.agents.researcher.structured_call",
            return_value={"queries": ["  Nobody answers the page "]},
        ),
    ):
        update = research_node(_rag_state())

    assert rag.call_count == 1, "an identical query must not be searched twice"
    assert "reworded" not in update["trace"][0]["detail"]


def test_a_rewrite_that_still_finds_nothing_is_reported_but_not_recovered(
    real_mcp_session, rewriting
):
    with (
        _fake_rag("never matches"),
        patch("app.agents.researcher.structured_call", return_value={"queries": ["other words"]}),
    ):
        update = research_node(_rag_state())

    assert update["research_notes"] == []
    assert "reworded 1 empty query (0 recovered)" in update["trace"][0]["detail"]


def test_a_failing_rewrite_degrades_to_the_original_result(real_mcp_session, rewriting):
    with (
        _fake_rag("never matches"),
        patch("app.agents.researcher.structured_call", side_effect=RuntimeError("quota")),
    ):
        update = research_node(_rag_state())

    assert update["research_notes"] == []
    assert "reworded" not in update["trace"][0]["detail"]


def test_a_search_error_is_not_mistaken_for_an_empty_result(real_mcp_session, rewriting):
    with (
        patch("app.mcp.tools._rag_search", side_effect=RuntimeError("index missing")),
        patch("app.agents.researcher.structured_call") as llm,
    ):
        research_node(_rag_state())

    llm.assert_not_called()


def test_rewrite_queries_keeps_one_entry_per_input_even_if_the_model_comes_up_short():
    with patch("app.agents.researcher.structured_call", return_value={"queries": ["new a", ""]}):
        out = rewrite_queries("q", ["a", "b", "c"])

    assert out == ["new a", "b", "c"]


# --- web lane: read the top pages in full -------------------------------------

RESULTS = [
    {"title": "SRE Book", "url": "https://sre.example/oncall", "snippet": "Rotations."},
    {"title": "Other", "url": "https://other.example/x", "snippet": "More."},
]


def _web_state():
    return {
        "question": "How do others run on-call?",
        "subtasks": ["typical on-call rotation"],
        "use_rag": False,
        "use_web": True,
    }


def _patch_web(monkeypatch, pages):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("AGENTDESK_FETCH_PAGES", "2")
    monkeypatch.setattr("app.mcp.tools._duckduckgo_search", lambda q, n, t: list(RESULTS))
    asked = []

    def fetch(url, max_chars=None):
        asked.append(url)
        return json.dumps(pages[url])

    monkeypatch.setattr("app.mcp.server.fetch_page_impl", fetch)
    return asked


def test_top_results_are_read_in_full_and_replace_the_snippet(real_mcp_session, monkeypatch):
    asked = _patch_web(
        monkeypatch,
        {
            "https://sre.example/oncall": {"url": "x", "title": "t", "text": "Full page body."},
            "https://other.example/x": {"url": "x", "title": "t", "text": "Second page body."},
        },
    )

    update = research_node(_web_state())

    contents = {n["source_id"]: n["content"] for n in update["research_notes"]}
    assert contents["web:1"] == "SRE Book: Full page body."
    assert contents["web:2"] == "Other: Second page body."
    assert asked == ["https://sre.example/oncall", "https://other.example/x"]
    assert "read 2 page(s) in full" in update["trace"][0]["detail"]


def test_an_unreadable_page_falls_back_to_its_snippet(real_mcp_session, monkeypatch):
    _patch_web(
        monkeypatch,
        {
            "https://sre.example/oncall": {"url": "x", "title": "t", "text": "Full page body."},
            "https://other.example/x": {"url": "x", "error": "not a text page (application/pdf)"},
        },
    )

    update = research_node(_web_state())

    contents = {n["source_id"]: n["content"] for n in update["research_notes"]}
    assert contents["web:1"] == "SRE Book: Full page body."
    assert contents["web:2"] == "Other: More."
    assert "read 1 page(s) in full (1 unreadable)" in update["trace"][0]["detail"]


def test_page_reading_can_be_switched_off(real_mcp_session, monkeypatch):
    asked = _patch_web(monkeypatch, {})
    monkeypatch.setenv("AGENTDESK_FETCH_PAGES", "0")

    update = research_node(_web_state())

    assert asked == []
    assert update["research_notes"][0]["content"] == "SRE Book: Rotations."


def test_pages_to_read_prefers_top_ranked_results_across_subtasks_and_dedupes():
    payloads = [
        {"results": [{"url": "https://a/1"}, {"url": "https://a/2"}]},
        {"results": [{"url": "https://b/1"}, {"url": "https://a/1"}]},
        RuntimeError("search failed"),
        {"results": [{"url": "ftp://bad/1"}, {"url": ""}]},
    ]

    assert _pages_to_read(payloads, 3) == ["https://a/1", "https://b/1", "https://a/2"]
    assert _pages_to_read(payloads, 0) == []
