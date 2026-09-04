"""Query-time retrieval, with a relevance floor so off-topic chunks stay out."""

import logging

from app.config import get_settings
from app.rag.ingest import embed_texts, get_chroma_collection

log = logging.getLogger("agentdesk.rag")


def rag_search(query: str, k: int | None = None, max_distance: float | None = None) -> list[dict]:
    """Return the chunks similar enough to `query` to be worth grounding on.

    Top-k alone is not a relevance test: an empty-ish or off-topic question still
    returns k chunks, which the Analyst would then treat as evidence. Anything
    beyond `max_distance` (cosine) is dropped instead.
    """
    settings = get_settings()
    k = settings.retrieval_k if k is None else k
    max_distance = settings.max_distance if max_distance is None else max_distance

    collection = get_chroma_collection()
    count = collection.count()
    if count == 0:
        log.warning("Chroma collection is empty - run `python -m scripts.ingest_docs` first")
        return []

    results = collection.query(
        query_embeddings=[embed_texts([query])[0]],
        n_results=min(k, count),
        include=["documents", "metadatas", "distances"],
    )
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    ids = results.get("ids", [[]])[0]
    distances = results.get("distances", [[]])[0]

    notes = []
    for doc, meta, doc_id, distance in zip(docs, metas, ids, distances, strict=True):
        if distance is not None and distance > max_distance:
            continue
        meta = meta or {}
        notes.append(
            {
                "doc_id": doc_id,
                "file": meta.get("source_file", doc_id.split("#")[0]),
                "chunk_index": meta.get("chunk_index"),
                "score": round(1.0 - distance, 4) if distance is not None else None,
                "content": doc,
            }
        )

    log.info(
        "rag_search(%r): %d/%d chunks passed the relevance floor (distance <= %.2f)",
        query,
        len(notes),
        len(docs),
        max_distance,
    )
    return notes
