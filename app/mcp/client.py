"""MCP client: one stdio session, reused across every tool call in a run.

Opening the session per call would spawn a fresh `python -m app.mcp.server`
subprocess, redo the initialize handshake, and rebuild the Chroma client for
each of the (subtasks x tools) calls a single question produces.
"""

import json
import logging
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.errors import ToolError

log = logging.getLogger("agentdesk.mcp")

SERVER_PARAMS = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp.server"])


@asynccontextmanager
async def mcp_session():
    """Yield an initialized MCP session backed by the tool server subprocess."""
    async with (
        stdio_client(SERVER_PARAMS) as (read, write),
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
