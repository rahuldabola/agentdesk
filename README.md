# AgentDesk — Multi-Agent Research & Report Orchestrator

[![Tests](https://github.com/rahuldabola/agentdesk/actions/workflows/tests.yml/badge.svg)](https://github.com/rahuldabola/agentdesk/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A LangGraph-based multi-agent system that turns a question into a cited, fact-checked report,
using MCP (Model Context Protocol) for tool access and a RAG pipeline over a local knowledge
base for grounding.

## The problem this solves

A single LLM call answering a research question either hallucinates unsupported claims or
gives a shallow, uncited answer. This project splits the work across five specialized agents
with a self-correction loop, and grounds every claim in a retrievable source — either an
internal document (via RAG) or a live web result (via a real MCP tool server) — so the output
is auditable, not just plausible-sounding text.

## Architecture

```
question
   |
   v
[Planner]  -- decomposes the question into subtasks, decides which tools are needed
   |
   v
[Researcher] -- calls an MCP tool server over stdio (real MCP protocol, not hardcoded functions)
   |             - rag_search: embeds the query, retrieves top-k chunks from a Chroma vector store
   |             - web_search: Tavily API, or DuckDuckGo HTML scrape as a free fallback
   v
[Analyst]  -- extracts atomic factual claims from raw notes, each tagged with its source_id
   |
   v
[Writer]   -- drafts a report citing only the extracted facts, inline [source_id] citations
   |
   v
[Critic]   -- checks the draft against the facts; flags unsupported claims or missing citations
   |
   +-- verdict = revise (< 2 revisions so far) --> back to [Writer], with feedback
   |
   +-- verdict = pass, or revision cap reached --> final report
```

State is passed through a `langgraph.graph.StateGraph`; each node returns a partial update
that LangGraph merges into the running state (Planner → Researcher → Analyst → Writer →
Critic, with a conditional edge looping Critic back to Writer).

## Why MCP instead of calling tools directly

The Researcher agent doesn't call Python functions directly — it talks to `app/mcp/server.py`
(an `MCPServer` from the official `mcp` SDK) over a real stdio JSON-RPC session via
`app/mcp/client.py`. This is the actual point of MCP: the tool server is a separate process
with a declared tool schema, callable by any MCP-compatible client, not just this codebase.

## Why RAG instead of stuffing docs into the prompt

`app/rag/ingest.py` chunks markdown docs (800 chars, 150-char overlap), embeds them with
OpenAI's `text-embedding-3-small`, and stores them in a persistent Chroma collection.
`app/rag/retriever.py` embeds the query and retrieves the top-k most similar chunks. This
scales to a knowledge base far larger than a context window, and only pulls in what's
actually relevant to the question.

## Tech stack

- **Orchestration:** LangGraph (`app/graph.py`) — explicit state machine, not a fixed chain
- **LLM:** Claude or Gemini (`app/llm/claude_client.py`), selected via `AI_PROVIDER`
  (`anthropic` or `gemini`) — structured JSON-schema outputs are forced via tool/function
  calling for the Planner/Analyst/Critic, matching the function-calling + structured-output
  pattern used in production RAG pipelines
- **Embeddings + vector store:** OpenAI `text-embedding-3-small` + Chroma (persistent, local)
- **Tool access:** MCP (`mcp` SDK) — a real client/server pair over stdio, not hardcoded calls
- **Web search:** Tavily API if `TAVILY_API_KEY` is set, else a best-effort DuckDuckGo HTML
  scrape (DuckDuckGo actively rate-limits/blocks scripted requests, so Tavily's free tier is
  the reliable path — the fallback exists so the tool never hard-fails, not as the primary path)
- **API + UI:** FastAPI (`app/main.py`), `POST /api/report {"question": "..."}`, plus a static
  web UI (`app/static/`) served at `/`
- **Tests:** pytest, 19 tests, all mocking the LLM/embedding/network calls so the suite runs
  fully offline with zero API cost — verifies graph wiring (including the revise-loop), each
  agent's parsing logic, chunking, retrieval, and the web-search tool's HTML parsing. Two of
  these drive the real `MCPServer` through an actual `ClientSession` over the mcp SDK's
  in-memory transport (`tests/test_mcp_protocol_integration.py`), proving the JSON-RPC
  initialize/call_tool wiring works end to end rather than only testing the tool functions
  as plain Python. CI also boots `uvicorn app.main:app` and polls `/health` after the test
  suite, catching import-time/startup breakage that a mocked test suite can't see.

## Evaluation

`eval/eval_set.json` has 6 questions spanning RAG-only, web-only, and both-needed cases.
`eval/run_eval.py` runs each through the full graph and reports:

- **task_completion_rate** — did a final report get produced
- **critic_revision_rate** — how often the Critic's first draft got rejected
- **tool_routing_accuracy** — did the Planner's use_rag/use_web decision match what the
  question actually needed
- **citation_coverage** — did the final report carry at least one citation

These are deterministic, heuristic checks rather than an LLM-judge score — cheap to run and
reproducible. Running this requires your own `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` (real
LLM/embedding calls); results aren't checked into this repo since they'd cost real API credits
to regenerate and would go stale. The natural next step, noted here rather than built, is
adding an LLM-as-judge faithfulness score once a labeled answer key exists.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # or: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in ANTHROPIC_API_KEY and OPENAI_API_KEY
python -m scripts.ingest_docs # embeds data/sample_docs/*.md into a local Chroma store
python -m scripts.run_demo "What is our on-call rotation and how does it compare to typical SRE practice?"
```

Or run it as an API + web UI:

```bash
uvicorn app.main:app --reload
# UI:  http://localhost:8000/
# API: POST http://localhost:8000/api/report  {"question": "..."}
```

The UI (`app/static/`) is a static HTML/CSS/JS page served directly by FastAPI — no build step.
It posts to `/api/report` and renders the final report (with inline `[source_id]` citations
highlighted), the citation list, the revision badge, and the full agent trace returned by the
graph.

Run the offline test suite (no API keys needed):

```bash
pytest -v
```

## Suggested resume bullets

- Built a multi-agent research system (LangGraph) with five specialized agents and a
  self-correcting Critic → Writer feedback loop that caps hallucinated/uncited claims before
  they reach the final report
- Implemented tool access via the Model Context Protocol (MCP), running a real client/server
  pair over stdio rather than hardcoded function calls, exposing web search and RAG retrieval
  as declared, schema-typed tools
- Built a RAG pipeline (chunking, OpenAI embeddings, Chroma vector store) grounding agent
  outputs in a local document corpus, with inline per-claim source citation
- Forced structured JSON-schema outputs from Claude via tool use for every agent decision
  point (planning, fact extraction, critique verdicts), eliminating brittle free-text parsing
- Wrote a fully offline test suite (17 tests) mocking LLM/embedding calls to verify agent
  logic, graph control flow, and the revision loop without incurring API cost per test run
