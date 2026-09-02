from mcp.server.mcpserver import MCPServer

from app.mcp.tools import rag_search_impl, web_search_impl

mcp = MCPServer("agentdesk-tools")


@mcp.tool()
def web_search(query: str, max_results: int = 4) -> str:
    """Search the public web and return titles, snippets, and URLs for the query."""
    return web_search_impl(query, max_results)


@mcp.tool()
def rag_search(query: str, k: int = 4) -> str:
    """Search the local internal knowledge base (engineering/policy docs) for relevant passages."""
    return rag_search_impl(query, k)


if __name__ == "__main__":
    mcp.run()
