"""The answer-quality eval's deterministic parts: subset, references, scoring."""

import pytest

from eval import run_answer_eval as answers


def test_subset_is_stratified_and_stable():
    queries, negatives = answers.load_subset()

    by_type = {t: [q for q in queries if q["type"] == t] for t in answers.PER_TYPE}
    assert {t: len(qs) for t, qs in by_type.items()} == answers.PER_TYPE
    assert len(negatives) == 2 * answers.NEGATIVES_PER_TYPE
    assert answers.load_subset() == (queries, negatives), "same questions every run"


def test_gold_passages_are_the_chunks_holding_the_evidence():
    gold = [{"file": "error_codes.md", "evidence": "AUTH-1003"}]

    [passage] = answers.gold_passages(gold)

    assert passage.startswith("(error_codes.md)")
    assert "AUTH-1003" in passage


def test_gold_passages_use_the_first_resolvable_alternative():
    gold = [
        {
            "any_of": [
                {"file": "oncall_runbook.md", "evidence": "Monday 09:00 UTC"},
                {"file": "engineering_handbook.md", "evidence": "every Monday at 9:00 AM"},
            ]
        }
    ]

    assert len(answers.gold_passages(gold)) == 1


def test_cited_ids_are_unique_and_ordered():
    report = "A [rag:a.md#0]. B [web:1] and again [rag:a.md#0]. Not a cite [x]."

    assert answers.cited_ids(report) == ["rag:a.md#0", "web:1"]


NOTES = [
    {"source_id": "rag:error_codes.md#0", "content": "`AUTH-1003` - the token was revoked"},
    {"source_id": "web:1", "content": "AUTH-1003 means revoked, says a blog"},
]
GOLD = [{"file": "error_codes.md", "evidence": "AUTH-1003"}]


def test_gold_cited_needs_an_internal_citation_holding_the_evidence():
    assert answers.gold_cited("Revoked [rag:error_codes.md#0].", NOTES, GOLD)
    assert not answers.gold_cited("Revoked [web:1].", NOTES, GOLD), "web is not gold"
    assert not answers.gold_cited("Revoked.", NOTES, GOLD), "uncited is not gold"


def row(qtype, grade, claims, gold_cited=True, sanity="incorrect"):
    return {
        "type": qtype,
        "grade": grade,
        "claims": [{"claim": "c", "supported": s} for s in claims],
        "gold_cited": gold_cited,
        "sanity_grade": sanity,
        "latency_s": 10.0,
    }


def test_summary_scores_partial_as_half_and_pools_claims():
    rows = [
        row("keyword", "correct", [True, True]),
        row("paraphrase", "partial", [True, False], gold_cited=False),
        row("multi", "incorrect", [False], sanity="correct"),
    ]
    negatives = [{"no_fabrication": True, "latency_s": 5.0}, {"error": "boom"}]

    s = answers.summarise(rows, negatives)

    assert s["correctness"] == pytest.approx(0.5)
    assert s["fully_correct_rate"] == pytest.approx(1 / 3, abs=1e-3)
    assert s["correctness_by_type"] == {"keyword": 1.0, "paraphrase": 0.5, "multi": 0.0}
    assert s["faithfulness"] == pytest.approx(3 / 5)
    assert s["gold_cited_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["no_fabrication_rate"] == 1.0
    assert s["judge_sanity"] == pytest.approx(2 / 3, abs=1e-3)
    assert s["errors"] == 1


def test_errored_rows_are_counted_not_scored():
    s = answers.summarise(
        [row("keyword", "correct", [True]), {"type": "keyword", "error": "x"}], []
    )

    assert s["errors"] == 1
    assert s["correctness"] == 1.0


def test_with_retries_recovers_then_gives_up(monkeypatch):
    monkeypatch.setattr(answers.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("503")
        return "ok"

    assert answers.with_retries(flaky, attempts=4) == "ok"
    with pytest.raises(RuntimeError):
        answers.with_retries(lambda: (_ for _ in ()).throw(RuntimeError("down")), attempts=2)


def test_render_table_shows_every_headline_metric():
    result = {
        "meta": {"model": "m", "judge_model": "j"},
        "summary": answers.summarise([row("keyword", "correct", [True])], []),
    }

    table = answers.render_table(result)

    for label in ("Correctness", "Faithfulness", "Judge sanity", "No fabricated"):
        assert label in table


def test_completeness_judge_is_skipped_without_criteria():
    from unittest.mock import patch

    with patch("app.llm.gemini_client.structured_call") as judge:
        assert answers.judge_completeness([], "report", "m") == []

    judge.assert_not_called()


def test_summary_reports_criteria_coverage_only_when_it_was_measured():
    covered = {
        **row("keyword", "correct", [True]),
        "criteria": [
            {"criterion": "a", "met": True},
            {"criterion": "b", "met": False},
            {"criterion": "c", "met": True},
            {"criterion": "d", "met": True},
        ],
    }

    with_criteria = answers.summarise([covered], [])
    without = answers.summarise([row("keyword", "correct", [True])], [])

    assert with_criteria["criteria_coverage"] == pytest.approx(0.75)
    assert with_criteria["criteria_checked"] == 4
    assert without["criteria_coverage"] is None


def test_render_table_adds_a_coverage_row_only_when_measured():
    measured = {**row("keyword", "correct", [True]), "criteria": [{"criterion": "a", "met": True}]}
    result = {"meta": {"model": "m", "judge_model": "j"}}

    shown = answers.render_table({**result, "summary": answers.summarise([measured], [])})
    hidden = answers.render_table(
        {**result, "summary": answers.summarise([row("keyword", "correct", [True])], [])}
    )

    assert "Criteria coverage | 100%" in shown
    assert "Criteria coverage" not in hidden
