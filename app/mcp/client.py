"""MCP client: one stdio session, reused across every tool call in a run.

Opening the session per call would spawn a fresh `python -m app.mcp.server`
subprocess, redo the initialize handshake, and rebuild the Chroma client for
each of the (subtasks x tools) calls a single question produces.
"""

import json
import logging
import os
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.errors import ToolError

log = logging.getLogger("agentdesk.mcp")


def _server_params() -> StdioServerParameters:
    """Built fresh per session, not cached at import time.

    mcp's stdio_client only forwards a small allowlisted subset of the parent's
    environment by default (PATH, HOME, etc - deliberately not API keys, since
    an MCP server is normally someone else's process). Ours is our own trusted
    subprocess and needs the real environment: GEMINI_API_KEY, TAVILY_API_KEY,
    and every AGENTDESK_* setting app/config.py reads at call time. Reading
    os.environ here (rather than once at import time) matters because
    `load_dotenv()` in app/main.py runs after app.mcp.client is first imported.
    """
    return StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp.server"], env=dict(os.environ)
    )


@asynccontextmanager
async def mcp_session():
    """Yield an initialized MCP session backed by the tool server subprocess."""
    async with (
        stdio_client(_server_params()) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        log.debug("MCP session initialized")
        yield session


async def call_tool(session, tool_name: str, arguments: dict) -> dict:
    """Call a tool over an existing session and return its parsed JSON payload."""
    result = await session.call_tool(tool_name, arguments)
    if getattr(result, "isError", False):
        raise ToolError(f"MCP tool '{tool_name}' reported an error: {result.content}")

    text = "\n".join(part.text for part in result.content if hasattr(part, "text"))
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError(
            f"MCP tool '{tool_name}' returned a non-JSON payload: {text[:200]!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise ToolError(
            f"MCP tool '{tool_name}' returned {type(payload).__name__}, expected an object"
        )
    return payload
