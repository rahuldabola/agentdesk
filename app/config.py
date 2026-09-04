"""Central settings, read from the environment at call time.

Read-at-call-time (rather than import-time constants) keeps tests able to
monkeypatch a single env var without reimporting half the package.
"""

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return default if raw in (None, "") else int(raw)


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return default if raw in (None, "") else float(raw)


@dataclass(frozen=True)
class Settings:
    # LLM
    anthropic_model: str
    llm_max_attempts: int
    llm_backoff_base: float
    llm_timeout: float

    # Embeddings + vector store
    embed_model: str
    embed_batch_size: int
    chroma_dir: str
    collection_name: str
    chunk_size: int
    chunk_overlap: int
    retrieval_k: int
    max_distance: float

    # Tools
    web_results: int
    tool_timeout: float
    max_concurrent_tool_calls: int

    # Control loop
    max_revisions: int
    max_research_rounds: int


def get_settings() -> Settings:
    return Settings(
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
        llm_max_attempts=_int("AGENTDESK_LLM_MAX_ATTEMPTS", 4),
        llm_backoff_base=_float("AGENTDESK_LLM_BACKOFF_BASE", 0.5),
        llm_timeout=_float("AGENTDESK_LLM_TIMEOUT", 60.0),
        embed_model=os.environ.get("AGENTDESK_EMBED_MODEL", "text-embedding-3-small"),
        embed_batch_size=_int("AGENTDESK_EMBED_BATCH_SIZE", 64),
        chroma_dir=os.environ.get("AGENTDESK_CHROMA_DIR", "./chroma_db"),
        collection_name=os.environ.get("AGENTDESK_COLLECTION", "agentdesk_docs"),
        chunk_size=_int("AGENTDESK_CHUNK_SIZE", 800),
        chunk_overlap=_int("AGENTDESK_CHUNK_OVERLAP", 150),
        retrieval_k=_int("AGENTDESK_RETRIEVAL_K", 4),
        # Cosine distance in [0, 2]. Unrelated text against text-embedding-3-small
        # typically lands above 0.7; genuinely on-topic chunks sit well below it.
        max_distance=_float("AGENTDESK_MAX_DISTANCE", 0.65),
        web_results=_int("AGENTDESK_WEB_RESULTS", 3),
        tool_timeout=_float("AGENTDESK_TOOL_TIMEOUT", 15.0),
        max_concurrent_tool_calls=_int("AGENTDESK_MAX_CONCURRENT_TOOL_CALLS", 4),
        max_revisions=_int("AGENTDESK_MAX_REVISIONS", 2),
        max_research_rounds=_int("AGENTDESK_MAX_RESEARCH_ROUNDS", 1),
    )
