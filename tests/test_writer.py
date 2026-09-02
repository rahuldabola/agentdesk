from unittest.mock import patch

from app.agents.writer import writer_node


def test_writer_node_drafts_report_with_citations():
    state = {
        "question": "q",
        "facts": [{"claim": "X is true", "source_id": "rag:doc.md#0"}],
        "trace": [],
        "revision_count": 0,
    }
    with patch("app.agents.writer.text_call", return_value="X is true [rag:doc.md#0]"):
        result = writer_node(state)

    assert "rag:doc.md#0" in result["draft_report"]
    assert result["citations"] == ["rag:doc.md#0"]


def test_writer_node_includes_critic_feedback_in_prompt():
    state = {
        "question": "q",
        "facts": [],
        "trace": [],
        "revision_count": 1,
        "critic_feedback": "missing citation for claim X",
    }
    captured = {}

    def fake_text_call(system, user_prompt, **kwargs):
        captured["user_prompt"] = user_prompt
        return "revised report"

    with patch("app.agents.writer.text_call", side_effect=fake_text_call):
        writer_node(state)

    assert "missing citation for claim X" in captured["user_prompt"]
