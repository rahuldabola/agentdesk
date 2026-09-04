"""Tests that exercise the real MCP client/server protocol.

Unit tests call `web_search_impl` / `rag_search_impl` as plain Python, which
never proves the production path works: the Researcher talks to
`app/mcp/server.py` over a JSON-RPC session. These drive the real `MCPServer`
through a real `ClientSession` (in-memory transport, so no subprocess to
monkeypatch), exercising the initialize handshake, the declared tool schemas,
and `app/mcp/client.py`'s own payload parsing.
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

import app.rag.ingest as ingest_module
from app.errors import ToolError
from app.mcp.client import call_tool
from tests.doubles import flatten_exception, in_memory_mcp_session

DDG_HTML = """
<div class="result__body">
  <a class="result__a" href="https://example.com">Example Title</a>
  <a class="result__snippet">Example snippet text.</a>
</div>
"""


async def _call(tool_name, arguments):
    async with in_memory_mcp_session() as session:
        return await call_tool(session, tool_name, arguments)


async def _list_tools():
    async with in_memory_mcp_session() as session:
        return await session.list_tools()


def test_the_server_declares_both_tools_with_schemas():
    result = asyncio.run(_list_tools())
    tools = {t.name: t for t in result.tools}

    assert set(tools) == {"web_search", "rag_search"}
    assert "query" in tools["rag_search"].input_schema["properties"]
    assert "max_results" in tools["web_search"].input_schema["properties"]
    assert tools["rag_search"].description


def test_web_search_over_a_real_session(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    resp = MagicMock()
    resp.text = DDG_HTML
    resp.raise_for_status = MagicMock()

    with patch("app.mcp.tools.requests.get", return_value=resp):
        payload = asyncio.run(_call("web_search", {"query": "test", "max_results": 2}))

    assert payload["provider"] == "duckduckgo"
    assert payload["results"][0]["title"] == "Example Title"
    assert payload["results"][0]["url"] == "https://example.com"


def test_rag_search_over_a_real_session(tmp_path, isolated_chroma, fake_embed):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "oncall.md").write_text(
        "The on-call rotation is weekly and starts Monday at 9am.", encoding="utf-8"
    )
    ingest_module.ingest_docs(docs_dir=str(docs))

    payload = asyncio.run(_call("rag_search", {"query": "on-call rotation", "k": 2}))

    assert payload["provider"] == "chroma"
    assert payload["results"][0]["doc_id"].startswith("oncall.md#")
    assert "on-call rotation" in payload["results"][0]["content"]


def test_concurrent_tool_calls_share_one_session(tmp_path, isolated_chroma, fake_embed):
    """The Researcher fans out over a single session; the protocol must cope."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "oncall.md").write_text("Weekly on-call rotation.", encoding="utf-8")
    ingest_module.ingest_docs(docs_dir=str(docs))

    async def fan_out():
        async with in_memory_mcp_session() as session:
            return await asyncio.gather(
                *(
                    call_tool(session, "rag_search", {"query": f"query {i}", "k": 1})
                    for i in range(5)
                )
            )

    payloads = asyncio.run(fan_out())

    assert len(payloads) == 5
    assert all(p["provider"] == "chroma" for p in payloads)


def test_a_non_json_tool_payload_is_reported_as_a_tool_error(monkeypatch):
    """A tool that stops returning JSON must fail loudly, not silently yield nothing."""
    monkeypatch.setattr("app.mcp.server.rag_search_impl", lambda query, k=4: "not json at all")

    with pytest.raises(BaseException) as caught:
        asyncio.run(_call("rag_search", {"query": "q", "k": 1}))

    errors = flatten_exception(caught.value)
    assert any(isinstance(e, ToolError) and "non-JSON payload" in str(e) for e in errors), errors


def test_calling_an_undeclared_tool_fails_loudly():
    """The server must reject an unknown tool rather than answering it."""
    with pytest.raises(BaseException) as caught:  # noqa: B017 - anyio wraps the real cause
        asyncio.run(_call("no_such_tool", {}))

    messages = " ".join(str(e) for e in flatten_exception(caught.value)).lower()
    assert "no_such_tool" in messages or "unknown tool" in messages, messages
