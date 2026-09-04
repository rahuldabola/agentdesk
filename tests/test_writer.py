from unittest.mock import patch

from app.agents.writer import writer_node

FACTS = [
    {"claim": "On-call is weekly.", "source_id": "rag:h.md#0"},
    {"claim": "Pages escalate after 10 minutes.", "source_id": "rag:h.md#1"},
]


def test_writer_puts_every_fact_and_source_in_the_prompt():
    with patch("app.agents.writer.text_call", return_value="A report [rag:h.md#0]") as call:
        update = writer_node({"question": "q", "facts": FACTS})

    prompt = call.call_args.kwargs["user_prompt"]
    assert "On-call is weekly." in prompt
    assert "[rag:h.md#1]" in prompt
    assert update["draft_report"] == "A report [rag:h.md#0]"


def test_writer_is_told_what_the_critic_rejected_on_a_revision():
    state = {
        "question": "q",
        "facts": FACTS,
        "critic_feedback": "claim 2 is unsupported",
        "unsupported_claims": ["Pages escalate instantly."],
        "revision_count": 1,
    }
    with patch("app.agents.writer.text_call", return_value="v2") as call:
        writer_node(state)

    prompt = call.call_args.kwargs["user_prompt"]
    assert "claim 2 is unsupported" in prompt
    assert "Pages escalate instantly." in prompt


def test_writer_does_not_mention_feedback_on_the_first_draft():
    with patch("app.agents.writer.text_call", return_value="v1") as call:
        writer_node({"question": "q", "facts": FACTS, "revision_count": 0})

    assert "rejected by the Critic" not in call.call_args.kwargs["user_prompt"]


def test_writer_handles_an_empty_fact_list():
    with patch("app.agents.writer.text_call", return_value="I cannot answer.") as call:
        writer_node({"question": "q", "facts": []})

    assert "(none)" in call.call_args.kwargs["user_prompt"]
