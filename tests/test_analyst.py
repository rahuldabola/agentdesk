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

    assert update["facts"] == facts


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
