"""Chunk -> embed -> upsert into a persistent Chroma collection."""

import glob
import logging
import os

import chromadb
import openai
from openai import OpenAI

from app.config import get_settings
from app.errors import ConfigurationError, RetrievalError
from app.util.retry import retry_call

log = logging.getLogger("agentdesk.rag")

# Cosine distance keeps the relevance threshold in app/config.py interpretable:
# 0 is identical, 1 is orthogonal. The default L2 space would make it depend on
# embedding magnitude, which is not a property we want a threshold to track.
COLLECTION_CONFIG = {"hnsw": {"space": "cosine"}}


def chunk_text(text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    """Fixed-width overlapping windows over the raw text."""
    settings = get_settings()
    chunk_size = settings.chunk_size if chunk_size is None else chunk_size
    overlap = settings.chunk_overlap if overlap is None else overlap
    if not text:
        return []
    step = max(chunk_size - overlap, 1)
    chunks = [text[start : start + chunk_size] for start in range(0, len(text), step)]
    return [c.strip() for c in chunks if c.strip()]


def get_openai_client() -> OpenAI:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ConfigurationError(
            "OPENAI_API_KEY is not set. Copy .env.example to .env and fill it in."
        )
    return OpenAI(api_key=key)


def _embeddings_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError)):
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code >= 500
    return False


def embed_texts(texts: list[str], client: OpenAI | None = None) -> list[list[float]]:
    """Embed in batches - one request per 10k texts is neither polite nor allowed."""
    if not texts:
        return []
    settings = get_settings()
    client = client or get_openai_client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), settings.embed_batch_size):
        batch = texts[start : start + settings.embed_batch_size]
        resp = retry_call(
            lambda b=batch: client.embeddings.create(model=settings.embed_model, input=b),
            attempts=settings.llm_max_attempts,
            base_delay=settings.llm_backoff_base,
            retryable=_embeddings_retryable,
            description="openai.embeddings.create",
        )
        vectors.extend(d.embedding for d in resp.data)
    return vectors


def get_chroma_collection():
    settings = get_settings()
    try:
        client = chromadb.PersistentClient(path=settings.chroma_dir)
        return client.get_or_create_collection(
            settings.collection_name, configuration=COLLECTION_CONFIG
        )
    except Exception as exc:
        raise RetrievalError(
            f"Could not open the Chroma collection '{settings.collection_name}' at "
            f"{settings.chroma_dir}: {exc}"
        ) from exc


def ingest_docs(docs_dir: str = "data/sample_docs") -> int:
    """Re-ingest every markdown file in docs_dir. Returns the chunk count written.

    Each file's existing chunks are deleted first, so shrinking or deleting
    content in a source doc does not leave orphaned chunks retrievable forever.
    """
    collection = get_chroma_collection()
    files = sorted(glob.glob(os.path.join(docs_dir, "*.md")))
    ids, docs, metadatas = [], [], []

    for path in files:
        fname = os.path.basename(path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        collection.delete(where={"source_file": fname})
        for i, chunk in enumerate(chunk_text(text)):
            ids.append(f"{fname}#{i}")
            docs.append(chunk)
            metadatas.append({"source_file": fname, "chunk_index": i})

    if not ids:
        log.warning("no markdown files found in %s", docs_dir)
        return 0

    log.info("embedding %d chunks from %d files", len(ids), len(files))
    collection.upsert(ids=ids, documents=docs, metadatas=metadatas, embeddings=embed_texts(docs))
    return len(ids)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    count = ingest_docs()
    print(
        f"Ingested {count} chunks into Chroma collection "
        f"'{settings.collection_name}' at {settings.chroma_dir}"
    )
