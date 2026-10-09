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


def test_writer_prompt_lists_the_success_criteria():
    from unittest.mock import patch

    from app.agents.writer import writer_node

    state = {"question": "q", "facts": [], "success_criteria": ["states the timeline"]}
    with patch("app.agents.writer.text_call", return_value="r") as mocked:
        writer_node(state)

    assert "- states the timeline" in mocked.call_args.kwargs["user_prompt"]


def _prompt_for(state):
    from unittest.mock import patch

    from app.agents.writer import writer_node

    with patch("app.agents.writer.text_call", return_value="r") as mocked:
        writer_node(state)
    return mocked.call_args.kwargs["user_prompt"]


TWO_FACTS = [
    {"claim": "Ours is weekly.", "source_id": "rag:h.md#0"},
    {"claim": "Industry is 1-2 weeks.", "source_id": "web:1"},
]


def test_writer_groups_facts_under_the_synthesizers_themes():
    synthesis = {
        "themes": [{"title": "Internal", "fact_ids": [0]}, {"title": "Industry", "fact_ids": [1]}],
        "conflicts": [],
        "gaps": [],
    }
    prompt = _prompt_for({"question": "q", "facts": TWO_FACTS, "synthesis": synthesis})

    assert "### Internal\n- Ours is weekly. [rag:h.md#0]" in prompt
    assert "### Industry\n- Industry is 1-2 weeks. [web:1]" in prompt
    assert "Internal company documents: rag:h.md#0" in prompt
    assert "External web sources: web:1" in prompt


def test_writer_surfaces_conflicts_and_gaps():
    synthesis = {
        "themes": [{"title": "All", "fact_ids": [0, 1]}],
        "conflicts": [{"description": "weekly vs 1-2 weeks", "fact_ids": [0, 1]}],
        "gaps": ["escalation path"],
    }
    prompt = _prompt_for({"question": "q", "facts": TWO_FACTS, "synthesis": synthesis})

    assert "weekly vs 1-2 weeks (sources: rag:h.md#0, web:1)" in prompt
    assert "- escalation path" in prompt


def test_writer_falls_back_to_a_flat_list_without_a_synthesis():
    prompt = _prompt_for({"question": "q", "facts": TWO_FACTS})

    assert "###" not in prompt
    assert "- Ours is weekly. [rag:h.md#0]" in prompt


def test_writer_ignores_a_synthesis_that_points_past_the_fact_list():
    synthesis = {"themes": [{"title": "Stale", "fact_ids": [0, 5]}], "conflicts": [], "gaps": []}
    prompt = _prompt_for({"question": "q", "facts": TWO_FACTS, "synthesis": synthesis})

    assert "###" not in prompt
    assert "- Industry is 1-2 weeks. [web:1]" in prompt


def test_writer_picks_the_template_for_the_question_type():
    comparison = _prompt_for({"question": "q", "facts": TWO_FACTS, "question_type": "comparison"})
    how_to = _prompt_for({"question": "q", "facts": TWO_FACTS, "question_type": "how_to"})
    unknown = _prompt_for({"question": "q", "facts": TWO_FACTS, "question_type": "mystery"})

    assert "Markdown table" in comparison
    assert "numbered steps" in how_to
    assert "Shape: a brief" in unknown
