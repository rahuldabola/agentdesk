"""Integration tests that exercise the real MCP client/server protocol.

Every other test in this suite calls the tool functions (web_search_impl,
rag_search_impl) directly as plain Python. That never proves the actual
production path works: app/mcp/client.py talks to app/mcp/server.py over a
JSON-RPC session (normally stdio), and that wiring (initialize handshake,
tool schema validation, request/response framing) is untested by unit-level
mocks alone.

These tests drive the real `MCPServer` instance from app/mcp/server.py
through a real `ClientSession`, connected via the mcp SDK's in-memory
transport instead of a subprocess+stdio pipe (a subprocess can't be
monkeypatched from the test process). Only the network/embedding calls at
the edges are mocked, so this stays offline and free like the rest of the
suite, while still proving the protocol layer itself works end to end.
"""

import asyncio
from unittest.mock import MagicMock, patch

import anyio
from mcp import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

import app.rag.ingest as ingest_module
from app.mcp.server import mcp as mcp_app


async def _call_tool_over_real_session(tool_name, arguments):
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        async with anyio.create_task_group() as tg:
            tg.start_soon(
                mcp_app._lowlevel_server.run,
                server_read,
                server_write,
                mcp_app._lowlevel_server.create_initialization_options(),
            )

            async with ClientSession(client_read, client_write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                text = "\n".join(part.text for part in result.content if hasattr(part, "text"))

            tg.cancel_scope.cancel()

    return text


def test_web_search_tool_over_real_mcp_session(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    html = """
    <div class="result__body">
      <a class="result__a" href="https://example.com">Example Title</a>
      <a class="result__snippet">Example snippet text.</a>
    </div>
    """
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.raise_for_status = MagicMock()

    with patch("app.mcp.tools.requests.get", return_value=mock_resp):
        text = asyncio.run(
            _call_tool_over_real_session("web_search", {"query": "test query", "max_results": 2})
        )

    assert "Example Title" in text
    assert "example.com" in text


def test_rag_search_tool_over_real_mcp_session(tmp_path, fake_embed, monkeypatch):
    monkeypatch.setenv("AGENTDESK_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(ingest_module, "COLLECTION_NAME", "mcp_integration_test")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "oncall.md").write_text(
        "The on-call rotation is weekly and starts Monday at 9am.", encoding="utf-8"
    )
    ingest_module.ingest_docs(docs_dir=str(docs_dir))

    text = asyncio.run(_call_tool_over_real_session("rag_search", {"query": "on-call rotation", "k": 2}))

    assert "[rag:oncall.md" in text
    assert "on-call rotation" in text
