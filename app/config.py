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


DEPTHS = ("quick", "deep")


def resolve_depth(requested: str | None = None) -> str:
    """Normalise a per-request depth, falling back to AGENTDESK_DEPTH, then "deep".

    quick = the lean pipeline (no page reading, no query rewriting, no synthesis
    pass): fewer LLM and HTTP calls, for when latency or rate limits matter.
    deep = every specialist on.
    """
    for candidate in (requested, os.environ.get("AGENTDESK_DEPTH")):
        if candidate and candidate.strip().lower() in DEPTHS:
            return candidate.strip().lower()
    return "deep"


def agent_model(agent: str) -> str | None:
    """Model override for one agent (AGENTDESK_MODEL_<AGENT>), or None for the default.

    Lets the judgement-heavy agents (planner, synthesizer, critic) run on a
    stronger model than extraction and drafting, without paying for it everywhere.
    """
    return os.environ.get(f"AGENTDESK_MODEL_{agent.upper()}") or None


@dataclass(frozen=True)
class Settings:
    # LLM
    gemini_model: str
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
    retrieval_mode: str
    candidate_k: int
    rrf_k: int
    reranker: str
    rerank_model: str

    # Tools
    web_results: int
    tool_timeout: float
    max_concurrent_tool_calls: int
    fetch_pages: int
    fetch_max_chars: int
    query_rewrite: bool

    # Control loop
    max_revisions: int
    max_research_rounds: int


def get_settings() -> Settings:
    return Settings(
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest"),
        llm_max_attempts=_int("AGENTDESK_LLM_MAX_ATTEMPTS", 4),
        llm_backoff_base=_float("AGENTDESK_LLM_BACKOFF_BASE", 0.5),
        llm_timeout=_float("AGENTDESK_LLM_TIMEOUT", 60.0),
        embed_model=os.environ.get("AGENTDESK_EMBED_MODEL", "gemini-embedding-001"),
        embed_batch_size=_int("AGENTDESK_EMBED_BATCH_SIZE", 64),
        chroma_dir=os.environ.get("AGENTDESK_CHROMA_DIR", "./chroma_db"),
        collection_name=os.environ.get("AGENTDESK_COLLECTION", "agentdesk_docs"),
        chunk_size=_int("AGENTDESK_CHUNK_SIZE", 800),
        chunk_overlap=_int("AGENTDESK_CHUNK_OVERLAP", 150),
        retrieval_k=_int("AGENTDESK_RETRIEVAL_K", 4),
        # Cosine distance in [0, 2]. Calibrated on gemini-embedding-001 by
        # eval/run_retrieval_eval.py: every gold chunk sits within 0.375, every
        # off-topic question's nearest chunk beyond 0.42. The previous 0.65 was
        # tuned for OpenAI embeddings and let every off-topic question through.
        max_distance=_float("AGENTDESK_MAX_DISTANCE", 0.40),
        # dense | bm25 | hybrid. Dense is the default because it measured best on
        # this corpus (eval/run_retrieval_eval.py); hybrid fuses dense and BM25
        # with reciprocal rank fusion, for corpora heavy in exact identifiers.
        retrieval_mode=os.environ.get("AGENTDESK_RETRIEVAL_MODE", "dense").lower(),
        # How many candidates each retriever contributes before fusion/reranking.
        candidate_k=_int("AGENTDESK_CANDIDATE_K", 20),
        rrf_k=_int("AGENTDESK_RRF_K", 60),
        # none | cross-encoder. The cross-encoder needs `pip install .[rerank]`.
        reranker=os.environ.get("AGENTDESK_RERANKER", "none").lower(),
        rerank_model=os.environ.get("AGENTDESK_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2"),
        web_results=_int("AGENTDESK_WEB_RESULTS", 3),
        tool_timeout=_float("AGENTDESK_TOOL_TIMEOUT", 15.0),
        max_concurrent_tool_calls=_int("AGENTDESK_MAX_CONCURRENT_TOOL_CALLS", 4),
        # Pages the web researcher reads in full per round (0 turns it off), and how
        # much text of each reaches the Analyst (which caps a note at 2000 chars).
        fetch_pages=_int("AGENTDESK_FETCH_PAGES", 3),
        fetch_max_chars=_int("AGENTDESK_FETCH_MAX_CHARS", 1800),
        # Let the internal researcher reword a query that retrieved nothing, once.
        query_rewrite=_int("AGENTDESK_QUERY_REWRITE", 1) != 0,
        max_revisions=_int("AGENTDESK_MAX_REVISIONS", 2),
        max_research_rounds=_int("AGENTDESK_MAX_RESEARCH_ROUNDS", 1),
    )
