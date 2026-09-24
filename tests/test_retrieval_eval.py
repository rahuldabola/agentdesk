"""The retrieval benchmark's scoring, and its labelled set's integrity."""

import json
import re

import pytest

from app.rag.ingest import chunk_text
from eval import run_retrieval_eval as bench


def note(file, content):
    return {"file": file, "content": content, "doc_id": f"{file}#0", "score": 0.9}


def test_recall_counts_gold_items_found_in_the_top_k():
    gold = [{"file": "a.md", "evidence": "alpha"}, {"file": "b.md", "evidence": "beta"}]
    ranked = (
        [note("a.md", "alpha here"), note("x.md", "noise")]
        + [note("x.md", "n")] * 3
        + [note("b.md", "beta")]
    )

    m = bench.score_query(ranked, gold)

    assert m["recall@4"] == 0.5
    assert m["hit@1"] == 1.0
    assert m["mrr@10"] == 1.0
    assert 0.0 < m["ndcg@10"] < 1.0


def test_evidence_in_the_wrong_file_does_not_count():
    gold = [{"file": "a.md", "evidence": "alpha"}]

    assert bench.score_query([note("b.md", "alpha")], gold)["recall@4"] == 0.0


def test_any_of_accepts_an_equivalent_source():
    gold = [{"any_of": [{"file": "a.md", "evidence": "x"}, {"file": "b.md", "evidence": "y"}]}]

    assert bench.score_query([note("b.md", "y")], gold)["recall@4"] == 1.0


def test_duplicate_evidence_is_not_double_counted():
    gold = [{"file": "a.md", "evidence": "alpha"}]
    ranked = [note("a.md", "alpha"), note("a.md", "alpha again")]

    assert bench.score_query(ranked, gold)["ndcg@10"] == pytest.approx(1.0)


def test_evidence_matching_ignores_line_wrapping():
    gold = [{"file": "a.md", "evidence": "expire after 24 hours"}]

    assert bench.score_query([note("a.md", "Tokens\nexpire after\n24 hours")], gold)["hit@1"]


def test_floor_filters_then_truncates():
    ranked = [dict(note("a.md", str(i)), score=s) for i, s in enumerate([0.9, 0.2, 0.8, 0.7, 0.6])]

    kept = bench.apply_floor(ranked, max_distance=0.35, k=2)

    assert [n["score"] for n in kept] == [0.9, 0.8]


def test_every_gold_evidence_string_exists_in_some_chunk():
    """A typo in the labelled set would silently cap recall below 1.0."""
    with open(bench.SET_PATH, encoding="utf-8") as f:
        bench_set = json.load(f)
    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731

    chunks = {}
    for query in bench_set["queries"]:
        for item in query["gold"]:
            for alt in item.get("any_of", [item]):
                if alt["file"] not in chunks:
                    path = f"{bench.DOCS_DIR}/{alt['file']}"
                    with open(path, encoding="utf-8") as f:
                        chunks[alt["file"]] = [norm(c) for c in chunk_text(f.read())]
                assert any(norm(alt["evidence"]) in c for c in chunks[alt["file"]]), (
                    query["id"],
                    alt,
                )


def test_harness_runs_end_to_end_with_fake_embeddings():
    result, _, _ = bench.run(embeddings="fake", rerank=False)

    assert set(result["summary"]) == {"dense", "bm25", "hybrid"}
    for summary in result["summary"].values():
        assert 0.0 <= summary["recall@4"] <= 1.0
    # Lexical retrieval does not depend on the embeddings, so it is a real number here.
    assert result["summary"]["bm25"]["recall@4[keyword]"] >= 0.9
    assert "rerank" not in bench.render_table(result).split("|")[1]


def test_check_flags_a_regression():
    healthy = {
        "recall@4": 0.97,
        "mrr@10": 0.9,
        "hit@1": 0.75,
        "answerable": 0.98,
        "rejected[off-topic]": 1.0,
        "rejected[near-domain]": 0.5,
    }
    summary = {
        "dense": dict(healthy, **{"rejected[off-topic]": 0.0}),
        "dense+rerank": dict(healthy, **{"hit@1": 0.7}),
    }

    failures = bench.check(summary)

    assert any("rejected[off-topic]" in f for f in failures)
    assert any("no longer improves hit@1" in f for f in failures)
    assert bench.check({"dense": healthy, "dense+rerank": dict(healthy, **{"hit@1": 0.81})}) == []
