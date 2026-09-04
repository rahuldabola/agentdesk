"""Smoke-test the MCP tool server over a real stdio subprocess.

The protocol tests in tests/test_mcp_protocol_integration.py use the SDK's
in-memory transport so the tools' dependencies stay patchable. That leaves one
thing unproven: that `python -m app.mcp.server` actually starts as its own
process and completes a handshake over stdio pipes - the path production uses.

Runs without any API key: it queries an empty knowledge base, which the
retriever handles by returning no results rather than embedding anything.
"""

import asyncio
import sys
import tempfile

from app.mcp.client import call_tool, mcp_session

EXPECTED_TOOLS = {"rag_search", "web_search"}


async def check() -> None:
    async with mcp_session() as session:
        listed = await session.list_tools()
        names = {t.name for t in listed.tools}
        assert names == EXPECTED_TOOLS, f"expected {EXPECTED_TOOLS}, got {names}"
        print(f"ok: subprocess handshake complete, tools declared: {sorted(names)}")

        payload = await call_tool(session, "rag_search", {"query": "smoke test", "k": 1})
        assert payload["provider"] == "chroma", payload
        assert payload["results"] == [], f"expected no hits from an empty store, got {payload}"
        print("ok: rag_search returned a well-formed JSON payload over stdio")


def main() -> int:
    # Point at a throwaway store so the check never depends on, or disturbs,
    # a real ingested collection.
    import os

    os.environ["AGENTDESK_CHROMA_DIR"] = tempfile.mkdtemp()
    os.environ["AGENTDESK_COLLECTION"] = "agentdesk-smoke"
    try:
        asyncio.run(check())
    except Exception as exc:
        print(f"MCP stdio smoke test FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("MCP stdio smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
