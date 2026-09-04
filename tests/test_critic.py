from unittest.mock import patch

from app.agents.critic import critic_node

STATE = {
    "question": "q",
    "facts": [{"claim": "c", "source_id": "rag:h.md#0"}],
    "draft_report": "draft",
    "revision_count": 0,
    "research_rounds": 0,
}


def _verdict(**data):
    data.setdefault("unsupported_claims", [])
    data.setdefault("missing_information", [])
    data.setdefault("feedback", "")
    return patch("app.agents.critic.structured_call", return_value=data)


def test_pass_finalises_the_report():
    with _verdict(verdict="pass"):
        update = critic_node(STATE)

    assert update["final_report"] == "draft"
    assert update["status"] == "passed"


def test_overreach_routes_back_to_the_writer():
    """No missing evidence, just unsupported wording - a rewrite can fix it."""
    with _verdict(verdict="revise", unsupported_claims=["overstated"]):
        update = critic_node(STATE)

    assert "final_report" not in update
    assert update["revision_count"] == 1
    assert update["missing_information"] == []


def test_an_evidence_gap_routes_back_to_research():
    with _verdict(verdict="revise", missing_information=["what does the SRE book say?"]):
        update = critic_node(STATE)

    assert update["pending_subtasks"] == ["what does the SRE book say?"]
    assert update["missing_information"] == ["what does the SRE book say?"]
    # A research round must not burn a rewrite attempt.
    assert "revision_count" not in update


def test_evidence_gaps_stop_requesting_research_once_the_round_cap_is_hit(monkeypatch):
    monkeypatch.setenv("AGENTDESK_MAX_RESEARCH_ROUNDS", "1")
    with _verdict(verdict="revise", missing_information=["more"]):
        update = critic_node({**STATE, "research_rounds": 1})

    assert update["missing_information"] == []
    assert update["revision_count"] == 1


def test_hitting_the_revision_limit_ships_the_draft_but_flags_it():
    with _verdict(verdict="revise", feedback="still wrong"):
        update = critic_node({**STATE, "revision_count": 2})

    assert update["final_report"] == "draft"
    assert update["status"] == "revision_limit_reached"
    assert update["critic_verdict"] == "revise"


def test_blank_missing_information_entries_are_ignored():
    with _verdict(verdict="revise", missing_information=["  ", ""]):
        update = critic_node(STATE)

    assert update["missing_information"] == []
    assert update["revision_count"] == 1
