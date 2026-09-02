from unittest.mock import patch

from app.agents.analyst import analyst_node


def test_analyst_node_extracts_facts():
    fake_facts = {"facts": [{"claim": "Rate limit is 1000 rpm", "source_id": "rag:api_policies.md#0"}]}
    state = {
        "question": "What is the rate limit?",
        "research_notes": [
            {"source_id": "rag:api_policies.md#0", "source_type": "rag", "content": "Rate limit is 1000 rpm"}
        ],
        "trace": [],
    }
    with patch("app.agents.analyst.structured_call", return_value=fake_facts):
        result = analyst_node(state)

    assert result["facts"] == fake_facts["facts"]


def test_analyst_node_skips_when_no_notes():
    state = {"question": "q", "research_notes": [], "trace": []}
    result = analyst_node(state)
    assert result["facts"] == []
