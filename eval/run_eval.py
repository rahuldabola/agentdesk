"""Run the eval set through the full graph and report metrics.

Two modes:

  --offline  (default)  Deterministic. Real graph, real MCP protocol, real
                        Chroma; a scripted stub stands in for Gemini and the
                        embedding/search APIs. Costs nothing, runs in CI, and
                        catches pipeline regressions.
  --live                Real Gemini, real embeddings, real web search. Needs
                        GEMINI_API_KEY, and costs money.

Metrics fall into two groups. Pipeline metrics (task_completion_rate,
citation_validity, citation_coverage, termination_rate) describe the system
and are meaningful in both modes - CI asserts on them. Judgement metrics
(tool_routing_accuracy, critic_revision_rate) describe whichever model is
answering, so offline they are a property of the stub, not of Gemini.
"""

import argparse
import json
import logging
import os
import statistics
import sys
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.graph import extract_citation_ids, run_agentdesk  # noqa: E402

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(EVAL_DIR)
README_PATH = os.path.join(REPO_ROOT, "README.md")

# Metrics that describe the orchestrator, and hold whichever model is answering.
PIPELINE_METRICS = (
    "task_completion_rate",
    "termination_rate",
    "citation_coverage",
    "citation_validity",
    "error_rate",
)
# Metrics that describe the model doing the judging, not the pipeline.
JUDGEMENT_METRICS = (
    "tool_routing_accuracy",
    "critic_revision_rate",
    "research_loop_rate",
    "unverified_report_rate",
)


def results_path(mode: str) -> str:
    return os.path.join(EVAL_DIR, f"results_{mode}.json")


# Pipeline invariants. A change that breaks one of these is a regression in the
# orchestrator, independent of how good the underlying model is.
OFFLINE_THRESHOLDS = {
    "task_completion_rate": 1.0,
    "termination_rate": 1.0,
    "citation_validity": 1.0,
    "error_rate": 0.0,
}


def load_eval_set(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "eval_set.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def offline_patches(docs_dir, chroma_dir):
    """Swap the three true external dependencies for deterministic stand-ins."""
    from eval import stub_model
    from tests.doubles import fake_embed_texts, in_memory_mcp_session

    os.environ["AGENTDESK_CHROMA_DIR"] = chroma_dir
    os.environ["AGENTDESK_COLLECTION"] = "agentdesk-eval"
    os.environ.setdefault("GEMINI_API_KEY", "offline-stub")
    os.environ.pop("TAVILY_API_KEY", None)

    return [
        patch("app.rag.ingest.embed_texts", fake_embed_texts),
        patch("app.rag.retriever.embed_texts", fake_embed_texts),
        # Run the MCP server in-process, so the tool side sees these stubs too.
        # The protocol path (handshake, schemas, JSON-RPC) is still the real one.
        patch("app.agents.researcher.mcp_session", in_memory_mcp_session),
        patch("app.agents.planner.structured_call", stub_model.structured_call),
        patch("app.agents.analyst.structured_call", stub_model.structured_call),
        patch("app.agents.critic.structured_call", stub_model.structured_call),
        patch("app.agents.writer.text_call", stub_model.text_call),
        patch("app.mcp.tools._duckduckgo_search", stub_model.synthetic_web_search),
    ]


def evaluate_case(case):
    started = time.perf_counter()
    try:
        result = run_agentdesk(case["question"])
    except Exception as exc:
        return {
            "question": case["question"],
            "error": f"{type(exc).__name__}: {exc}",
            "latency_s": round(time.perf_counter() - started, 2),
        }

    report = result.get("final_report") or ""
    sources = result.get("sources", {})
    markers = extract_citation_ids(report)
    resolvable = [m for m in markers if m in sources]

    return {
        "question": case["question"],
        "completed": bool(report.strip()),
        "status": result.get("status"),
        "routing_correct": (
            result.get("use_rag") == case.get("expects_rag")
            and result.get("use_web") == case.get("expects_web")
        ),
        "routed": {"use_rag": result.get("use_rag"), "use_web": result.get("use_web")},
        "revisions": result.get("revision_count", 0),
        "research_rounds": result.get("research_rounds", 0),
        "notes": len(result.get("research_notes", [])),
        "facts": len(result.get("facts", [])),
        "citation_markers": len(markers),
        "citations_resolved": len(resolvable),
        "latency_s": round(time.perf_counter() - started, 2),
    }


def summarise(rows):
    n = len(rows) or 1
    ok = [r for r in rows if "error" not in r]
    markers = sum(r["citation_markers"] for r in ok)
    resolved = sum(r["citations_resolved"] for r in ok)

    return {
        "cases": len(rows),
        # Pipeline metrics - CI asserts on these.
        "task_completion_rate": sum(r["completed"] for r in ok) / n,
        "termination_rate": len(ok) / n,
        "error_rate": (len(rows) - len(ok)) / n,
        "citation_coverage": sum(r["citation_markers"] > 0 for r in ok) / n,
        "citation_validity": (resolved / markers) if markers else 0.0,
        # Judgement metrics - a property of whichever model answered.
        "tool_routing_accuracy": sum(r["routing_correct"] for r in ok) / n,
        "critic_revision_rate": sum(r["revisions"] > 0 for r in ok) / n,
        "research_loop_rate": sum(r["research_rounds"] > 0 for r in ok) / n,
        "unverified_report_rate": sum(r["status"] == "revision_limit_reached" for r in ok) / n,
        "mean_latency_s": (
            round(statistics.mean([r["latency_s"] for r in rows]), 2) if rows else 0.0
        ),
    }


def run_eval(mode="offline", eval_path=None, docs_dir="data/sample_docs", chroma_dir=None):
    cases = load_eval_set(eval_path)

    with ExitStack() as stack:
        if mode == "offline":
            import tempfile

            chroma_dir = chroma_dir or os.path.join(tempfile.mkdtemp(), "chroma")
            for p in offline_patches(docs_dir, chroma_dir):
                stack.enter_context(p)
            from app.rag.ingest import ingest_docs

            ingest_docs(docs_dir=docs_dir)

        rows = [evaluate_case(case) for case in cases]

    return summarise(rows), rows


def render_table(mode: str, summary: dict) -> str:
    """Render the summary as the markdown block the README embeds."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        f"_{mode.capitalize()} run, {summary['cases']} cases, recorded {stamp}._",
        "",
        "| Metric | Result | Measures |",
        "| --- | --- | --- |",
    ]
    for metric in PIPELINE_METRICS:
        lines.append(f"| `{metric}` | {summary[metric]:.2f} | the pipeline |")
    for metric in JUDGEMENT_METRICS:
        target = "the stub" if mode == "offline" else "the model"
        lines.append(f"| `{metric}` | {summary[metric]:.2f} | {target} |")
    lines.append(f"| `mean_latency_s` | {summary['mean_latency_s']:.2f} | — |")
    return "\n".join(lines)


def update_readme(mode: str, summary: dict) -> bool:
    """Replace the README block between this mode's markers. No markers, no edit."""
    start, end = f"<!-- eval:{mode}:start -->", f"<!-- eval:{mode}:end -->"
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
        f.write(f"{head}{start}\n{render_table(mode, summary)}\n{end}{tail}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--offline", action="store_true", help="deterministic stub run (default)")
    group.add_argument("--live", action="store_true", help="real API calls; costs money")
    parser.add_argument(
        "--write", action="store_true", help="write offline results to eval/results_offline.json"
    )
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero if a pipeline metric regresses"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show per-node logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    mode = "live" if args.live else "offline"
    if mode == "live" and not os.environ.get("GEMINI_API_KEY"):
        parser.error("--live needs GEMINI_API_KEY")

    summary, rows = run_eval(mode=mode)
    document = {"mode": mode, "summary": summary, "rows": rows}
    print(json.dumps(document, indent=2))

    if args.write:
        path = results_path(mode)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(document, f, indent=2)
            f.write("\n")
        print(f"\nwrote {path}", file=sys.stderr)
        if update_readme(mode, summary):
            print(f"updated the {mode} results table in README.md", file=sys.stderr)

    if args.check:
        failures = [
            f"{metric}: {summary[metric]:.3f} < {threshold}"
            for metric, threshold in OFFLINE_THRESHOLDS.items()
            if (
                summary[metric] > threshold
                if metric == "error_rate"
                else summary[metric] < threshold
            )
        ]
        if failures:
            print("\nPIPELINE REGRESSION:\n  " + "\n  ".join(failures), file=sys.stderr)
            return 1
        print("\nall pipeline thresholds met", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
