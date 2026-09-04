"""API-surface tests. The graph is stubbed; what is under test is the contract."""

import json
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


# --- streaming ----------------------------------------------------------------


def _events(raw: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, data) pairs."""
    parsed = []
    for block in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        parsed.append((lines["event"], json.loads(lines["data"])))
    return parsed


def test_the_stream_reports_each_node_before_the_final_report():
    def fake_stream(question):
        yield "progress", {"node": "planner", "detail": "2 subtasks", "elapsed_ms": 10.0}
        yield "progress", {"node": "researcher", "detail": "4 notes", "elapsed_ms": 20.0}
        yield "report", RESULT

    with patch("app.main.stream_agentdesk", side_effect=fake_stream):
        resp = client.post("/api/report/stream", json={"question": "a question"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _events(resp.text)
    assert [name for name, _ in events] == ["progress", "progress", "report"]
    assert events[0][1]["node"] == "planner"
    assert events[-1][1]["report"] == RESULT["final_report"]
    assert events[-1][1]["citations"][0]["file"] == "h.md"


def test_a_failure_mid_stream_arrives_as_an_error_event():
    """The status line is already sent, so the failure has to travel in-band."""

    def fake_stream(question):
        yield "progress", {"node": "planner", "detail": "ok", "elapsed_ms": 1.0}
        raise LLMError("Claude is down")

    with patch("app.main.stream_agentdesk", side_effect=fake_stream):
        resp = client.post("/api/report/stream", json={"question": "a question"})

    events = _events(resp.text)
    assert resp.status_code == 200
    assert [name for name, _ in events] == ["progress", "error"]
    assert events[-1][1] == {"error": "LLMError", "detail": "Claude is down"}


def test_the_stream_validates_its_input_like_the_plain_endpoint():
    with patch("app.main.stream_agentdesk") as never:
        resp = client.post("/api/report/stream", json={"question": ""})

    assert resp.status_code == 422
    never.assert_not_called()
