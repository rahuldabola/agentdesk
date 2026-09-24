"""Hybrid retrieval: BM25, rank fusion, reranking, and the floor across modes.

Runs against a real Chroma store with fake embeddings, like test_rag_retrieval.
"""

import math

import pytest

import app.rag.ingest as ingest_module
from app.errors import RetrievalError
from app.rag import bm25
from app.rag.rerank import RerankerUnavailable
from app.rag.retriever import rag_search, retrieve, rrf_fuse

ERRORS = """# Error Codes

- `AUTH-1003` - the token was revoked by an administrator.
"""

ONCALL = """# On-call

The on-call rotation is weekly and hands over on Monday morning.
"""

BILLING = """# Billing

Refunds up to five hundred dollars need no approval from anyone.
"""


@pytest.fixture
def corpus(tmp_path, isolated_chroma, fake_embed):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "errors.md").write_text(ERRORS, encoding="utf-8")
    (docs / "oncall.md").write_text(ONCALL, encoding="utf-8")
    (docs / "billing.md").write_text(BILLING, encoding="utf-8")
    ingest_module.ingest_docs(docs_dir=str(docs))
    return docs


def _search(query, **overrides):
    params = {
        "k": 3,
        "mode": "hybrid",
        "reranker": "none",
        "max_distance": math.inf,
        "candidate_k": 10,
    }
    params.update(overrides)
    return retrieve(query, **params)


# ----------------------------------------------------------------------------- BM25


def test_tokenize_keeps_identifiers_whole_and_in_parts():
    tokens = bm25.tokenize("What does AUTH-1003 mean?")

    assert "auth-1003" in tokens
    assert {"auth", "1003"} <= set(tokens)
    assert "what" not in tokens, "stopwords carry no lexical signal"


def test_tokenize_folds_plurals():
    assert bm25.tokenize("deploys") == bm25.tokenize("deploy")


def test_bm25_ranks_the_exact_identifier_first():
    index = bm25.BM25Index.build(
        ["a", "b", "c"],
        ["AUTH-1003 token revoked", "AUTH-1007 missing scope", "weekly on-call rotation"],
    )

    hits = index.search("AUTH-1003", top_n=3)

    assert hits[0][0] == "a"
    assert "c" not in [doc_id for doc_id, _ in hits], "no shared term, no score"


def test_bm25_on_an_empty_query_returns_nothing():
    index = bm25.BM25Index.build(["a"], ["some text"])

    assert index.search("the of and", top_n=5) == []


# ----------------------------------------------------------------------------- fusion


def test_rrf_rewards_agreement_between_rankings():
    fused = rrf_fuse([["a", "b", "c"], ["b", "c", "a"]])

    assert fused[0] == "b", "ranked 2nd and 1st beats 1st and 3rd"
    assert set(fused) == {"a", "b", "c"}


def test_rrf_keeps_documents_only_one_ranking_found():
    assert rrf_fuse([["a"], ["z"]]) == ["a", "z"]


# ----------------------------------------------------------------------------- retrieve


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_every_mode_returns_provenance(corpus, mode):
    notes = _search("AUTH-1003 revoked token", mode=mode)

    assert notes
    assert {"doc_id", "file", "chunk_index", "score", "content"} <= set(notes[0])
    assert 0.0 <= notes[0]["score"] <= 1.0


def test_hybrid_puts_the_exact_identifier_match_first(corpus):
    notes = _search("AUTH-1003", mode="hybrid")

    assert notes[0]["file"] == "errors.md"


def test_bm25_only_candidates_still_face_the_relevance_floor(corpus):
    """BM25 cannot tell on-topic from off-topic, so its hits get a real distance too."""
    assert _search("AUTH-1003", mode="bm25")
    assert _search("AUTH-1003", mode="bm25", max_distance=0.0) == []


def test_floor_is_applied_before_truncating_to_k(corpus):
    notes = _search("AUTH-1003 token", k=1, max_distance=math.inf)

    assert len(notes) == 1


def test_unknown_mode_is_rejected(corpus):
    with pytest.raises(RetrievalError, match="retrieval mode"):
        _search("anything", mode="semantic")


def test_unknown_reranker_is_rejected(corpus):
    with pytest.raises(RetrievalError, match="reranker"):
        _search("anything", reranker="gpt")


def test_reranker_reorders_candidates(corpus, monkeypatch):
    def prefer_billing(query, documents, model_name):
        return [10.0 if "Refunds" in d else 0.0 for d in documents]

    monkeypatch.setattr("app.rag.retriever.rerank_scores", prefer_billing)

    notes = _search("AUTH-1003", reranker="cross-encoder")

    assert notes[0]["file"] == "billing.md"
    assert notes[0]["rerank_score"] == 10.0


def test_missing_reranker_falls_back_to_the_fused_ranking(corpus, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RerankerUnavailable("fastembed not installed")

    monkeypatch.setattr("app.rag.retriever.rerank_scores", unavailable)

    notes = _search("AUTH-1003", reranker="cross-encoder")

    assert notes[0]["file"] == "errors.md"
    assert "rerank_score" not in notes[0]


def test_rag_search_reads_mode_and_reranker_from_settings(corpus, monkeypatch):
    monkeypatch.setenv("AGENTDESK_RETRIEVAL_MODE", "bm25")
    monkeypatch.setenv("AGENTDESK_MAX_DISTANCE", "2.0")

    assert rag_search("xyzzy plugh") == [], "bm25 mode has nothing to offer here"
    assert rag_search("xyzzy plugh", mode="dense"), "an explicit mode wins"


def test_reingest_refreshes_the_bm25_index(corpus):
    assert _search("quarantine", mode="bm25") == []

    (corpus / "billing.md").write_text("Flaky tests go to quarantine.", encoding="utf-8")
    ingest_module.ingest_docs(docs_dir=str(corpus))

    notes = _search("quarantine", mode="bm25")
    assert notes and notes[0]["file"] == "billing.md"
