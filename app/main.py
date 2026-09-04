"""FastAPI surface for the orchestrator."""

import logging

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.errors import AgentDeskError, ConfigurationError
from app.graph import run_agentdesk

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("agentdesk.api")

app = FastAPI(
    title="AgentDesk",
    version="1.0.0",
    description="Multi-agent research & report orchestrator (LangGraph + MCP + RAG)",
)


class ReportRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


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
    return {
        "question": req.question,
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
