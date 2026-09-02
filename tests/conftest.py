import pytest


def _fake_embed_texts(texts, client=None):
    """Deterministic, dependency-free stand-in for OpenAI embeddings."""
    vectors = []
    for t in texts:
        v = [0.0] * 8
        for i, ch in enumerate(t):
            v[i % 8] += ord(ch)
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        vectors.append([x / norm for x in v])
    return vectors


@pytest.fixture
def fake_embed(monkeypatch):
    monkeypatch.setattr("app.rag.ingest.embed_texts", _fake_embed_texts)
    monkeypatch.setattr("app.rag.retriever.embed_texts", _fake_embed_texts)
    return _fake_embed_texts
