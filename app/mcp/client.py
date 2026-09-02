import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_PARAMS = StdioServerParameters(command=sys.executable, args=["-m", "app.mcp.server"])


@asynccontextmanager
async def mcp_session():
    async with stdio_client(SERVER_PARAMS) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_tool(tool_name: str, arguments: dict) -> str:
    """Call an AgentDesk MCP tool over stdio and return its text output."""
    async with mcp_session() as session:
        result = await session.call_tool(tool_name, arguments)
        return "\n".join(part.text for part in result.content if hasattr(part, "text"))
