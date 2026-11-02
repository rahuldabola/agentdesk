"""Observability: token/cost accounting, OpenTelemetry spans, run metrics.

The Gemini API and the agents are stubbed; the ledger, the node decorator,
the LLM client's instrumentation, LangGraph, the run index and the OTel SDK
(with an in-memory exporter) are real.
"""

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import app.llm.gemini_client as gemini_client
from app.agents.base import node
from app.graph import get_run, list_runs, stream_agentdesk
from app.main import app
from app.observability import (
    compute_metrics,
    measure,
    price_per_m,
    record_llm_response,
    summarize_trace,
    usage_from_response,
)
from app.persistence import RunStore

# The OTel API allows one global provider per process: install an in-memory
# exporter once; the module-level `tracer` proxies resolve to it.
EXPORTER = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
trace.set_tracer_provider(_provider)


@pytest.fixture(autouse=True)
def fresh_spans():
    EXPORTER.clear()
    yield


def response(tokens_in=1000, tokens_out=200, thoughts=0, model="gemini-3.5-flash-lite-001"):
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(
            prompt_token_count=tokens_in,
            candidates_token_count=tokens_out,
            thoughts_token_count=thoughts,
        ),
        model_version=model,
        function_calls=[SimpleNamespace(name="submit", args={"ok": True})],
        text="ok",
        candidates=[],
    )


# --- pricing and per-response usage ------------------------------------------------


def test_cost_uses_the_model_gemini_reports_and_bills_thinking_as_output():
    usage = usage_from_response(response(1_000_000, 100_000, thoughts=100_000), "ignored")

    assert (usage.tokens_in, usage.tokens_out) == (1_000_000, 200_000)
    # 3.5 Flash-Lite: $0.30/M in + $2.50/M out
    assert usage.cost_usd == pytest.approx(0.30 + 0.2 * 2.50)


def test_longest_prefix_wins_and_env_overrides_price(monkeypatch):
    assert price_per_m("models/gemini-2.5-flash-lite-preview") == (0.10, 0.40)
    monkeypatch.setenv("AGENTDESK_PRICE_OUTPUT_PER_M", "9")
    assert price_per_m("gemini-2.5-flash-lite") == (0.10, 9.0)


def test_a_response_without_usage_metadata_counts_the_call_but_no_tokens():
    usage = usage_from_response(SimpleNamespace(), "gemini-flash-lite-latest")

    assert (usage.llm_calls, usage.tokens_in, usage.tokens_out, usage.cost_usd) == (1, 0, 0, 0)


# --- attribution to agents ---------------------------------------------------------


def test_concurrent_calls_from_threads_and_tasks_bill_to_the_node_that_spawned_them():
    """The Researcher fans out with asyncio.gather and asyncio.to_thread."""

    @node("researcher")
    def researcher(state):
        async def lanes():
            async def lane():
                record_llm_response(response(100, 10), None)

            await asyncio.gather(
                lane(),
                lane(),
                asyncio.to_thread(record_llm_response, response(100, 10), None),
            )

        asyncio.run(lanes())
        return {"_detail": "3 calls"}

    entry = researcher({})["trace"][0]

    assert entry["llm_calls"] == 3
    assert (entry["tokens_in"], entry["tokens_out"]) == (300, 30)
    assert entry["cost_usd"] > 0


def test_ledgers_do_not_leak_between_nodes_or_outside_them():
    record_llm_response(response(), None)  # outside any node: recorded nowhere, no error

    @node("a")
    def a(state):
        record_llm_response(response(10, 1), None)
        return {}

    @node("b")
    def b(state):
        return {}

    assert a({})["trace"][0]["tokens_in"] == 10
    assert b({})["trace"][0]["llm_calls"] == 0


def test_nested_measure_blocks_are_independent():
    with measure() as outer:
        record_llm_response(response(5, 0), None)
        with measure() as inner:
            record_llm_response(response(7, 0), None)

    assert (outer.usage.tokens_in, inner.usage.tokens_in) == (5, 7)


def test_the_real_llm_client_reports_usage_to_the_calling_agent(monkeypatch):
    class FakeModels:
        def generate_content(self, **kwargs):
            return response(1234, 56)

    monkeypatch.setattr(gemini_client, "get_client", lambda: SimpleNamespace(models=FakeModels()))

    @node("planner")
    def planner(state):
        gemini_client.structured_call("sys", "q", "submit", "d", {"type": "object"})
        return {}

    entry = planner({})["trace"][0]
    assert (entry["llm_calls"], entry["tokens_in"], entry["tokens_out"]) == (1, 1234, 56)

    llm_span = next(s for s in EXPORTER.get_finished_spans() if s.name == "gemini.generate_content")
    agent_span = next(s for s in EXPORTER.get_finished_spans() if s.name == "agent.planner")
    assert llm_span.parent.span_id == agent_span.context.span_id
    assert llm_span.attributes["gen_ai.system"] == "gemini"
    assert llm_span.attributes["gen_ai.usage.input_tokens"] == 1234
    assert llm_span.attributes["gen_ai.usage.output_tokens"] == 56
    assert llm_span.attributes["gen_ai.response.model"] == "gemini-3.5-flash-lite-001"
    assert agent_span.attributes["agentdesk.tokens_in"] == 1234


def test_a_failing_agent_marks_its_span_as_an_error():
    @node("writer")
    def writer(state):
        raise TimeoutError("slow")

    with pytest.raises(TimeoutError):
        writer({})

    span = next(s for s in EXPORTER.get_finished_spans() if s.name == "agent.writer")
    assert not span.status.is_ok
    assert any(e.name == "exception" for e in span.events)


# --- runs: spans, the run index, the API ------------------------------------------


@contextmanager
def billed_pipeline():
    """Agents that each make LLM calls of known size, decorated like the real ones."""

    def agent(name, calls, ret):
        @node(name)
        def fn(state):
            for _ in range(calls):
                record_llm_response(response(1000, 100), None)
            return ret(state) if callable(ret) else dict(ret)

        return fn

    nodes = {
        "planner_node": agent("planner", 1, {"subtasks": ["s"], "use_rag": True, "use_web": False}),
        "research_node": agent(
            "researcher",
            2,
            {
                "research_notes": [{"source_id": "rag:a#0", "content": "x"}],
                "sources": {"rag:a#0": {"source_id": "rag:a#0", "type": "rag"}},
            },
        ),
        "analyst_node": agent("analyst", 1, {"facts": []}),
        "synthesizer_node": agent("synthesizer", 1, {"synthesis": {}}),
        "writer_node": agent("writer", 1, {"draft_report": "Fact [rag:a#0]."}),
        "critic_node": agent(
            "critic",
            1,
            lambda s: {"final_report": s["draft_report"], "status": "passed"},
        ),
    }
    patches = [patch(f"app.graph.{name}", side_effect=fn) for name, fn in nodes.items()]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


def test_a_run_reports_totals_and_a_per_agent_breakdown():
    with billed_pipeline():
        events = list(stream_agentdesk("a question"))

    report = events[-1][1]
    usage = report["usage"]
    assert usage["llm_calls"] == 7
    assert usage["tokens_in"] == 7000 and usage["tokens_out"] == 700
    assert usage["by_agent"]["researcher"]["llm_calls"] == 2
    assert usage["cost_usd"] == pytest.approx(7 * (1000 * 0.30 + 100 * 2.50) / 1e6)

    # Every progress event carries that node's usage, so the UI can show it live.
    progress = [p for k, p in events if k == "progress"]
    assert sum(p["llm_calls"] for p in progress) == 7

    # The run index holds the same totals, for listing and fleet metrics.
    row = list_runs()[0]
    assert (row["llm_calls"], row["tokens_in"], row["tokens_out"]) == (7, 7000, 700)
    assert row["usage_by_agent"]["critic"]["llm_calls"] == 1
    assert get_run(row["run_id"])["result"]["usage"]["llm_calls"] == 7


def test_run_span_is_the_parent_of_every_agent_span():
    with billed_pipeline():
        list(stream_agentdesk("a question"))

    spans = EXPORTER.get_finished_spans()
    run = next(s for s in spans if s.name == "agentdesk.run")
    agents = [s for s in spans if s.name.startswith("agent.")]

    assert {s.name for s in agents} == {
        "agent.planner",
        "agent.researcher",
        "agent.analyst",
        "agent.synthesizer",
        "agent.writer",
        "agent.critic",
    }
    assert all(s.context.trace_id == run.context.trace_id for s in agents)
    assert run.attributes["agentdesk.status"] == "completed"
    assert run.attributes["agentdesk.outcome"] == "passed"
    assert run.attributes["agentdesk.total_llm_calls"] == 7


def test_a_paused_run_already_records_what_planning_cost():
    with billed_pipeline():
        list(stream_agentdesk("a question", review_plan=True))

    row = list_runs()[0]
    assert row["status"] == "awaiting_review"
    assert row["llm_calls"] == 1  # the Planner, before the pause


def test_the_api_returns_usage_and_fleet_metrics():
    client = TestClient(app)
    with billed_pipeline():
        body = client.post("/api/report", json={"question": "a question"}).json()
        client.post("/api/report", json={"question": "another question"})

    assert body["usage"]["llm_calls"] == 7

    metrics = client.get("/api/metrics").json()
    assert metrics["runs"] == 2 and metrics["completed"] == 2
    assert metrics["pass_rate"] == 1.0
    assert metrics["avg_tokens_per_run"] == 7700
    assert metrics["by_agent"]["researcher"]["avg_llm_calls"] == 2
    assert metrics["by_agent"]["researcher"]["cost_share"] == pytest.approx(2 / 7, abs=1e-3)
    assert client.get("/health").json()["tracing"] in (True, False)


def test_metrics_are_password_gated(monkeypatch):
    monkeypatch.setenv("AGENTDESK_APP_PASSWORD", "pw")
    assert TestClient(app).get("/api/metrics").status_code == 401


def test_otlp_export_is_off_without_an_endpoint_and_wired_with_one(monkeypatch):
    import app.observability as obs

    monkeypatch.setattr(obs, "_tracing_ready", False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert obs.init_tracing() is False

    installed = []
    monkeypatch.setattr(obs.trace, "set_tracer_provider", installed.append)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "agentdesk-test")
    assert obs.init_tracing() is True
    assert obs.init_tracing() is True  # idempotent: one provider, installed once
    assert len(installed) == 1
    assert installed[0].resource.attributes["service.name"] == "agentdesk-test"
    installed[0].shutdown()


# --- metrics maths and storage ---------------------------------------------------


def _run(status="completed", outcome="passed", ms=1000.0, cost=0.01, tokens=100, agents=None):
    return {
        "status": status,
        "outcome": outcome,
        "elapsed_ms": ms,
        "cost_usd": cost,
        "tokens_in": tokens,
        "tokens_out": 0,
        "created_at": 1.0,
        "usage_by_agent": agents or {},
    }


def test_metrics_use_completed_runs_for_latency_but_count_all_spend():
    runs = [
        _run(ms=ms)
        for ms in (100, 200, 300, 400, 500, 600, 700, 800, 900, 10_000)  # one slow outlier
    ] + [_run(status="failed", outcome=None, ms=50, cost=0.5)]

    m = compute_metrics(runs)

    assert m["by_status"] == {"completed": 10, "failed": 1}
    assert m["latency_ms"]["p50"] == 500
    assert m["latency_ms"]["p95"] == 10_000
    assert m["total_cost_usd"] == pytest.approx(10 * 0.01 + 0.5)
    assert m["avg_cost_per_run_usd"] == pytest.approx(0.01)


def test_metrics_pass_rate_and_empty_window():
    m = compute_metrics([_run(), _run(outcome="revision_limit_reached")])
    assert m["pass_rate"] == 0.5

    empty = compute_metrics([])
    assert empty["runs"] == 0 and empty["pass_rate"] is None and empty["latency_ms"]["p50"] is None


def test_summarize_trace_tolerates_entries_from_before_usage_existed():
    old = [{"node": "planner", "detail": "", "elapsed_ms": 5.0}]
    summary = summarize_trace(old)

    assert summary["llm_calls"] == 0 and summary["elapsed_ms"] == 5.0
    assert summary["by_agent"]["planner"]["runs"] == 1


def test_an_existing_runs_db_gains_the_usage_columns(tmp_path):
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, question TEXT NOT NULL, depth TEXT,"
        " review_plan INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, outcome TEXT,"
        " error TEXT, citations INTEGER, revisions INTEGER, created_at REAL NOT NULL,"
        " updated_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO runs VALUES ('r1', 'q', 'deep', 0, 'completed', 'passed', NULL, 1, 0, 1, 1)"
    )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    store = RunStore(conn)
    assert store.get("r1")["usage_by_agent"] == {}  # old row still readable

    store.update("r1", cost_usd=0.002, usage_by_agent={"critic": {"llm_calls": 1}})
    row = store.get("r1")
    assert row["cost_usd"] == 0.002
    assert row["usage_by_agent"] == {"critic": {"llm_calls": 1}}
    raw = conn.execute("SELECT usage_by_agent FROM runs").fetchone()[0]
    assert json.loads(raw) == {"critic": {"llm_calls": 1}}
    conn.close()
