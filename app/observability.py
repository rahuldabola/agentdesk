"""Observability: token/cost accounting per agent, and OpenTelemetry tracing.

Usage accounting
    Every Gemini response carries `usage_metadata`. The `@node` decorator opens
    a fresh `Ledger` in a context variable for the duration of the node, and the
    LLM client records each response into whichever ledger is current. Context
    variables follow the work: asyncio tasks and `asyncio.to_thread` copy them,
    so the Researcher's concurrent lanes still bill to the Researcher. The
    ledger is then folded into that node's trace entry, which the checkpointer
    already persists and the SSE stream already delivers - no second store.

Tracing
    One span per run segment, per agent, per Gemini call and per MCP tool call,
    using the OpenTelemetry GenAI semantic conventions for the LLM spans
    (`gen_ai.usage.input_tokens`, ...). Spans are exported over OTLP/HTTP when
    `OTEL_EXPORTER_OTLP_ENDPOINT` is set (Jaeger, Grafana Tempo, Honeycomb,
    Langfuse...); otherwise the OpenTelemetry API is a no-op and costs nothing.
"""

from __future__ import annotations

import contextvars
import logging
import math
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from opentelemetry import trace

log = logging.getLogger("agentdesk.observability")

tracer = trace.get_tracer("agentdesk")

# USD per 1M tokens (input, output), standard paid tier, from
# https://ai.google.dev/gemini-api/docs/pricing (checked 2026-11-03). Matched by
# longest prefix against the model version Gemini reports for each response.
# Thinking tokens bill as output. Override with AGENTDESK_PRICE_INPUT_PER_M /
# AGENTDESK_PRICE_OUTPUT_PER_M. On the free tier the real bill is $0; these are
# what the same traffic would cost on the paid tier.
PRICES_PER_M: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.25, 1.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-flash-lite-latest": (0.30, 2.50),
}
DEFAULT_PRICE_PER_M = (0.30, 2.50)


def price_per_m(model: str | None) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for `model`; env overrides win."""
    env_in = os.environ.get("AGENTDESK_PRICE_INPUT_PER_M")
    env_out = os.environ.get("AGENTDESK_PRICE_OUTPUT_PER_M")
    base = DEFAULT_PRICE_PER_M
    name = (model or "").removeprefix("models/")
    for prefix in sorted(PRICES_PER_M, key=len, reverse=True):
        if name.startswith(prefix):
            base = PRICES_PER_M[prefix]
            break
    return (
        float(env_in) if env_in else base[0],
        float(env_out) if env_out else base[1],
    )


@dataclass
class Usage:
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

    def add(self, other: Usage) -> None:
        self.llm_calls += other.llm_calls
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out
        self.cost_usd += other.cost_usd

    def as_dict(self) -> dict:
        data = asdict(self)
        data["cost_usd"] = round(self.cost_usd, 6)
        return data


class Ledger:
    """Usage accumulated by one node. Thread-safe: lanes may record concurrently."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.usage = Usage()

    def record(self, usage: Usage) -> None:
        with self._lock:
            self.usage.add(usage)


_ledger: contextvars.ContextVar[Ledger | None] = contextvars.ContextVar(
    "agentdesk_ledger", default=None
)


@contextmanager
def measure() -> Iterator[Ledger]:
    """Collect every LLM call made (directly or by spawned tasks) inside the block."""
    ledger = Ledger()
    token = _ledger.set(ledger)
    try:
        yield ledger
    finally:
        _ledger.reset(token)


def usage_from_response(response, requested_model: str | None) -> Usage:
    """Token counts and cost of one Gemini response (zeros if it reports none)."""
    meta = getattr(response, "usage_metadata", None)

    def _count(field: str) -> int:
        value = getattr(meta, field, 0)
        return value if isinstance(value, int) else 0

    tokens_in = _count("prompt_token_count")
    tokens_out = _count("candidates_token_count") + _count("thoughts_token_count")
    reported = getattr(response, "model_version", None)
    model = reported if isinstance(reported, str) and reported else requested_model
    price_in, price_out = price_per_m(model)
    cost = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
    return Usage(llm_calls=1, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost)


def record_llm_response(response, requested_model: str | None, span=None) -> Usage:
    """Bill one response to the current node and annotate its LLM span."""
    usage = usage_from_response(response, requested_model)
    ledger = _ledger.get()
    if ledger is not None:
        ledger.record(usage)
    if span is not None and span.is_recording():
        span.set_attribute("gen_ai.response.model", str(getattr(response, "model_version", "")))
        span.set_attribute("gen_ai.usage.input_tokens", usage.tokens_in)
        span.set_attribute("gen_ai.usage.output_tokens", usage.tokens_out)
        span.set_attribute("agentdesk.cost_usd", round(usage.cost_usd, 8))
    return usage


USAGE_KEYS = ("llm_calls", "tokens_in", "tokens_out", "cost_usd")


def summarize_trace(trace_entries: list[dict]) -> dict:
    """Run totals and a per-agent breakdown, derived from the trace entries.

    The trace is the source of truth: it is checkpointed with the run, so the
    numbers survive restarts and resumes and always match what the UI showed.
    """
    total = Usage()
    elapsed = 0.0
    by_agent: dict[str, dict] = {}
    for entry in trace_entries or []:
        node = entry.get("node", "?")
        usage = Usage(**{k: entry.get(k, 0) or 0 for k in USAGE_KEYS})
        total.add(usage)
        ms = float(entry.get("elapsed_ms", 0) or 0)
        elapsed += ms
        agent = by_agent.setdefault(node, {"runs": 0, "elapsed_ms": 0.0, **Usage().as_dict()})
        agent["runs"] += 1
        agent["elapsed_ms"] = round(agent["elapsed_ms"] + ms, 1)
        for key in USAGE_KEYS:
            agent[key] += getattr(usage, key)
        agent["cost_usd"] = round(agent["cost_usd"], 6)
    return {**total.as_dict(), "elapsed_ms": round(elapsed, 1), "by_agent": by_agent}


def _percentile(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile; None for no data."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(pct / 100 * len(ordered))))
    return round(ordered[rank - 1], 1)


def compute_metrics(runs: list[dict]) -> dict:
    """Fleet-level numbers from the run index: volume, quality, latency, cost.

    Latency and per-run averages use completed runs only (a paused or failed run
    would drag them down for the wrong reason); spend counts every run, because
    a failed run's tokens were billed too. Per-agent figures answer "where do
    the time and the money go".
    """
    by_status: dict[str, int] = {}
    for run in runs:
        by_status[run["status"]] = by_status.get(run["status"], 0) + 1
    completed = [r for r in runs if r["status"] == "completed"]
    passed = sum(1 for r in completed if r.get("outcome") == "passed")
    latencies = [float(r["elapsed_ms"]) for r in completed if r.get("elapsed_ms") is not None]
    total_cost = sum(float(r.get("cost_usd") or 0) for r in runs)
    total_tokens = sum(int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0) for r in runs)

    agents: dict[str, dict] = {}
    for run in completed:
        for name, usage in (run.get("usage_by_agent") or {}).items():
            agg = agents.setdefault(
                name, {"elapsed_ms": 0.0, "tokens": 0, "cost_usd": 0.0, "llm_calls": 0}
            )
            agg["elapsed_ms"] += float(usage.get("elapsed_ms", 0) or 0)
            agg["tokens"] += int(usage.get("tokens_in", 0) or 0) + int(
                usage.get("tokens_out", 0) or 0
            )
            agg["cost_usd"] += float(usage.get("cost_usd", 0) or 0)
            agg["llm_calls"] += int(usage.get("llm_calls", 0) or 0)
    all_ms = sum(a["elapsed_ms"] for a in agents.values()) or 1.0
    all_cost = sum(a["cost_usd"] for a in agents.values()) or 1.0
    n = len(completed) or 1
    by_agent = {
        name: {
            "avg_elapsed_ms": round(a["elapsed_ms"] / n, 1),
            "avg_tokens": round(a["tokens"] / n),
            "avg_llm_calls": round(a["llm_calls"] / n, 2),
            "avg_cost_usd": round(a["cost_usd"] / n, 6),
            "time_share": round(a["elapsed_ms"] / all_ms, 3),
            "cost_share": round(a["cost_usd"] / all_cost, 3),
        }
        for name, a in agents.items()
    }

    return {
        "runs": len(runs),
        "by_status": by_status,
        "completed": len(completed),
        "pass_rate": round(passed / len(completed), 3) if completed else None,
        "latency_ms": {
            "p50": _percentile(latencies, 50),
            "p95": _percentile(latencies, 95),
            "mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
        },
        "avg_tokens_per_run": round(
            sum(int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0) for r in completed) / n
        )
        if completed
        else None,
        "avg_cost_per_run_usd": round(sum(float(r.get("cost_usd") or 0) for r in completed) / n, 6)
        if completed
        else None,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 6),
        "by_agent": by_agent,
        "window_start": min((r["created_at"] for r in runs), default=None),
    }


_tracing_lock = threading.Lock()
_tracing_ready = False


def init_tracing() -> bool:
    """Install an OTLP exporter if OTEL_EXPORTER_OTLP_ENDPOINT is set. Idempotent.

    Returns whether spans are being exported. Standard OTEL_* variables
    (headers, service name, sampler) are honoured by the SDK itself.
    """
    global _tracing_ready
    with _tracing_lock:
        if _tracing_ready:
            return True
        if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
            return False
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {"service.name": os.environ.get("OTEL_SERVICE_NAME", "agentdesk-api")}
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracing_ready = True
        log.info("OpenTelemetry tracing enabled -> %s", os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"])
        return True
