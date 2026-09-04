"""The MCP tool server. Runs as its own process: `python -m app.mcp.server`."""

import logging

from mcp.server.mcpserver import MCPServer

from app.mcp.tools import rag_search_impl, web_search_impl

mcp = MCPServer("agentdesk-tools")


@mcp.tool()
def web_search(query: str, max_results: int = 3) -> str:
    """Search the public web. Returns JSON: {provider, results:[{title,url,snippet}]}."""
    return web_search_impl(query, max_results)


@mcp.tool()
def rag_search(query: str, k: int = 4) -> str:
    """Search the internal knowledge base.

    Returns JSON: {provider, results: [{doc_id, file, chunk_index, score, content}]}.
    """
    return rag_search_impl(query, k)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    mcp.run()
