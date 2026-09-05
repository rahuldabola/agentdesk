from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from app.graph import run_agentdesk  # noqa: E402
from app.llm.claude_client import LLMQuotaError  # noqa: E402

app = FastAPI(
    title="AgentDesk",
    description="Multi-agent research & report orchestrator (LangGraph + MCP + RAG)",
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ReportRequest(BaseModel):
    question: str


@app.get("/")
def ui():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/report")
async def create_report(req: ReportRequest):
    try:
        result = await run_in_threadpool(run_agentdesk, req.question)
    except LLMQuotaError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {
        "question": req.question,
        "report": result.get("final_report"),
        "citations": result.get("citations", []),
        "revisions": result.get("revision_count", 0),
        "trace": result.get("trace", []),
    }
