from unittest.mock import patch

from app.agents.critic import critic_node


def test_critic_pass_sets_final_report():
    fake_verdict = {"verdict": "pass", "feedback": "looks good", "unsupported_claims": []}
    state = {"question": "q", "facts": [], "draft_report": "Report", "revision_count": 0, "trace": []}
    with patch("app.agents.critic.structured_call", return_value=fake_verdict):
        result = critic_node(state)

    assert result["final_report"] == "Report"


def test_critic_revise_increments_count():
    fake_verdict = {"verdict": "revise", "feedback": "missing citation", "unsupported_claims": ["claim1"]}
    state = {"question": "q", "facts": [], "draft_report": "Report", "revision_count": 0, "trace": []}
    with patch("app.agents.critic.structured_call", return_value=fake_verdict):
        result = critic_node(state)

    assert result["revision_count"] == 1
    assert "final_report" not in result


def test_critic_revise_caps_at_max_revisions():
    fake_verdict = {"verdict": "revise", "feedback": "still bad", "unsupported_claims": []}
    state = {"question": "q", "facts": [], "draft_report": "Report", "revision_count": 2, "trace": []}
    with patch("app.agents.critic.structured_call", return_value=fake_verdict):
        result = critic_node(state)

    assert result.get("final_report") == "Report"
