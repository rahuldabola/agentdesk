"""Durable runs: checkpointing, human-in-the-loop plan review, resume, run API.

The agents are stubbed (they are covered elsewhere); LangGraph, its
checkpointers and the run index run for real, including on a SQLite file.
"""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import app.graph as graph_module
import app.persistence as persistence
from app.graph import (
    RunConflict,
    RunNotFound,
    cancel_run,
    clean_plan_edits,
    delete_run,
    get_run,
    list_runs,
    resume_run,
    stream_agentdesk,
)
from app.main import app

PLAN = {
    "question_type": "comparison",
    "subtasks": ["internal on-call policy", "industry on-call practice"],
    "success_criteria": ["states rotation length"],
    "use_rag": True,
    "use_web": True,
}


class Pipeline:
    """Stub agents that count their calls and record what the Researcher saw."""

    def __init__(self, fail_writer_times: int = 0):
        self.calls: dict[str, int] = {}
        self.researched: list[list[str]] = []
        self.fail_writer_times = fail_writer_times

    def _hit(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def planner(self, state):
        self._hit("planner")
        return {**PLAN, "trace": [{"node": "planner", "detail": "", "elapsed_ms": 1.0}]}

    def research(self, state):
        self._hit("researcher")
        self.researched.append(list(state["subtasks"]))
        return {
            "research_notes": [{"source_id": "rag:oncall.md#0", "content": "weekly"}],
            "sources": {"rag:oncall.md#0": {"source_id": "rag:oncall.md#0", "type": "rag"}},
            "trace": [{"node": "researcher", "detail": "", "elapsed_ms": 1.0}],
        }

    def analyst(self, state):
        self._hit("analyst")
        return {"facts": [], "trace": [{"node": "analyst", "detail": "", "elapsed_ms": 1.0}]}

    def synthesizer(self, state):
        self._hit("synthesizer")
        return {"synthesis": {}, "trace": [{"node": "synthesizer", "detail": "", "elapsed_ms": 1}]}

    def writer(self, state):
        self._hit("writer")
        if self.calls["writer"] <= self.fail_writer_times:
            raise TimeoutError("Gemini timed out")
        return {
            "draft_report": "On-call is weekly [rag:oncall.md#0].",
            "trace": [{"node": "writer", "detail": "", "elapsed_ms": 1.0}],
        }

    def critic(self, state):
        self._hit("critic")
        return {
            "critic_verdict": "pass",
            "final_report": state["draft_report"],
            "status": "passed",
            "trace": [{"node": "critic", "detail": "", "elapsed_ms": 1.0}],
        }

    @contextmanager
    def installed(self):
        nodes = {
            "planner_node": self.planner,
            "research_node": self.research,
            "analyst_node": self.analyst,
            "synthesizer_node": self.synthesizer,
            "writer_node": self.writer,
            "critic_node": self.critic,
        }
        patches = [patch(f"app.graph.{n}", side_effect=fn) for n, fn in nodes.items()]
        for p in patches:
            p.start()
        try:
            yield self
        finally:
            for p in patches:
                p.stop()


def _start_review(pipeline: Pipeline) -> tuple[str, list]:
    with pipeline.installed():
        events = list(stream_agentdesk("How does our on-call compare?", review_plan=True))
    return events[0][1]["run_id"], events


# --- Human-in-the-loop plan review --------------------------------------------


def test_review_pauses_after_planning_before_any_research():
    pipeline = Pipeline()
    run_id, events = _start_review(pipeline)

    assert [kind for kind, _ in events] == ["run", "progress", "plan_review"]
    kind, plan = events[-1]
    assert plan["run_id"] == run_id
    assert plan["subtasks"] == PLAN["subtasks"]
    assert plan["success_criteria"] == PLAN["success_criteria"]
    assert pipeline.calls == {"planner": 1}  # nothing past the Planner ran
    assert get_run(run_id)["status"] == "awaiting_review"
    assert get_run(run_id)["pending_review"]["question_type"] == "comparison"


def test_an_edited_plan_is_what_the_researcher_actually_receives():
    pipeline = Pipeline()
    run_id, _ = _start_review(pipeline)

    edits = {"subtasks": ["  internal on-call policy  ", "", "Google SRE on-call guidance"]}
    with pipeline.installed():
        events = list(resume_run(run_id, edits))

    assert pipeline.researched == [["internal on-call policy", "Google SRE on-call guidance"]]
    progress = [p["node"] for k, p in events if k == "progress"]
    # The resumed segment reports only new work: no replayed planner entry.
    assert progress == ["reviewer", "researcher", "analyst", "synthesizer", "writer", "critic"]
    reviewer = next(p for k, p in events if k == "progress" and p["node"] == "reviewer")
    assert reviewer["detail"] == "edited subtasks"

    report = events[-1][1]
    assert events[-1][0] == "report"
    assert report["run_id"] == run_id
    assert report["status"] == "passed"
    assert pipeline.calls["planner"] == 1  # the Planner is never re-run on resume

    record = get_run(run_id)
    assert record["status"] == "completed"
    assert record["outcome"] == "passed"
    assert record["citations"] == 1


def test_approving_without_edits_keeps_the_planners_plan():
    pipeline = Pipeline()
    run_id, _ = _start_review(pipeline)

    with pipeline.installed():
        events = list(resume_run(run_id, {}))

    assert pipeline.researched == [PLAN["subtasks"]]
    reviewer = next(p for k, p in events if k == "progress" and p["node"] == "reviewer")
    assert reviewer["detail"] == "approved as planned"


def test_a_rejected_plan_is_cancelled_and_cannot_be_resumed():
    run_id, _ = _start_review(Pipeline())

    assert cancel_run(run_id)["status"] == "cancelled"
    with pytest.raises(RunConflict):
        resume_run(run_id)


def test_an_executing_run_stops_at_the_next_node_boundary():
    pipeline = Pipeline()
    original_analyst = pipeline.analyst

    def analyst_then_user_hits_stop(state):
        run_id = list_runs()[0]["run_id"]
        assert cancel_run(run_id)["cancel_requested"] is True
        return original_analyst(state)

    pipeline.analyst = analyst_then_user_hits_stop
    with pipeline.installed():
        events = list(stream_agentdesk("a question"))

    assert events[-1][0] == "cancelled"
    # The node in flight finished; nothing after it started.
    assert [p["node"] for k, p in events if k == "progress"] == ["planner", "researcher", "analyst"]
    assert "synthesizer" not in pipeline.calls
    run = list_runs()[0]
    assert run["status"] == "cancelled"
    assert run["run_id"] not in graph_module._cancel_requests  # claim fully released
    with pytest.raises(RunConflict):
        resume_run(run["run_id"])


def test_a_finished_run_cannot_be_cancelled():
    with Pipeline().installed():
        list(stream_agentdesk("a question"))

    with pytest.raises(RunConflict):
        cancel_run(list_runs()[0]["run_id"])


def test_runs_without_review_never_pause():
    pipeline = Pipeline()
    with pipeline.installed():
        events = list(stream_agentdesk("a question"))

    assert events[-1][0] == "report"
    assert "reviewer" not in [p.get("node") for k, p in events if k == "progress"]


# --- Plan-edit sanitising -------------------------------------------------------


def test_plan_edits_are_cleaned_and_capped(monkeypatch):
    monkeypatch.setenv("AGENTDESK_MAX_PLAN_SUBTASKS", "2")
    update = clean_plan_edits(PLAN, {"subtasks": ["a", " ", "b", "c", 7], "use_web": False})

    assert update["subtasks"] == ["a", "b"]
    assert (update["use_rag"], update["use_web"]) == (True, False)


@pytest.mark.parametrize(
    "edits",
    [
        {"subtasks": []},  # an empty plan cannot be researched
        {"subtasks": ["  ", ""]},
        {"subtasks": "not a list"},
        {"use_rag": False, "use_web": False},  # a plan with no tools
        {"use_rag": "yes"},
        None,
        "garbage",
    ],
)
def test_plan_edits_cannot_break_the_planners_invariants(edits):
    update = clean_plan_edits(PLAN, edits)

    assert "subtasks" not in update
    assert update.get("use_rag", True) or update.get("use_web", False)


# --- Durability -------------------------------------------------------------------


def test_a_failed_run_resumes_from_its_last_checkpoint():
    pipeline = Pipeline(fail_writer_times=1)
    with pipeline.installed(), pytest.raises(TimeoutError):
        list(stream_agentdesk("a question"))

    run_id = list_runs()[0]["run_id"]
    record = get_run(run_id)
    assert record["status"] == "failed"
    assert "TimeoutError" in record["error"]
    assert record["next"] == ["write"]

    with pipeline.installed():
        events = list(resume_run(run_id))

    assert events[-1][0] == "report"
    # Only the failed node onward re-ran; planning and research were not repeated.
    assert pipeline.calls["planner"] == 1
    assert pipeline.calls["researcher"] == 1
    assert pipeline.calls["writer"] == 2
    assert get_run(run_id)["status"] == "completed"


def test_an_orphaned_running_run_can_be_resumed_but_a_live_one_cannot():
    run_id, _ = _start_review(Pipeline())
    persistence.get_run_store().update(run_id, status="running")  # as if the server died

    graph_module._active_runs.add(run_id)
    try:
        with pytest.raises(RunConflict):
            resume_run(run_id)
    finally:
        graph_module._active_runs.discard(run_id)

    pipeline = Pipeline()
    with pipeline.installed():
        events = list(resume_run(run_id))
    # It re-enters the paused review node and pauses again, rather than skipping review.
    assert events[-1][0] == "plan_review"


def test_a_paused_run_survives_a_process_restart(tmp_path, monkeypatch):
    """Checkpoints on disk: pause in one 'process', approve in the next."""
    monkeypatch.setenv("AGENTDESK_RUNS_DB", str(tmp_path / "runs.sqlite"))
    persistence.reset_persistence()
    graph_module.reset_graph()

    run_id, _ = _start_review(Pipeline())

    # Simulate a restart: drop every in-memory handle to the stores and graph.
    persistence.reset_persistence()
    graph_module.reset_graph()

    assert list_runs()[0]["status"] == "awaiting_review"
    pipeline = Pipeline()
    with pipeline.installed():
        events = list(resume_run(run_id, {"subtasks": ["only this"]}))

    assert pipeline.researched == [["only this"]]
    assert pipeline.calls.get("planner") is None  # the new process never re-planned
    assert events[-1][1]["final_report"] == "On-call is weekly [rag:oncall.md#0]."
    persistence.reset_persistence()  # release the SQLite handles before tmp cleanup


def test_deleting_a_run_drops_its_checkpoints():
    run_id, _ = _start_review(Pipeline())

    delete_run(run_id)

    with pytest.raises(RunNotFound):
        get_run(run_id)
    assert persistence.get_checkpointer().get_tuple(graph_module._config(run_id)) is None


def test_unknown_runs_are_not_found():
    for action in (get_run, resume_run, cancel_run, delete_run):
        with pytest.raises(RunNotFound):
            action("nope")


# --- HTTP surface -------------------------------------------------------------------

client = TestClient(app)


def _events(raw: str) -> list[tuple[str, dict]]:
    parsed = []
    for block in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        parsed.append((lines["event"], json.loads(lines["data"])))
    return parsed


def test_the_review_flow_end_to_end_over_http():
    pipeline = Pipeline()
    with pipeline.installed():
        started = client.post(
            "/api/report/stream", json={"question": "Compare on-call", "review_plan": True}
        )
        events = _events(started.text)
        assert [k for k, _ in events] == ["run", "progress", "plan_review"]
        run_id = events[0][1]["run_id"]

        listed = client.get("/api/runs").json()["runs"]
        assert listed[0]["run_id"] == run_id
        assert listed[0]["status"] == "awaiting_review"

        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["pending_review"]["subtasks"] == PLAN["subtasks"]
        assert detail["result"] is None

        resumed = client.post(f"/api/runs/{run_id}/resume", json={"subtasks": ["edited task"]})
        events = _events(resumed.text)

    assert events[0] == ("run", {"run_id": run_id})
    assert events[-1][0] == "report"
    assert events[-1][1]["run_id"] == run_id
    assert events[-1][1]["question"] == "Compare on-call"
    assert pipeline.researched == [["edited task"]]

    finished = client.get(f"/api/runs/{run_id}").json()
    assert finished["status"] == "completed"
    assert finished["result"]["report"] == "On-call is weekly [rag:oncall.md#0]."


def test_rejecting_over_http_returns_the_cancelled_run():
    run_id, _ = _start_review(Pipeline())

    resp = client.post(f"/api/runs/{run_id}/resume", json={"action": "reject"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    again = client.post(f"/api/runs/{run_id}/resume", json={})
    assert again.status_code == 409
    assert again.json()["error"] == "RunConflict"


def test_run_routes_map_errors_to_status_codes():
    assert client.get("/api/runs/missing").status_code == 404
    assert client.post("/api/runs/missing/resume", json={}).status_code == 404
    assert client.delete("/api/runs/missing").status_code == 404
    assert client.post("/api/runs/x/resume", json={"action": "maybe"}).status_code == 422

    assert client.post("/api/runs/missing/cancel").status_code == 404

    run_id, _ = _start_review(Pipeline())
    cancelled = client.post(f"/api/runs/{run_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert client.get(f"/api/runs/{run_id}").status_code == 404


def test_a_run_finishes_even_if_nobody_reads_the_stream():
    """Regression: a client that disconnects mid-run must not strand the run.

    Streaming the run generator straight into the response left it suspended
    at a `yield` forever once the client went away: stuck at "running", still
    claimed, unresumable. The worker thread drives it to completion regardless.
    """
    from app.main import start_run_worker

    pipeline = Pipeline()
    with pipeline.installed():
        _, worker = start_run_worker(stream_agentdesk("a question"))
        worker.join(timeout=10)  # nobody consumes the queue: the client is gone

    assert not worker.is_alive()
    run = list_runs()[0]
    assert run["status"] == "completed"
    assert run["run_id"] not in graph_module._active_runs


def test_an_unexpected_error_still_ends_the_stream_with_an_error_event():
    def broken():
        yield "run", {"run_id": "r"}
        raise KeyError("bug")

    with patch("app.main.stream_agentdesk", return_value=broken()):
        resp = client.post("/api/report/stream", json={"question": "a question"})

    assert [k for k, _ in _events(resp.text)] == ["run", "error"]
    assert _events(resp.text)[-1][1] == {"error": "KeyError", "detail": "internal error"}


def test_run_routes_are_password_gated(monkeypatch):
    monkeypatch.setenv("AGENTDESK_APP_PASSWORD", "s3cret")

    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/runs", headers={"X-App-Password": "s3cret"}).status_code == 200
