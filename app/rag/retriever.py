"""Query-time retrieval: hybrid dense + BM25 search, optional reranking, relevance floor.

Pipeline for one query:

  1. candidates   dense top-N from Chroma and/or BM25 top-N (N = candidate_k)
  2. fusion       reciprocal rank fusion of the two rankings (hybrid mode)
  3. reranking    optional cross-encoder pass over the fused candidates
  4. floor        drop anything whose cosine distance exceeds max_distance
  5. top-k        what the Researcher actually receives

Why each stage exists, with numbers, is in eval/run_retrieval_eval.py and the
"Retrieval quality" section of the README.
"""

import logging
import math

from app.config import get_settings
from app.errors import RetrievalError
from app.rag import bm25
from app.rag.ingest import embed_texts, get_chroma_collection
from app.rag.rerank import RerankerUnavailable, rerank_scores

log = logging.getLogger("agentdesk.rag")

MODES = ("dense", "bm25", "hybrid")
RERANKERS = ("none", "cross-encoder")


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal rank fusion: score(d) = sum over rankings of 1 / (k + rank).

    RRF uses only ranks, so it needs no calibration between a cosine distance
    and a BM25 score, which live on unrelated scales. Ties keep first-seen order.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda d: scores[d], reverse=True)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 1.0 - dot / norm if norm else 1.0


def retrieve(
    query: str,
    *,
    k: int,
    mode: str,
    reranker: str,
    max_distance: float,
    candidate_k: int,
    rrf_k: int = 60,
    rerank_model: str | None = None,
) -> list[dict]:
    """Ranked, floor-filtered chunks for `query`. Every knob is explicit here;
    `rag_search` below fills them from settings.

    Pass `max_distance=math.inf` to see the raw ranking without the floor.
    """
    if mode not in MODES:
        raise RetrievalError(f"unknown retrieval mode '{mode}' (expected one of {MODES})")
    if reranker not in RERANKERS:
        raise RetrievalError(f"unknown reranker '{reranker}' (expected one of {RERANKERS})")

    settings = get_settings()
    collection = get_chroma_collection()
    count = collection.count()
    if count == 0:
        log.warning("Chroma collection is empty - run `python -m scripts.ingest_docs` first")
        return []

    n = min(max(candidate_k, k), count)
    # The floor is a cosine distance, so the query is embedded in every mode -
    # BM25 alone cannot tell an off-topic question from an on-topic one.
    query_vec = embed_texts([query], task_type="RETRIEVAL_QUERY")[0]
    records: dict[str, dict] = {}

    dense_ids: list[str] = []
    if mode in ("dense", "hybrid"):
        res = collection.query(
            query_embeddings=[query_vec],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
        for doc_id, doc, meta, dist in zip(
            res["ids"][0],
            res["documents"][0],
            res["metadatas"][0],
            res["distances"][0],
            strict=True,
        ):
            dense_ids.append(doc_id)
            records[doc_id] = {"content": doc, "meta": meta or {}, "distance": dist}

    lexical_ids: list[str] = []
    if mode in ("bm25", "hybrid"):
        index = bm25.get_index(collection, (settings.chroma_dir, settings.collection_name))
        lexical_ids = [doc_id for doc_id, _ in index.search(query, n)]

    if mode == "dense":
        ranking = dense_ids
    elif mode == "bm25":
        ranking = lexical_ids
    else:
        ranking = rrf_fuse([dense_ids, lexical_ids], k=rrf_k)[:n]

    # BM25-only candidates have no distance yet; fetch their stored vectors.
    missing = [doc_id for doc_id in ranking if doc_id not in records]
    if missing:
        got = collection.get(ids=missing, include=["documents", "metadatas", "embeddings"])
        for doc_id, doc, meta, vec in zip(
            got["ids"], got["documents"], got["metadatas"], got["embeddings"], strict=True
        ):
            records[doc_id] = {
                "content": doc,
                "meta": meta or {},
                "distance": _cosine_distance(query_vec, list(vec)),
            }

    rerank_by_id: dict[str, float] = {}
    if reranker == "cross-encoder" and ranking:
        try:
            scores = rerank_scores(
                query,
                [records[d]["content"] for d in ranking],
                rerank_model or settings.rerank_model,
            )
            rerank_by_id = dict(zip(ranking, scores, strict=True))
            ranking = sorted(ranking, key=lambda d: rerank_by_id[d], reverse=True)
        except RerankerUnavailable as exc:
            log.warning("reranking skipped: %s", exc)

    notes = []
    for doc_id in ranking:
        rec = records[doc_id]
        if rec["distance"] > max_distance:
            continue
        note = {
            "doc_id": doc_id,
            "file": rec["meta"].get("source_file", doc_id.split("#")[0]),
            "chunk_index": rec["meta"].get("chunk_index"),
            "score": round(1.0 - rec["distance"], 4),
            "content": rec["content"],
        }
        if doc_id in rerank_by_id:
            note["rerank_score"] = round(rerank_by_id[doc_id], 4)
        notes.append(note)
        if len(notes) == k:
            break

    log.info(
        "retrieve(%r, mode=%s, reranker=%s): %d/%d candidates kept (distance <= %.2f)",
        query,
        mode,
        reranker,
        len(notes),
        len(ranking),
        max_distance,
    )
    return notes


def rag_search(
    query: str,
    k: int | None = None,
    max_distance: float | None = None,
    mode: str | None = None,
    reranker: str | None = None,
) -> list[dict]:
    """Return the chunks relevant enough to `query` to be worth grounding on.

    Top-k alone is not a relevance test: an off-topic question still returns k
    chunks, which the Analyst would then treat as evidence. Anything beyond
    `max_distance` (cosine) is dropped instead, in every retrieval mode.
    """
    settings = get_settings()
    return retrieve(
        query,
        k=settings.retrieval_k if k is None else k,
        mode=settings.retrieval_mode if mode is None else mode,
        reranker=settings.reranker if reranker is None else reranker,
        max_distance=settings.max_distance if max_distance is None else max_distance,
        candidate_k=settings.candidate_k,
        rrf_k=settings.rrf_k,
        rerank_model=settings.rerank_model,
    )
