"""FastAPI surface for the orchestrator."""

import json
import logging
import os
import queue
import secrets
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.errors import AgentDeskError, ConfigurationError
from app.graph import (
    RunConflict,
    RunNotFound,
    cancel_run,
    delete_run,
    get_run,
    list_runs,
    resume_run,
    run_agentdesk,
    stream_agentdesk,
)
from app.mcp.client import mcp_session
from app.mcp.shared import reset_shared_session, shared_session
from app.observability import compute_metrics, init_tracing

load_dotenv()  # no-ops if .env doesn't exist (Docker/Railway set real env vars instead)
TRACING = init_tracing()  # exports spans only when OTEL_EXPORTER_OTLP_ENDPOINT is set

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("agentdesk.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Warm the shared MCP session at boot so the first question doesn't pay for it.

    Non-blocking: the server accepts requests (and passes health checks) while
    the tool server starts; a question arriving first simply waits for it.
    """
    if get_settings().mcp_reuse and os.environ.get("AGENTDESK_MCP_PREWARM", "1") != "0":
        future = shared_session(mcp_session).warm()
        future.add_done_callback(
            lambda f: f.exception() and log.warning("MCP prewarm failed: %s", f.exception())
        )
    yield
    reset_shared_session()


app = FastAPI(
    title="AgentDesk",
    version="1.2.0",
    description="Multi-agent research & report orchestrator (LangGraph + MCP + RAG)",
    lifespan=lifespan,
)

_raw_cors_origins = os.environ.get("AGENTDESK_CORS_ORIGINS", "*")
_cors_origins = [o.strip() for o in _raw_cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["content-type", "x-app-password"],
)


async def require_app_password(x_app_password: str | None = Header(default=None)) -> None:
    """Gate the expensive endpoints behind a shared password.

    Unset `AGENTDESK_APP_PASSWORD` disables the gate (local dev). When set, every
    request to a protected route must send a matching `X-App-Password` header.
    """
    expected = os.environ.get("AGENTDESK_APP_PASSWORD")
    if not expected:
        return
    if not x_app_password or not secrets.compare_digest(x_app_password, expected):
        raise HTTPException(status_code=401, detail="Missing or incorrect password.")


class ReportRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    # quick = leaner pipeline (fewer LLM/HTTP calls); deep = every specialist on.
    # Omitted -> the server's AGENTDESK_DEPTH, which defaults to deep.
    depth: Literal["quick", "deep"] | None = None


class StreamRequest(ReportRequest):
    # Pause after the Planner and wait for a human to approve or edit the plan
    # (POST /api/runs/{run_id}/resume). Only meaningful on a streamed run.
    review_plan: bool = False


class ResumeRequest(BaseModel):
    """A reviewer's decision on a paused plan; omitted fields keep the Planner's value."""

    action: Literal["approve", "reject"] = "approve"
    subtasks: list[str] | None = Field(default=None, max_length=20)
    success_criteria: list[str] | None = Field(default=None, max_length=20)
    use_rag: bool | None = None
    use_web: bool | None = None


def _response_body(question: str, result: dict) -> dict:
    return {
        "run_id": result.get("run_id"),
        "question": question,
        "depth": result.get("depth"),
        # "passed" means the Critic accepted the report; "revision_limit_reached"
        # means it did not, and the last draft is being returned unverified.
        "status": result.get("status"),
        "report": result.get("final_report"),
        "citations": result.get("citations", []),
        "revisions": result.get("revision_count", 0),
        "research_rounds": result.get("research_rounds", 0),
        "critic": {
            "verdict": result.get("critic_verdict"),
            "feedback": result.get("critic_feedback"),
            "unsupported_claims": result.get("unsupported_claims", []),
        },
        "trace": result.get("trace", []),
        # Tokens, LLM calls and list-price cost: run totals plus a per-agent breakdown.
        "usage": result.get("usage"),
    }


@app.exception_handler(AgentDeskError)
async def agentdesk_error_handler(request: Request, exc: AgentDeskError) -> JSONResponse:
    """A misconfiguration is ours (500); a failed upstream is a bad gateway (502)."""
    status = 500 if isinstance(exc, ConfigurationError) else 502
    log.error("%s: %s", type(exc).__name__, exc)
    return JSONResponse(
        status_code=status,
        content={"error": type(exc).__name__, "detail": str(exc)},
    )


@app.exception_handler(RunNotFound)
async def run_not_found_handler(request: Request, exc: RunNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "RunNotFound", "detail": str(exc)})


@app.exception_handler(RunConflict)
async def run_conflict_handler(request: Request, exc: RunConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": "RunConflict", "detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": get_settings().gemini_model, "tracing": TRACING}


@app.get("/api/metrics", dependencies=[Depends(require_app_password)])
async def metrics(limit: int = Query(default=200, ge=1, le=1000)) -> dict:
    """Volume, pass rate, latency percentiles, spend, and where time and money go per agent."""
    runs = await run_in_threadpool(list_runs, limit)
    return compute_metrics(runs)


@app.post("/api/report", dependencies=[Depends(require_app_password)])
async def create_report(req: ReportRequest) -> dict:
    result = await run_in_threadpool(run_agentdesk, req.question, req.depth)
    return _response_body(req.question, result)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _run_events(events: Iterator[tuple[str, dict]]) -> Iterator[str]:
    """Server-sent events for one run segment.

    `run` (the id, first), a `progress` per node, then either `report` or
    `plan_review` (the run is paused for a human). Errors are delivered as a
    terminal `error` event rather than a severed connection, because the
    response status is already committed by then. The run is checkpointed, so
    a failed run can be resumed later.
    """
    try:
        for kind, payload in events:
            if kind == "report":
                yield _sse("report", _response_body(payload.get("question", ""), payload))
            else:
                yield _sse(kind, payload)
    except AgentDeskError as exc:
        log.error("%s during stream: %s", type(exc).__name__, exc)
        yield _sse("error", {"error": type(exc).__name__, "detail": str(exc)})
    except Exception as exc:  # a bug, not an upstream failure; still end the stream cleanly
        log.exception("unexpected error during run")
        yield _sse("error", {"error": type(exc).__name__, "detail": "internal error"})


_DONE = object()


def start_run_worker(events: Iterator[tuple[str, dict]]) -> tuple[queue.Queue, threading.Thread]:
    """Execute a run on its own thread, publishing SSE chunks to a queue.

    The run's lifetime is decoupled from the HTTP connection on purpose. A
    sync generator streamed straight into the response is simply abandoned
    when the client disconnects - suspended at a `yield`, never closed - which
    left the run stuck at "running" and unresumable. Here the worker always
    drives the run to its next stopping point (report, review pause or error),
    the checkpointer records it, and a client that dropped off can read the
    outcome from GET /api/runs/{run_id}.
    """
    chunks: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            for chunk in _run_events(events):
                chunks.put(chunk)
        finally:
            chunks.put(_DONE)

    worker = threading.Thread(target=work, name="agentdesk-run", daemon=True)
    worker.start()
    return chunks, worker


def _event_stream(events: Iterator[tuple[str, dict]]) -> StreamingResponse:
    chunks, _ = start_run_worker(events)

    async def body():
        while (chunk := await run_in_threadpool(chunks.get)) is not _DONE:
            yield chunk

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/auth/check", dependencies=[Depends(require_app_password)])
async def auth_check() -> dict:
    """Let the frontend validate a password before wiring up the real UI."""
    return {"ok": True}


@app.post("/api/report/stream", dependencies=[Depends(require_app_password)])
async def create_report_stream(req: StreamRequest) -> StreamingResponse:
    """Same run as /api/report, streamed as each agent finishes."""
    return _event_stream(stream_agentdesk(req.question, req.depth, review_plan=req.review_plan))


# --- Durable runs -------------------------------------------------------------


@app.get("/api/runs", dependencies=[Depends(require_app_password)])
async def runs_index(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """Most recent runs first, from the run index (no checkpoint reads)."""
    return {"runs": await run_in_threadpool(list_runs, limit)}


@app.get("/api/runs/{run_id}", dependencies=[Depends(require_app_password)])
async def run_detail(run_id: str) -> dict:
    """One run, reconstructed from its checkpoint: plan, trace, pending review, result."""
    record = await run_in_threadpool(get_run, run_id)
    result = record.pop("result")
    record["result"] = _response_body(record["question"], result) if result else None
    return record


@app.post("/api/runs/{run_id}/resume", dependencies=[Depends(require_app_password)])
async def run_resume(run_id: str, req: ResumeRequest):
    """Approve (optionally edit) a paused plan, or continue a failed/orphaned run.

    `reject` cancels a paused run and returns its record as JSON; everything
    else streams the rest of the run as server-sent events.
    """
    if req.action == "reject":
        return await run_in_threadpool(cancel_run, run_id)
    edits = req.model_dump(exclude={"action"}, exclude_none=True)
    return _event_stream(resume_run(run_id, edits))


@app.post("/api/runs/{run_id}/cancel", dependencies=[Depends(require_app_password)])
async def run_cancel(run_id: str) -> dict:
    """Stop a run. An executing one halts at its next node boundary."""
    return await run_in_threadpool(cancel_run, run_id)


@app.delete("/api/runs/{run_id}", status_code=204, dependencies=[Depends(require_app_password)])
async def run_delete(run_id: str) -> Response:
    await run_in_threadpool(delete_run, run_id)
    return Response(status_code=204)
