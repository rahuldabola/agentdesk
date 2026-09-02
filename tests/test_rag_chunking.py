from app.rag.ingest import chunk_text


def test_chunk_text_basic():
    text = "a" * 2000
    chunks = chunk_text(text, chunk_size=800, overlap=150)
    assert len(chunks) >= 2
    assert all(len(c) <= 800 for c in chunks)


def test_chunk_text_empty():
    assert chunk_text("") == []


def test_chunk_text_short_text_single_chunk():
    assert chunk_text("hello world", chunk_size=800, overlap=150) == ["hello world"]
