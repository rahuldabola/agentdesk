"""FastAPI surface for the orchestrator."""

import json
import logging
from collections.abc import Iterator

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool

from app.config import get_settings
from app.errors import AgentDeskError, ConfigurationError
from app.graph import run_agentdesk, stream_agentdesk

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("agentdesk.api")

app = FastAPI(
    title="AgentDesk",
    version="1.0.0",
    description="Multi-agent research & report orchestrator (LangGraph + MCP + RAG)",
)


class ReportRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


def _response_body(question: str, result: dict) -> dict:
    return {
        "question": question,
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": get_settings().anthropic_model}


@app.post("/api/report")
async def create_report(req: ReportRequest) -> dict:
    result = await run_in_threadpool(run_agentdesk, req.question)
    return _response_body(req.question, result)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _report_events(question: str) -> Iterator[str]:
    """Server-sent events for one run: a `progress` per node, then `report`.

    Errors are delivered as a terminal `error` event rather than a severed
    connection, because the response status is already committed by then.
    """
    try:
        for kind, payload in stream_agentdesk(question):
            if kind == "progress":
                yield _sse("progress", payload)
            else:
                yield _sse("report", _response_body(question, payload))
    except AgentDeskError as exc:
        log.error("%s during stream: %s", type(exc).__name__, exc)
        yield _sse("error", {"error": type(exc).__name__, "detail": str(exc)})


@app.post("/api/report/stream")
async def create_report_stream(req: ReportRequest) -> StreamingResponse:
    """Same run as /api/report, streamed as each agent finishes."""
    return StreamingResponse(
        iterate_in_threadpool(_report_events(req.question)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
