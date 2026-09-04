"""The eval harness computes the numbers the README publishes, and edits the
README in place. Both deserve tests: a metric that silently miscounts, or a
marker replacement that eats surrounding prose, would be invisible otherwise.
"""

import json

import pytest

from eval import run_eval as harness

SUMMARY = {
    "cases": 2,
    "task_completion_rate": 1.0,
    "termination_rate": 1.0,
    "citation_coverage": 0.5,
    "citation_validity": 0.75,
    "error_rate": 0.0,
    "tool_routing_accuracy": 0.5,
    "critic_revision_rate": 0.5,
    "research_loop_rate": 0.0,
    "unverified_report_rate": 0.0,
    "mean_latency_s": 1.25,
}


def _row(**overrides):
    row = {
        "completed": True,
        "status": "passed",
        "routing_correct": True,
        "revisions": 0,
        "research_rounds": 0,
        "citation_markers": 2,
        "citations_resolved": 2,
        "latency_s": 1.0,
    }
    row.update(overrides)
    return row


# --- metrics ------------------------------------------------------------------


def test_a_clean_run_scores_one_across_the_pipeline_metrics():
    summary = harness.summarise([_row(), _row()])

    assert summary["task_completion_rate"] == 1.0
    assert summary["citation_validity"] == 1.0
    assert summary["error_rate"] == 0.0


def test_citation_validity_is_the_ratio_of_markers_that_resolve():
    """Four markers, three of which resolve to a registered source."""
    summary = harness.summarise(
        [
            _row(citation_markers=2, citations_resolved=2),
            _row(citation_markers=2, citations_resolved=1),
        ]
    )

    assert summary["citation_validity"] == 0.75


def test_a_report_with_no_citations_does_not_count_as_valid():
    summary = harness.summarise([_row(citation_markers=0, citations_resolved=0)])

    assert summary["citation_coverage"] == 0.0
    assert summary["citation_validity"] == 0.0, "no markers must not read as perfect validity"


def test_a_crashed_case_counts_against_termination_not_just_completion():
    summary = harness.summarise([_row(), {"question": "q", "error": "boom", "latency_s": 0.1}])

    assert summary["error_rate"] == 0.5
    assert summary["termination_rate"] == 0.5
    assert summary["task_completion_rate"] == 0.5


def test_an_unverified_report_is_counted_separately():
    summary = harness.summarise([_row(status="revision_limit_reached", revisions=2), _row()])

    assert summary["unverified_report_rate"] == 0.5
    assert summary["critic_revision_rate"] == 0.5


def test_summarise_handles_an_empty_run_without_dividing_by_zero():
    summary = harness.summarise([])

    assert summary["cases"] == 0
    assert summary["mean_latency_s"] == 0.0


# --- thresholds ---------------------------------------------------------------


def test_every_threshold_names_a_metric_summarise_actually_produces():
    summary = harness.summarise([_row()])

    assert set(harness.OFFLINE_THRESHOLDS) <= set(summary)


def test_the_labelled_metric_groups_cover_what_the_table_renders():
    summary = harness.summarise([_row()])

    assert set(harness.PIPELINE_METRICS) <= set(summary)
    assert set(harness.JUDGEMENT_METRICS) <= set(summary)


# --- rendering ----------------------------------------------------------------


def test_the_table_labels_judgement_metrics_by_who_produced_them():
    offline = harness.render_table("offline", SUMMARY)
    live = harness.render_table("live", SUMMARY)

    assert "| `tool_routing_accuracy` | 0.50 | the stub |" in offline
    assert "| `tool_routing_accuracy` | 0.50 | the model |" in live
    # Pipeline metrics are labelled the same either way.
    assert "| `citation_validity` | 0.75 | the pipeline |" in offline
    assert "| `citation_validity` | 0.75 | the pipeline |" in live


def test_the_table_records_the_case_count():
    assert "2 cases" in harness.render_table("offline", SUMMARY)


# --- README surgery -----------------------------------------------------------


@pytest.fixture
def readme(tmp_path, monkeypatch):
    path = tmp_path / "README.md"
    path.write_text(
        "# Title\n\nBefore.\n\n"
        "<!-- eval:offline:start -->\nstale table\n<!-- eval:offline:end -->\n\n"
        "After.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(harness, "README_PATH", str(path))
    return path


def test_updating_the_readme_replaces_only_the_marked_block(readme):
    assert harness.update_readme("offline", SUMMARY) is True

    text = readme.read_text(encoding="utf-8")
    assert "stale table" not in text
    assert "| `citation_validity` | 0.75 | the pipeline |" in text
    # Everything outside the markers is untouched.
    assert text.startswith("# Title\n\nBefore.\n\n")
    assert text.endswith("\n\nAfter.\n")


def test_updating_twice_is_idempotent_in_shape(readme):
    harness.update_readme("offline", SUMMARY)
    first = readme.read_text(encoding="utf-8")
    harness.update_readme("offline", SUMMARY)
    second = readme.read_text(encoding="utf-8")

    assert first.count("<!-- eval:offline:start -->") == 1
    assert second.count("<!-- eval:offline:start -->") == 1
    assert len(second.splitlines()) == len(first.splitlines())


def test_a_mode_with_no_markers_leaves_the_file_alone(readme):
    before = readme.read_text(encoding="utf-8")

    assert harness.update_readme("live", SUMMARY) is False
    assert readme.read_text(encoding="utf-8") == before


def test_a_missing_readme_is_reported_rather_than_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "README_PATH", str(tmp_path / "nope.md"))

    assert harness.update_readme("offline", SUMMARY) is False


# --- the eval set itself ------------------------------------------------------


def test_every_eval_case_declares_the_routing_it_expects():
    cases = harness.load_eval_set()

    assert cases, "the eval set must not be empty"
    for case in cases:
        assert case["question"].strip()
        assert isinstance(case["expects_rag"], bool)
        assert isinstance(case["expects_web"], bool)
        assert case["expects_rag"] or case["expects_web"], case["question"]


def test_the_checked_in_offline_results_match_the_current_metric_set():
    """A stale results file would publish numbers the harness no longer computes."""
    with open(harness.results_path("offline"), encoding="utf-8") as f:
        recorded = json.load(f)

    assert recorded["mode"] == "offline"
    assert set(harness.PIPELINE_METRICS) <= set(recorded["summary"])
    assert set(harness.JUDGEMENT_METRICS) <= set(recorded["summary"])
