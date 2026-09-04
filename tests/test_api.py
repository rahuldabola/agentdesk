"""API-surface tests. The graph is stubbed; what is under test is the contract."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.errors import ConfigurationError, LLMError
from app.main import app

client = TestClient(app)

RESULT = {
    "final_report": "On-call is weekly [rag:h.md#0].",
    "status": "passed",
    "citations": [{"source_id": "rag:h.md#0", "type": "rag", "file": "h.md"}],
    "revision_count": 1,
    "research_rounds": 0,
    "critic_verdict": "pass",
    "critic_feedback": "all claims supported",
    "unsupported_claims": [],
    "trace": [{"node": "planner", "detail": "2 subtasks", "elapsed_ms": 12.0}],
}


def test_health_needs_no_api_keys():
    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_a_successful_report_exposes_provenance_and_verdict():
    with patch("app.main.run_agentdesk", return_value=RESULT):
        resp = client.post("/api/report", json={"question": "What is our on-call rotation?"})

    body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "passed"
    assert body["report"] == RESULT["final_report"]
    assert body["citations"][0]["file"] == "h.md"
    assert body["revisions"] == 1
    assert body["critic"]["verdict"] == "pass"
    assert body["trace"][0]["node"] == "planner"


def test_a_report_that_failed_critique_says_so():
    """Callers must be able to tell a verified report from an unverified one."""
    unverified = {
        **RESULT,
        "status": "revision_limit_reached",
        "critic_verdict": "revise",
        "unsupported_claims": ["made this up"],
    }

    with patch("app.main.run_agentdesk", return_value=unverified):
        resp = client.post("/api/report", json={"question": "a question"})

    body = resp.json()
    assert body["status"] == "revision_limit_reached"
    assert body["critic"]["unsupported_claims"] == ["made this up"]


@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "hi"}, {"question": None}])
def test_malformed_requests_are_rejected_before_any_llm_call(payload):
    with patch("app.main.run_agentdesk") as never:
        resp = client.post("/api/report", json=payload)

    assert resp.status_code == 422
    never.assert_not_called()


def test_an_upstream_failure_is_a_bad_gateway_not_a_stack_trace():
    with patch("app.main.run_agentdesk", side_effect=LLMError("Claude is down")):
        resp = client.post("/api/report", json={"question": "a question"})

    assert resp.status_code == 502
    assert resp.json() == {"error": "LLMError", "detail": "Claude is down"}


def test_a_missing_key_is_reported_as_a_server_configuration_problem():
    with patch("app.main.run_agentdesk", side_effect=ConfigurationError("ANTHROPIC_API_KEY unset")):
        resp = client.post("/api/report", json={"question": "a question"})

    assert resp.status_code == 500
    assert resp.json()["error"] == "ConfigurationError"
