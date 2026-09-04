"""Shared fixtures. Every test in this suite runs offline and costs nothing.

The only things mocked are the true edges of the system: the Anthropic API,
the OpenAI embeddings API, and outbound HTTP. Chroma, LangGraph, and the MCP
client/server protocol all run for real - see tests/doubles.py.
"""

import pytest

import app.llm.claude_client as claude_client
from tests.doubles import fake_embed_texts, flatten_exception, in_memory_mcp_session

__all__ = ["fake_embed_texts", "flatten_exception", "in_memory_mcp_session"]


@pytest.fixture
def fake_embed(monkeypatch):
    monkeypatch.setattr("app.rag.ingest.embed_texts", fake_embed_texts)
    monkeypatch.setattr("app.rag.retriever.embed_texts", fake_embed_texts)
    return fake_embed_texts


@pytest.fixture
def isolated_chroma(tmp_path, monkeypatch):
    """Point the whole app at a throwaway Chroma directory and collection."""
    monkeypatch.setenv("AGENTDESK_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("AGENTDESK_COLLECTION", "agentdesk-test")
    return tmp_path


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if a test reaches for the network by accident."""

    def _boom(*args, **kwargs):
        raise AssertionError("a test attempted a real HTTP request")

    monkeypatch.setattr("app.mcp.tools.requests.get", _boom)
    monkeypatch.setattr("app.mcp.tools.requests.post", _boom)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def reset_llm_client():
    """The Anthropic client is cached; drop it between tests."""
    claude_client.reset_client()
    yield
    claude_client.reset_client()


@pytest.fixture
def real_mcp_session(monkeypatch):
    """Make the Researcher talk to the real MCP server without spawning a process."""
    monkeypatch.setattr("app.agents.researcher.mcp_session", in_memory_mcp_session)
    return in_memory_mcp_session
