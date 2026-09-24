"""Retrieval benchmark: how well does each retriever configuration find the evidence?

The end-to-end eval (eval/run_eval.py) checks the pipeline; this one isolates
the retrieval step, where most RAG answers are won or lost. Every configuration
runs over the same labelled question set (eval/retrieval_set.json) and the same
corpus (data/sample_docs):

  dense           Gemini embeddings + Chroma, what AgentDesk shipped with
  bm25            lexical Okapi BM25 only
  hybrid          dense + BM25 fused with reciprocal rank fusion
  dense+rerank    dense candidates reordered by a local cross-encoder
  hybrid+rerank   hybrid candidates reordered by a local cross-encoder

Embeddings come from one of three sources (--embeddings):

  cache  (default)  eval/embedding_cache.npz, checked in. Real Gemini vectors,
                    so CI reproduces the live numbers exactly, with no API key.
  live              call Gemini for anything missing from the cache; with
                    --write, save the cache so `cache` mode can replay it.
  fake              the deterministic stand-in from tests/doubles.py. Only
                    useful for testing this harness, not for measuring.
"""

import argparse
import hashlib
import json
import logging
import math
import os
import re
import statistics
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import numpy as np  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.rag.ingest import embed_texts as gemini_embed_texts  # noqa: E402  (unpatched)

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(EVAL_DIR)
README_PATH = os.path.join(REPO_ROOT, "README.md")
SET_PATH = os.path.join(EVAL_DIR, "retrieval_set.json")
CACHE_PATH = os.path.join(EVAL_DIR, "embedding_cache.npz")
RESULTS_PATH = os.path.join(EVAL_DIR, "results_retrieval.json")
DOCS_DIR = os.path.join(REPO_ROOT, "data", "sample_docs")

# (name, mode, reranker)
CONFIGS = (
    ("dense", "dense", "none"),
    ("bm25", "bm25", "none"),
    ("hybrid", "hybrid", "none"),
    ("dense+rerank", "dense", "cross-encoder"),
    ("hybrid+rerank", "hybrid", "cross-encoder"),
)
QUERY_TYPES = ("keyword", "paraphrase", "multi")
NEGATIVE_TYPES = ("off-topic", "near-domain")
DEFAULT_CONFIG = "dense"  # what AGENTDESK_RETRIEVAL_MODE / AGENTDESK_RERANKER default to
PREVIOUS_FLOOR = 0.65  # the floor tuned for OpenAI embeddings, before the port to Gemini
FLOOR_SWEEP = tuple(round(0.30 + 0.025 * i, 3) for i in range(15))  # 0.30 .. 0.65
K = 4  # what the Researcher asks for (AGENTDESK_RETRIEVAL_K)
DEEP_K = 10  # depth for MRR / nDCG

# Guards for CI, on the default retriever and the reranker's one real gain. The
# floor metrics are measured at AGENTDESK_MAX_DISTANCE, so a floor change that
# starts dropping real answers or admitting off-topic questions fails the build.
THRESHOLDS = {
    ("dense", "recall@4"): 0.95,
    ("dense", "mrr@10"): 0.85,
    ("dense", "answerable"): 0.95,
    ("dense", "rejected[off-topic]"): 1.0,
    ("dense", "rejected[near-domain]"): 0.5,
    ("dense+rerank", "hit@1"): 0.80,
}


# --------------------------------------------------------------------------- embeddings


class EmbeddingCache:
    """Real embeddings keyed by (model, task_type, text), stored as float16.

    Values are always round-tripped through float16, so a fresh live run and a
    replay from the cache rank identically.
    """

    def __init__(self, path: str, allow_live: bool):
        self.path = path
        self.allow_live = allow_live
        self.vectors: dict[str, np.ndarray] = {}
        self.misses = 0
        if os.path.exists(path):
            data = np.load(path)
            self.vectors = dict(zip(data["keys"].tolist(), data["vecs"], strict=True))

    @staticmethod
    def key(model: str, task_type: str, text: str) -> str:
        text = text.replace("\r\n", "\n")  # a CRLF checkout must hit the same entries
        return hashlib.sha256(f"{model}|{task_type}|{text}".encode()).hexdigest()[:24]

    def embed(self, texts, client=None, task_type="RETRIEVAL_DOCUMENT"):
        model = get_settings().embed_model
        keys = [self.key(model, task_type, t) for t in texts]
        todo = [(k, t) for k, t in zip(keys, texts, strict=True) if k not in self.vectors]
        if todo:
            if not self.allow_live:
                raise SystemExit(
                    f"{len(todo)} text(s) are not in {os.path.relpath(self.path, REPO_ROOT)} - "
                    "the corpus or question set changed. Refresh with:\n"
                    "  python -m eval.run_retrieval_eval --embeddings live --write"
                )
            self.misses += len(todo)
            fresh = gemini_embed_texts([t for _, t in todo], task_type=task_type)
            for (k, _), vec in zip(todo, fresh, strict=True):
                self.vectors[k] = np.asarray(vec, dtype=np.float16)
        return [self.vectors[k].astype(np.float32).tolist() for k in keys]

    def save(self, keep_keys: set[str]) -> None:
        keys = sorted(k for k in self.vectors if k in keep_keys)
        np.savez_compressed(
            self.path,
            keys=np.array(keys),
            vecs=np.stack([self.vectors[k] for k in keys]).astype(np.float16),
        )


class RecordingEmbedder:
    """Wraps an embed function and remembers which cache keys were used."""

    def __init__(self, embed):
        self.inner = embed
        self.used: set[str] = set()

    def __call__(self, texts, client=None, task_type="RETRIEVAL_DOCUMENT"):
        model = get_settings().embed_model
        self.used.update(EmbeddingCache.key(model, task_type, t) for t in texts)
        return self.inner(texts, client=client, task_type=task_type)


# --------------------------------------------------------------------------- scoring


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _alternatives(gold_item: dict) -> list[dict]:
    return gold_item.get("any_of", [gold_item])


def satisfies(note: dict, gold_item: dict) -> bool:
    content = _norm(note["content"])
    return any(
        note["file"] == alt["file"] and _norm(alt["evidence"]) in content
        for alt in _alternatives(gold_item)
    )


def score_query(ranked: list[dict], gold: list[dict], k: int = K, deep_k: int = DEEP_K) -> dict:
    """Metrics for one query's ranked notes against its gold items.

    A chunk earns relevance gain the first time it satisfies a not-yet-covered
    gold item, so two chunks carrying the same fact do not double-count.
    """
    covered: set[int] = set()
    gains = []
    for note in ranked[:deep_k]:
        gain = 0
        for i, item in enumerate(gold):
            if i not in covered and satisfies(note, item):
                covered.add(i)
                gain = 1
                break
        gains.append(gain)

    found_at_k = {i for i, item in enumerate(gold) if any(satisfies(n, item) for n in ranked[:k])}
    first_hit = next((rank for rank, g in enumerate(gains, start=1) if g), None)
    dcg = sum(g / math.log2(rank + 1) for rank, g in enumerate(gains, start=1))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(gold), deep_k) + 1))

    return {
        "recall@4": len(found_at_k) / len(gold),
        "hit@1": 1.0 if gains and gains[0] else 0.0,
        "mrr@10": 1.0 / first_hit if first_hit else 0.0,
        "ndcg@10": dcg / ideal if ideal else 0.0,
    }


def floor_effect(positive_runs, negative_runs, max_distance: float) -> dict:
    """What a given floor does: answerable questions kept vs unanswerable ones refused.

    `answerable` - share of labelled questions whose floor-filtered top-4 still
    holds at least one gold item. `rejected[type]` - share of unanswerable
    questions for which the floor returns nothing at all.
    """
    answerable = [
        score_query(apply_floor(ranked, max_distance), gold)["recall@4"] > 0
        for ranked, gold in positive_runs
    ]
    effect = {"answerable": round(sum(answerable) / len(answerable), 4) if answerable else 0.0}
    for neg_type in NEGATIVE_TYPES:
        runs = [ranked for t, ranked in negative_runs if t == neg_type]
        if runs:
            refused = sum(not apply_floor(ranked, max_distance) for ranked in runs)
            effect[f"rejected[{neg_type}]"] = round(refused / len(runs), 4)
    return effect


def apply_floor(ranked: list[dict], max_distance: float, k: int = K) -> list[dict]:
    """What rag_search would return: floor-filtered, then truncated to k."""
    return [n for n in ranked if (1.0 - n["score"]) <= max_distance + 1e-9][:k]


# --------------------------------------------------------------------------- runner


def run(embeddings: str = "cache", rerank: bool = True, set_path: str = SET_PATH):
    from app.rag import retriever
    from app.rag.ingest import ingest_docs
    from app.rag.rerank import warm_up

    with open(set_path, encoding="utf-8") as f:
        bench = json.load(f)
    queries, negatives = bench["queries"], bench["negatives"]
    settings = get_settings()
    configs = [c for c in CONFIGS if rerank or c[2] == "none"]

    if embeddings == "fake":
        from tests.doubles import fake_embed_texts

        cache, embed = None, RecordingEmbedder(fake_embed_texts)
    else:
        cache = EmbeddingCache(CACHE_PATH, allow_live=embeddings == "live")
        embed = RecordingEmbedder(cache.embed)

    if rerank:
        warm_up(settings.rerank_model)  # keep model download/load out of the latency figures

    per_config: dict[str, dict] = {}
    sweeps: dict[str, list] = {}
    distances: dict[str, list] = {"gold": [], **{t: [] for t in NEGATIVE_TYPES}}
    rows: dict[str, list] = {}

    def ranked_for(question, mode, reranker):
        return retriever.retrieve(
            question,
            k=settings.candidate_k,
            mode=mode,
            reranker=reranker,
            max_distance=math.inf,  # the floor is applied below, so it can be swept
            candidate_k=settings.candidate_k,
            rrf_k=settings.rrf_k,
        )

    with ExitStack() as stack, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "AGENTDESK_CHROMA_DIR": os.path.join(tmp, "chroma"),
                    "AGENTDESK_COLLECTION": "retrieval-eval",
                },
            )
        )
        stack.enter_context(patch("app.rag.ingest.embed_texts", embed))
        stack.enter_context(patch("app.rag.retriever.embed_texts", embed))
        chunks = ingest_docs(docs_dir=DOCS_DIR)

        for name, mode, reranker in configs:
            metrics, latencies, config_rows, positive_runs = [], [], [], []
            for q in queries:
                started = time.perf_counter()
                ranked = ranked_for(q["question"], mode, reranker)
                latencies.append((time.perf_counter() - started) * 1000)
                m = score_query(ranked, q["gold"])
                metrics.append((q["type"], m))
                positive_runs.append((ranked, q["gold"]))
                config_rows.append(
                    {
                        "id": q["id"],
                        "top4": [n["doc_id"] for n in ranked[:K]],
                        **{key: round(v, 4) for key, v in m.items()},
                    }
                )
                if name == "dense":
                    distances["gold"].extend(
                        1.0 - n["score"] for n in ranked if any(satisfies(n, g) for g in q["gold"])
                    )

            negative_runs = []
            for neg in negatives:
                ranked = ranked_for(neg["question"], mode, reranker)
                negative_runs.append((neg["type"], ranked))
                if name == "dense" and ranked:
                    distances[neg["type"]].append(1.0 - ranked[0]["score"])

            summary = {}
            for metric in ("recall@4", "hit@1", "mrr@10", "ndcg@10"):
                summary[metric] = round(statistics.mean(m[metric] for _, m in metrics), 4)
            for qtype in QUERY_TYPES:
                vals = [m["recall@4"] for t, m in metrics if t == qtype]
                if vals:
                    summary[f"recall@4[{qtype}]"] = round(statistics.mean(vals), 4)
            summary.update(floor_effect(positive_runs, negative_runs, settings.max_distance))
            summary["latency_ms_p50"] = round(statistics.median(latencies), 1)
            per_config[name] = summary
            sweeps[name] = [
                {"max_distance": f, **floor_effect(positive_runs, negative_runs, f)}
                for f in FLOOR_SWEEP
            ]
            rows[name] = config_rows

    floor = {
        "max_distance": settings.max_distance,
        "gold_distance_max": round(max(distances["gold"]), 4) if distances["gold"] else None,
        **{
            f"{t}_top1_distance_min": round(min(distances[t]), 4) if distances[t] else None
            for t in NEGATIVE_TYPES
        },
        "sweep": sweeps,
    }
    meta = {
        "queries": len(queries),
        "by_type": {t: sum(q["type"] == t for q in queries) for t in QUERY_TYPES},
        "negatives": {t: sum(n["type"] == t for n in negatives) for t in NEGATIVE_TYPES},
        "chunks": chunks,
        "embed_model": settings.embed_model,
        "rerank_model": settings.rerank_model if rerank else None,
        "embeddings": embeddings,
    }
    return {"meta": meta, "summary": per_config, "floor": floor, "rows": rows}, cache, embed


# --------------------------------------------------------------------------- reporting


def render_table(result: dict) -> str:
    """The markdown block the README embeds: ranking quality, then the floor's effect."""
    meta, summary, floor = result["meta"], result["summary"], result["floor"]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    by_type = ", ".join(f"{n} {t}" for t, n in meta["by_type"].items())
    negs = " + ".join(f"{n} {t}" for t, n in meta["negatives"].items())
    lines = [
        f"_{meta['queries']} labelled questions ({by_type}) and {negs} unanswerable ones, "
        f"over {meta['chunks']} chunks. Embeddings `{meta['embed_model']}`; reranker "
        f"`{meta['rerank_model']}`. Recorded {stamp}._",
        "",
        "| Retriever | Recall@4 | Hit@1 | MRR@10 | nDCG@10 | Recall@4 keyword | "
        "Recall@4 paraphrase | Recall@4 multi-doc | p50 latency |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    best = {
        metric: max(s[metric] for s in summary.values())
        for metric in ("recall@4", "hit@1", "mrr@10", "ndcg@10")
    }
    for name, s in summary.items():

        def cell(metric, s=s):
            value = f"{s[metric]:.2f}"
            return f"**{value}**" if metric in best and s[metric] == best[metric] else value

        marker = " (default)" if name == DEFAULT_CONFIG else ""
        lines.append(
            f"| `{name}`{marker} | {cell('recall@4')} | {cell('hit@1')} | {cell('mrr@10')} | "
            f"{cell('ndcg@10')} | {s.get('recall@4[keyword]', 0):.2f} | "
            f"{s.get('recall@4[paraphrase]', 0):.2f} | {s.get('recall@4[multi]', 0):.2f} | "
            f"{s['latency_ms_p50']:.0f} ms |"
        )

    sweep = {row["max_distance"]: row for row in floor["sweep"].get(DEFAULT_CONFIG, [])}
    shown = [f for f in (PREVIOUS_FLOOR, floor["max_distance"]) if f in sweep]
    if shown:
        lines += [
            "",
            f"Relevance floor, `{DEFAULT_CONFIG}` retriever (closest correct chunk: distance "
            f"{floor['gold_distance_max']:.3f} at worst; closest chunk to an unanswerable "
            f"question: {floor['near-domain_top1_distance_min']:.3f} near-domain, "
            f"{floor['off-topic_top1_distance_min']:.3f} off-topic):",
            "",
            "| `AGENTDESK_MAX_DISTANCE` | Answerable questions kept | Off-topic refused | "
            "Near-domain refused |",
            "| --- | --- | --- | --- |",
        ]
        for f in dict.fromkeys(shown):
            row = sweep[f]
            label = "previous" if f == PREVIOUS_FLOOR else "current"
            lines.append(
                f"| {f:.3f} ({label}) | {row['answerable']:.0%} | "
                f"{row['rejected[off-topic]']:.0%} | {row['rejected[near-domain]']:.0%} |"
            )
    return "\n".join(lines)


def update_readme(result: dict) -> bool:
    start, end = "<!-- eval:retrieval:start -->", "<!-- eval:retrieval:end -->"
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


def check(summary: dict) -> list[str]:
    failures = [
        f"{name} {metric}: {summary[name][metric]:.3f} < {floor}"
        for (name, metric), floor in THRESHOLDS.items()
        if name in summary and summary[name][metric] < floor
    ]
    if "dense+rerank" in summary and summary["dense+rerank"]["hit@1"] <= summary["dense"]["hit@1"]:
        failures.append("the reranker no longer improves hit@1 over dense retrieval")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--embeddings", choices=("cache", "live", "fake"), default="cache")
    parser.add_argument("--no-rerank", action="store_true", help="skip the cross-encoder configs")
    parser.add_argument(
        "--write",
        action="store_true",
        help="save results (and, with --embeddings live, the embedding cache); update README",
    )
    parser.add_argument("--check", action="store_true", help="exit non-zero below the thresholds")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.embeddings == "live" and not os.environ.get("GEMINI_API_KEY"):
        parser.error("--embeddings live needs GEMINI_API_KEY")

    result, cache, embed = run(embeddings=args.embeddings, rerank=not args.no_rerank)
    print(render_table(result))
    calibration = {k: v for k, v in result["floor"].items() if k != "sweep"}
    print(f"\nfloor calibration: {json.dumps(calibration)}")

    if args.write:
        if cache is not None and args.embeddings == "live":
            cache.save(embed.used)
            print(
                f"wrote {os.path.relpath(CACHE_PATH, REPO_ROOT)} ({len(embed.used)} vectors, "
                f"{cache.misses} fetched from Gemini)",
                file=sys.stderr,
            )
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
            f.write("\n")
        print(f"wrote {os.path.relpath(RESULTS_PATH, REPO_ROOT)}", file=sys.stderr)
        if args.embeddings != "fake" and update_readme(result):
            print("updated the retrieval table in README.md", file=sys.stderr)

    if args.check:
        if args.embeddings == "fake":
            parser.error("--check measures real retrieval; use --embeddings cache or live")
        failures = check(result["summary"])
        if failures:
            print("\nRETRIEVAL REGRESSION:\n  " + "\n  ".join(failures), file=sys.stderr)
            return 1
        print("\nall retrieval thresholds met", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
