from app.rag.ingest import chunk_text


def test_empty_text_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_short_text_is_a_single_chunk():
    assert chunk_text("hello world", chunk_size=100, overlap=10) == ["hello world"]


def test_chunks_respect_the_size_limit():
    text = "a" * 1000
    chunks = chunk_text(text, chunk_size=100, overlap=20)

    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) > 1


def test_consecutive_chunks_overlap():
    """Overlap is what keeps a fact that straddles a boundary retrievable."""
    text = "".join(chr(ord("a") + i % 26) for i in range(300))
    chunks = chunk_text(text, chunk_size=100, overlap=20)

    assert chunks[0][-20:] == chunks[1][:20]


def test_every_character_survives_chunking():
    text = "".join(chr(ord("a") + i % 26) for i in range(555))
    chunks = chunk_text(text, chunk_size=100, overlap=20)

    rebuilt = chunks[0]
    for nxt in chunks[1:]:
        rebuilt += nxt[20:]
    assert rebuilt == text


def test_overlap_at_or_above_chunk_size_still_makes_progress():
    """A misconfigured overlap must not produce an infinite loop."""
    chunks = chunk_text("abcdef", chunk_size=3, overlap=5)

    assert len(chunks) == 6


def test_chunk_size_falls_back_to_settings(monkeypatch):
    monkeypatch.setenv("AGENTDESK_CHUNK_SIZE", "10")
    monkeypatch.setenv("AGENTDESK_CHUNK_OVERLAP", "0")

    assert chunk_text("x" * 30) == ["x" * 10] * 3
