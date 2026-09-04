"""Retrieval tests run against a real Chroma store; only embeddings are faked."""

import pytest

import app.rag.ingest as ingest_module
from app.rag.retriever import rag_search

HANDBOOK = """# Engineering Handbook

## On-call Rotation

On-call is a weekly rotation starting Monday at 09:00 UTC.
"""

SECURITY = """# Security Policy

## Secrets

Secrets live in the vault and rotate every 90 days.
"""


@pytest.fixture
def corpus(tmp_path, isolated_chroma, fake_embed):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "handbook.md").write_text(HANDBOOK, encoding="utf-8")
    (docs / "security.md").write_text(SECURITY, encoding="utf-8")
    ingest_module.ingest_docs(docs_dir=str(docs))
    return docs


def test_search_on_an_empty_collection_returns_nothing(isolated_chroma, fake_embed):
    assert rag_search("anything") == []


def test_ingest_reports_the_chunk_count(corpus):
    assert ingest_module.get_chroma_collection().count() == 2


def test_results_carry_resolvable_provenance(corpus):
    notes = rag_search("on-call rotation weekly Monday", max_distance=2.0)

    assert notes
    note = notes[0]
    assert note["doc_id"].endswith("#0")
    assert note["file"] in {"handbook.md", "security.md"}
    assert note["chunk_index"] == 0
    assert 0.0 <= note["score"] <= 1.0
    assert "rotation" in note["content"] or "Secrets" in note["content"]


def test_results_are_ordered_by_similarity(corpus):
    notes = rag_search("on-call rotation weekly Monday", max_distance=2.0)

    scores = [n["score"] for n in notes]
    assert scores == sorted(scores, reverse=True)


def test_k_bounds_the_result_count(corpus):
    assert len(rag_search("on-call", k=1, max_distance=2.0)) == 1


def test_the_relevance_floor_drops_distant_chunks(corpus):
    """Top-k alone is not a relevance test - an unrelated query must return nothing."""
    permissive = rag_search("on-call rotation", max_distance=2.0)
    strict = rag_search("on-call rotation", max_distance=0.0)

    assert permissive, "sanity: the corpus is searchable"
    assert strict == [], "a zero-distance floor must admit nothing but an exact match"


def test_the_floor_is_configurable_by_environment(corpus, monkeypatch):
    monkeypatch.setenv("AGENTDESK_MAX_DISTANCE", "0.0")

    assert rag_search("on-call rotation") == []


def test_reingesting_a_shrunken_document_removes_its_stale_chunks(corpus, tmp_path):
    """Otherwise deleted content stays retrievable, and citable, forever."""
    big = "para one.\n\n" + ("filler text. " * 200)
    (corpus / "handbook.md").write_text(big, encoding="utf-8")
    ingest_module.ingest_docs(docs_dir=str(corpus))
    before = ingest_module.get_chroma_collection().count()

    (corpus / "handbook.md").write_text("para one.", encoding="utf-8")
    ingest_module.ingest_docs(docs_dir=str(corpus))
    after = ingest_module.get_chroma_collection().count()

    assert before > after
    contents = " ".join(n["content"] for n in rag_search("filler", max_distance=2.0))
    assert "filler text" not in contents
