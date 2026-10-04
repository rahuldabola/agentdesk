"""Public benchmark: the production retrieval code on BEIR SciFact.

The in-house retrieval benchmark (run_retrieval_eval.py) uses a corpus and
questions written by the same author, so it could flatter the system. This
runs the same `app.rag.retriever.retrieve` - Chroma, the BM25 index, reciprocal
rank fusion, the cross-encoder - over a public dataset with independent
relevance labels:

  BEIR SciFact   5,183 scientific abstracts, 300 test claims, expert qrels
                 (Thakur et al., 2021: https://github.com/beir-cellar/beir)

Embeddings come from a small local model (BAAI/bge-small-en-v1.5 via
fastembed) rather than Gemini: embedding 5k abstracts on the Gemini free tier
is impractical, and a local model keeps the run free and reproducible. What is
being tested is the retrieval *pipeline* - does BM25 behave like published
BM25, does fusion or reranking help - not Gemini.

Documents are indexed whole (SciFact abstracts are the retrieval unit), so the
metrics are the standard BEIR ones: nDCG@10 and Recall@10 over document ids.
"""

import argparse
import io
import json
import math
import os
import statistics
import sys
import tempfile
import time
import urllib.request
import zipfile
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(EVAL_DIR)
README_PATH = os.path.join(REPO_ROOT, "README.md")
CACHE_DIR = os.path.join(EVAL_DIR, ".cache")
RESULTS_PATH = os.path.join(EVAL_DIR, "results_beir.json")
DATASET_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CANDIDATES = 20
CONFIGS = (
    ("dense", "dense", "none"),
    ("bm25", "bm25", "none"),
    ("hybrid", "hybrid", "none"),
    ("dense+rerank", "dense", "cross-encoder"),
    ("hybrid+rerank", "hybrid", "cross-encoder"),
)
# Published BM25 on SciFact (BEIR paper, Elasticsearch BM25), for sanity-checking
# app/rag/bm25.py against an independent implementation.
PUBLISHED_BM25_NDCG10 = 0.665


def load_scifact() -> tuple[dict, dict, dict]:
    """(corpus, queries, qrels) for the SciFact test split, downloaded once."""
    root = os.path.join(CACHE_DIR, "scifact")
    if not os.path.exists(os.path.join(root, "corpus.jsonl")):
        os.makedirs(CACHE_DIR, exist_ok=True)
        print(f"downloading {DATASET_URL}", file=sys.stderr)
        with urllib.request.urlopen(DATASET_URL, timeout=120) as resp:
            zipfile.ZipFile(io.BytesIO(resp.read())).extractall(CACHE_DIR)

    corpus = {}
    with open(os.path.join(root, "corpus.jsonl"), encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            corpus[doc["_id"]] = f"{doc.get('title', '')}\n{doc['text']}".strip()
    queries = {}
    with open(os.path.join(root, "queries.jsonl"), encoding="utf-8") as f:
        for line in f:
            q = json.loads(line)
            queries[q["_id"]] = q["text"]
    qrels: dict[str, dict[str, int]] = {}
    with open(os.path.join(root, "qrels", "test.tsv"), encoding="utf-8") as f:
        next(f)
        for line in f:
            qid, did, score = line.rstrip("\n").split("\t")
            if int(score) > 0:
                qrels.setdefault(qid, {})[did] = int(score)
    queries = {qid: queries[qid] for qid in qrels}
    return corpus, queries, qrels


def ndcg_at_k(ranked: list[str], rels: dict[str, int], k: int = 10) -> float:
    dcg = sum((2 ** rels.get(d, 0) - 1) / math.log2(i + 2) for i, d in enumerate(ranked[:k]))
    ideal = sorted(rels.values(), reverse=True)[:k]
    idcg = sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def recall_at_k(ranked: list[str], rels: dict[str, int], k: int = 10) -> float:
    return len(set(ranked[:k]) & set(rels)) / len(rels) if rels else 0.0


class LocalEmbedder:
    """Stands in for app.rag.ingest.embed_texts, with the same signature."""

    def __init__(self, model_name: str = EMBED_MODEL):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model_name, threads=4)

    def __call__(self, texts, client=None, task_type="RETRIEVAL_DOCUMENT"):
        if task_type == "RETRIEVAL_QUERY":
            vectors = self.model.query_embed(list(texts))
        else:
            vectors = self.model.passage_embed(list(texts), batch_size=8)
        return [v.tolist() for v in vectors]


def run(limit: int | None = None, rerank: bool = True) -> dict:
    from app.config import get_settings
    from app.rag import retriever
    from app.rag.ingest import get_chroma_collection
    from app.rag.rerank import warm_up

    corpus, queries, qrels = load_scifact()
    if limit:
        queries = dict(list(queries.items())[:limit])
    settings = get_settings()
    configs = [c for c in CONFIGS if rerank or c[2] == "none"]
    embed = LocalEmbedder()
    if rerank:
        warm_up(settings.rerank_model)

    summary, per_query = {}, {}
    with ExitStack() as stack, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "AGENTDESK_CHROMA_DIR": os.path.join(tmp, "chroma"),
                    "AGENTDESK_COLLECTION": "beir-scifact",
                },
            )
        )
        stack.enter_context(patch("app.rag.retriever.embed_texts", embed))

        started = time.perf_counter()
        ids, docs = list(corpus), list(corpus.values())
        collection = get_chroma_collection()
        for start in range(0, len(ids), 256):
            batch_ids, batch_docs = ids[start : start + 256], docs[start : start + 256]
            collection.upsert(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=[{"source_file": d, "chunk_index": 0} for d in batch_ids],
                embeddings=embed(batch_docs),
            )
        index_s = round(time.perf_counter() - started, 1)
        print(f"indexed {len(ids)} documents in {index_s}s", file=sys.stderr)

        for name, mode, reranker in configs:
            ndcgs, recalls, latencies, rows = [], [], [], {}
            for qid, text in queries.items():
                t0 = time.perf_counter()
                ranked = retriever.retrieve(
                    text,
                    k=CANDIDATES,
                    mode=mode,
                    reranker=reranker,
                    max_distance=math.inf,
                    candidate_k=CANDIDATES,
                    rrf_k=settings.rrf_k,
                )
                latencies.append((time.perf_counter() - t0) * 1000)
                doc_ids = [n["doc_id"] for n in ranked]
                ndcgs.append(ndcg_at_k(doc_ids, qrels[qid]))
                recalls.append(recall_at_k(doc_ids, qrels[qid]))
                rows[qid] = round(ndcgs[-1], 4)
            summary[name] = {
                "ndcg@10": round(statistics.mean(ndcgs), 4),
                "recall@10": round(statistics.mean(recalls), 4),
                "latency_ms_p50": round(statistics.median(latencies), 1),
            }
            per_query[name] = rows
            print(f"{name}: {summary[name]}", file=sys.stderr)

    return {
        "meta": {
            "dataset": "BEIR SciFact (test)",
            "documents": len(corpus),
            "queries": len(queries),
            "embed_model": EMBED_MODEL,
            "rerank_model": settings.rerank_model if rerank else None,
            "candidates": CANDIDATES,
            "published_bm25_ndcg@10": PUBLISHED_BM25_NDCG10,
        },
        "summary": summary,
        "per_query_ndcg@10": per_query,
    }


def render_table(result: dict) -> str:
    meta, summary = result["meta"], result["summary"]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    best = max(s["ndcg@10"] for s in summary.values())
    lines = [
        f"_{meta['dataset']}: {meta['documents']:,} documents, {meta['queries']} queries with "
        f"expert relevance labels. Embeddings `{meta['embed_model']}` (local); reranker "
        f"`{meta['rerank_model']}` over the top {meta['candidates']}. Recorded {stamp}._",
        "",
        "| Retriever | nDCG@10 | Recall@10 | p50 latency |",
        "| --- | --- | --- | --- |",
    ]
    for name, s in summary.items():
        ndcg = f"{s['ndcg@10']:.3f}"
        if s["ndcg@10"] == best:
            ndcg = f"**{ndcg}**"
        lines.append(f"| `{name}` | {ndcg} | {s['recall@10']:.3f} | {s['latency_ms_p50']:.0f} ms |")
    lines.append(f"| _published BM25 (BEIR paper)_ | _{meta['published_bm25_ndcg@10']:.3f}_ | | |")
    return "\n".join(lines)


def update_readme(result: dict) -> bool:
    start, end = "<!-- eval:beir:start -->", "<!-- eval:beir:end -->"
    try:
        with open(README_PATH, encoding="utf-8") as f:
            readme = f.read()
    except OSError:
        return False
    if start not in readme or end not in readme:
        return False
    head, _, rest = readme.partition(start)
    _, _, tail = rest.partition(end)
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(f"{head}{start}\n{render_table(result)}\n{end}{tail}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--limit", type=int, help="only the first N queries (smoke test)")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--write", action="store_true", help="save results and update README")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    result = run(limit=args.limit, rerank=not args.no_rerank)
    print(render_table(result))
    if args.write:
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
            f.write("\n")
        print(f"wrote {os.path.relpath(RESULTS_PATH, REPO_ROOT)}", file=sys.stderr)
        if update_readme(result):
            print("updated the BEIR table in README.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
