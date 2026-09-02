from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from app.graph import run_agentdesk

app = FastAPI(
    title="AgentDesk",
    description="Multi-agent research & report orchestrator (LangGraph + MCP + RAG)",
)


class ReportRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/report")
async def create_report(req: ReportRequest):
    result = await run_in_threadpool(run_agentdesk, req.question)
    return {
        "question": req.question,
        "report": result.get("final_report"),
        "citations": result.get("citations", []),
        "revisions": result.get("revision_count", 0),
        "trace": result.get("trace", []),
    }
