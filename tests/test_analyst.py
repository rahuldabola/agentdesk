from unittest.mock import patch

from app.agents.analyst import analyst_node

NOTES = [
    {"source_id": "rag:h.md#0", "source_type": "rag", "content": "On-call is weekly."},
    {"source_id": "web:1", "source_type": "web", "content": "SRE Book: rotations are common."},
]


def test_analyst_extracts_facts_with_their_sources():
    facts = [{"claim": "On-call is weekly.", "source_id": "rag:h.md#0"}]
    with patch("app.agents.analyst.structured_call", return_value={"facts": facts}):
        update = analyst_node({"question": "q", "research_notes": NOTES})

    assert update["facts"] == [{**facts[0], "kind": "claim"}]


def test_analyst_skips_the_llm_call_when_there_is_nothing_to_analyse():
    with patch("app.agents.analyst.structured_call") as called:
        update = analyst_node({"question": "q", "research_notes": []})

    called.assert_not_called()
    assert update["facts"] == []


def test_analyst_drops_facts_citing_a_source_that_was_never_retrieved():
    """A fabricated source_id is a fabricated citation - catch it at the source."""
    facts = [
        {"claim": "Real claim.", "source_id": "rag:h.md#0"},
        {"claim": "Invented claim.", "source_id": "rag:does_not_exist.md#7"},
    ]
    with patch("app.agents.analyst.structured_call", return_value={"facts": facts}):
        update = analyst_node({"question": "q", "research_notes": NOTES})

    assert [f["source_id"] for f in update["facts"]] == ["rag:h.md#0"]
    assert "dropped 1" in update["trace"][0]["detail"]


def test_analyst_truncates_oversized_notes_before_prompting():
    huge = [{"source_id": "rag:h.md#0", "source_type": "rag", "content": "x" * 10_000}]
    with patch("app.agents.analyst.structured_call", return_value={"facts": []}) as call:
        analyst_node({"question": "q", "research_notes": huge})

    assert len(call.call_args.kwargs["user_prompt"]) < 3_000


def test_analyst_keeps_a_valid_fact_kind_and_defaults_an_invalid_one():
    facts = [
        {"claim": "Limit is 100/min.", "kind": "number", "source_id": "rag:h.md#0"},
        {"claim": "Rotations are common.", "kind": "vibes", "source_id": "web:1"},
    ]
    with patch("app.agents.analyst.structured_call", return_value={"facts": facts}):
        update = analyst_node({"question": "q", "research_notes": NOTES})

    assert [f["kind"] for f in update["facts"]] == ["number", "claim"]


def test_analyst_prompt_includes_the_subtasks_and_success_criteria():
    state = {
        "question": "q",
        "research_notes": NOTES,
        "subtasks": ["our escalation policy", "industry norms"],
        "success_criteria": ["states the internal timeline"],
    }
    with patch("app.agents.analyst.structured_call", return_value={"facts": []}) as call:
        analyst_node(state)

    prompt = call.call_args.kwargs["user_prompt"]
    assert "- our escalation policy" in prompt and "- industry norms" in prompt
    assert "- states the internal timeline" in prompt


def test_analyst_retries_once_when_the_model_returns_nothing_for_real_notes():
    fact = {"claim": "On-call is weekly.", "kind": "policy", "source_id": "rag:h.md#0"}
    replies = [{"facts": []}, {"facts": [fact]}]
    with patch("app.agents.analyst.structured_call", side_effect=replies) as call:
        update = analyst_node({"question": "q", "research_notes": NOTES})

    assert call.call_count == 2
    assert update["facts"] == [fact]
    assert "retried" in update["trace"][0]["detail"]


def test_analyst_does_not_retry_when_the_first_attempt_found_facts():
    fact = {"claim": "On-call is weekly.", "kind": "policy", "source_id": "rag:h.md#0"}
    with patch("app.agents.analyst.structured_call", return_value={"facts": [fact]}) as call:
        analyst_node({"question": "q", "research_notes": NOTES})

    assert call.call_count == 1


def test_analyst_gives_up_after_one_retry():
    with patch("app.agents.analyst.structured_call", return_value={"facts": []}) as call:
        update = analyst_node({"question": "q", "research_notes": NOTES})

    assert call.call_count == 2
    assert update["facts"] == []


def test_a_mangled_but_unambiguous_source_id_is_repaired():
    facts = [
        {"claim": "a", "source_id": "h.md#0"},
        {"claim": "b", "source_id": "[rag:h.md#0]"},
        {"claim": "c", "source_id": " RAG:H.MD#0 "},
        {"claim": "d", "source_id": "WEB:1"},
    ]
    with patch("app.agents.analyst.structured_call", return_value={"facts": facts}):
        update = analyst_node({"question": "q", "research_notes": NOTES})

    assert [f["source_id"] for f in update["facts"]] == ["rag:h.md#0"] * 3 + ["web:1"]


def test_invented_and_ambiguous_source_ids_are_still_rejected():
    from app.agents.analyst import resolve_source_id

    known = {"rag:a.md#0", "web:a.md#0"}

    assert resolve_source_id("a.md#0", known) is None, "ambiguous between two sources"
    assert resolve_source_id("rag:nope.md#9", known) is None
    assert resolve_source_id(None, known) is None
    assert resolve_source_id(7, known) is None
