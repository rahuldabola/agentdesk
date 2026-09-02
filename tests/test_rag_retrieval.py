import app.rag.ingest as ingest_module
import app.rag.retriever as retriever_module


def test_ingest_and_retrieve(tmp_path, fake_embed, monkeypatch):
    monkeypatch.setenv("AGENTDESK_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(ingest_module, "COLLECTION_NAME", "test_collection")

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "doc1.md").write_text(
        "The on-call rotation is weekly and starts Monday at 9am.", encoding="utf-8"
    )
    (docs_dir / "doc2.md").write_text(
        "The API rate limit is 1000 requests per minute per key.", encoding="utf-8"
    )

    n = ingest_module.ingest_docs(docs_dir=str(docs_dir))
    assert n >= 2

    notes = retriever_module.rag_search("on-call rotation schedule", k=2)
    assert len(notes) >= 1
    assert notes[0]["source_type"] == "rag"
    assert notes[0]["source_id"].startswith("rag:")


def test_retrieve_empty_collection_returns_empty(tmp_path, fake_embed, monkeypatch):
    monkeypatch.setenv("AGENTDESK_CHROMA_DIR", str(tmp_path / "empty_chroma"))
    monkeypatch.setattr(ingest_module, "COLLECTION_NAME", "empty_collection")

    notes = retriever_module.rag_search("anything", k=2)
    assert notes == []
