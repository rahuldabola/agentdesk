"""Answer-quality eval: is the final report correct, and is it faithful to its sources?

The pipeline eval (run_eval.py) checks that a report is produced and every
citation resolves; the retrieval benchmark (run_retrieval_eval.py) checks that
the right chunks come back. Neither says whether the *answer* is right. This
runs the full live pipeline - planner, MCP tools, analyst, writer, critic - on
questions from the labelled retrieval set, and grades each report:

  correctness     an LLM judge compares the report with the gold evidence
                  chunk(s): correct / partial / incorrect
  faithfulness    an LLM judge checks every claim against the passages the
                  report actually cites: supported claims / all claims
  gold_cited      deterministic: does the report cite a chunk that contains
                  the gold evidence?
  no_fabrication  deterministic, unanswerable questions only: the report
                  cites no internal document (it may still answer from the web)

The judge is a different model from the one under test
(AGENTDESK_JUDGE_MODEL; the default is a flash-lite model because stronger ones
exceed the free tier's daily quota), so the pipeline is not grading its own
homework, and
its reliability is measured rather than assumed: every answerable question is
also judged against a report written for a *different* question, which a
working judge must mark incorrect (`judge_sanity`).

Live only - it needs GEMINI_API_KEY and makes a few hundred free-tier calls.
Results are checked in (eval/results_answers.json) and rendered into the README.
"""

import argparse
import json
import logging
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.rag.ingest import chunk_text  # noqa: E402

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(EVAL_DIR)
README_PATH = os.path.join(REPO_ROOT, "README.md")
SET_PATH = os.path.join(EVAL_DIR, "retrieval_set.json")
RESULTS_PATH = os.path.join(EVAL_DIR, "results_answers.json")
DOCS_DIR = os.path.join(REPO_ROOT, "data", "sample_docs")

# A fixed, stratified subset keeps a run inside free-tier quotas and makes runs
# comparable over time: the first N of each type, in file order.
PER_TYPE = {"keyword": 8, "paraphrase": 10, "multi": 8}
NEGATIVES_PER_TYPE = 4
CITATION = re.compile(r"\[([^\]\s]+:[^\]\s]+)\]")
GRADE_SCORE = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}

CORRECTNESS_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string", "description": "one or two sentences"},
        "grade": {"type": "string", "enum": ["correct", "partial", "incorrect"]},
    },
    "required": ["reasoning", "grade"],
}
CORRECTNESS_SYSTEM = """You grade answers against reference material.
- correct: the answer states the key facts the reference gives for this question, with no
  contradiction. Extra accurate detail is fine.
- partial: some key facts are present but others are missing (for a two-part question, one
  part answered), or a key detail is vague.
- incorrect: the key facts are missing or contradicted, or the answer addresses a different
  question.
Judge only against the reference; do not use outside knowledge."""

FAITHFULNESS_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "description": "every factual claim in the report",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "supported": {"type": "boolean"},
                },
                "required": ["claim", "supported"],
            },
        }
    },
    "required": ["claims"],
}
FAITHFULNESS_SYSTEM = """You check a report against the passages it cites.
List every factual claim in the report. A claim is supported only if the cited passages state
it or directly imply it. Do not use outside knowledge: a claim that is true in the world but
absent from the passages is unsupported. Ignore headings, framing and hedging sentences."""


def load_subset(path: str = SET_PATH) -> tuple[list[dict], list[dict]]:
    with open(path, encoding="utf-8") as f:
        bench = json.load(f)
    queries = []
    for qtype, n in PER_TYPE.items():
        queries += [q for q in bench["queries"] if q["type"] == qtype][:n]
    negatives = []
    for neg_type in ("off-topic", "near-domain"):
        negatives += [n for n in bench["negatives"] if n["type"] == neg_type][:NEGATIVES_PER_TYPE]
    return queries, negatives


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def gold_passages(gold: list[dict], docs_dir: str = DOCS_DIR) -> list[str]:
    """The chunk text holding each gold item's evidence: the judge's reference."""
    passages = []
    for item in gold:
        for alt in item.get("any_of", [item]):
            with open(os.path.join(docs_dir, alt["file"]), encoding="utf-8") as f:
                chunks = chunk_text(f.read())
            match = next((c for c in chunks if _norm(alt["evidence"]) in _norm(c)), None)
            if match:
                passages.append(f"({alt['file']}) {match}")
                break
    return passages


def cited_ids(report: str) -> list[str]:
    return list(dict.fromkeys(CITATION.findall(report or "")))


def gold_cited(report: str, notes: list[dict], gold: list[dict]) -> bool:
    """True if some cited internal chunk contains a gold item's evidence."""
    by_id = {n["source_id"]: n for n in notes}
    for source_id in cited_ids(report):
        note = by_id.get(source_id)
        if not note or not source_id.startswith("rag:"):
            continue
        file = source_id[4:].split("#")[0]
        for item in gold:
            for alt in item.get("any_of", [item]):
                if alt["file"] == file and _norm(alt["evidence"]) in _norm(note["content"]):
                    return True
    return False


def with_retries(fn, attempts: int = 4, delay: float = 20.0):
    """Retry a whole call on any exception. The client already retries single
    requests; this outlasts longer overload spells (503 "high demand") and
    dropped connections that would otherwise sink one question of a long run."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts:
                raise
            wait = delay * attempt
            print(
                f"  retrying in {wait:.0f}s after {type(exc).__name__}: {str(exc)[:90]}",
                file=sys.stderr,
            )
            time.sleep(wait)
    raise AssertionError("unreachable")


def judge_correctness(question: str, reference: list[str], report: str, model: str) -> dict:
    from app.llm.gemini_client import structured_call

    prompt = (
        f"Question: {question}\n\nReference material:\n"
        + "\n\n".join(reference)
        + f"\n\nAnswer to grade:\n{report}"
    )
    return structured_call(
        CORRECTNESS_SYSTEM,
        prompt,
        "submit_grade",
        "Submit the grade",
        CORRECTNESS_SCHEMA,
        model=model,
    )


def judge_faithfulness(report: str, notes: list[dict], model: str) -> dict:
    from app.llm.gemini_client import structured_call

    by_id = {n["source_id"]: n for n in notes}
    passages = [f"[{sid}] {by_id[sid]['content']}" for sid in cited_ids(report) if sid in by_id]
    if not passages:
        return {"claims": []}
    prompt = "Cited passages:\n" + "\n\n".join(passages) + f"\n\nReport:\n{report}"
    return structured_call(
        FAITHFULNESS_SYSTEM,
        prompt,
        "submit_claims",
        "Submit the claims",
        FAITHFULNESS_SCHEMA,
        model=model,
        max_tokens=2048,
    )


def ingest_real_corpus(chroma_dir: str) -> None:
    """Ingest in a child process, as production does at boot, so this process
    never holds a Chroma handle the MCP tool subprocess also opens."""
    env = dict(os.environ, AGENTDESK_CHROMA_DIR=chroma_dir, AGENTDESK_COLLECTION="answer-eval")
    subprocess.run(
        [sys.executable, "-m", "scripts.ingest_docs", DOCS_DIR],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
    )


def run_pipeline(question: str) -> dict:
    from app.graph import run_agentdesk

    started = time.perf_counter()
    try:
        result = with_retries(lambda: run_agentdesk(question))
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "latency_s": 0.0}
    return {
        "report": result.get("final_report") or "",
        "status": result.get("status"),
        "notes": [
            {"source_id": n["source_id"], "content": n["content"]}
            for n in result.get("research_notes", [])
        ],
        "latency_s": round(time.perf_counter() - started, 1),
    }


def summarise(rows: list[dict], negative_rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    judged = [r for r in ok if "grade" in r]
    claims = [c for r in ok for c in r.get("claims", [])]
    by_type = {}
    for qtype in PER_TYPE:
        grades = [GRADE_SCORE[r["grade"]] for r in judged if r["type"] == qtype]
        if grades:
            by_type[qtype] = round(statistics.mean(grades), 3)
    sanity = [r["sanity_grade"] == "incorrect" for r in judged if "sanity_grade" in r]
    neg_ok = [r for r in negative_rows if "error" not in r]
    return {
        "answerable": len(rows),
        "errors": len(rows) - len(ok) + len(negative_rows) - len(neg_ok),
        "correctness": round(statistics.mean(GRADE_SCORE[r["grade"]] for r in judged), 3)
        if judged
        else 0.0,
        "fully_correct_rate": round(sum(r["grade"] == "correct" for r in judged) / len(judged), 3)
        if judged
        else 0.0,
        "correctness_by_type": by_type,
        "faithfulness": round(sum(c["supported"] for c in claims) / len(claims), 3)
        if claims
        else 0.0,
        "claims_checked": len(claims),
        "gold_cited_rate": round(sum(r["gold_cited"] for r in ok) / len(ok), 3) if ok else 0.0,
        "unanswerable": len(negative_rows),
        "no_fabrication_rate": round(sum(r["no_fabrication"] for r in neg_ok) / len(neg_ok), 3)
        if neg_ok
        else 0.0,
        "judge_sanity": round(sum(sanity) / len(sanity), 3) if sanity else 0.0,
        "mean_latency_s": round(statistics.mean(r["latency_s"] for r in ok), 1) if ok else 0.0,
    }


def run(judge_model: str, pause: float, limit: int | None = None) -> dict:
    queries, negatives = load_subset()
    if limit:
        queries, negatives = queries[:limit], negatives[: max(1, limit // 4)]

    chroma_dir = os.path.join(tempfile.mkdtemp(), "chroma")
    ingest_real_corpus(chroma_dir)
    os.environ["AGENTDESK_CHROMA_DIR"] = chroma_dir
    os.environ["AGENTDESK_COLLECTION"] = "answer-eval"

    rows = []
    for i, q in enumerate(queries, start=1):
        print(f"[{i}/{len(queries)}] {q['id']}: {q['question']}", file=sys.stderr)
        row = {
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
            **run_pipeline(q["question"]),
        }
        if "error" not in row:
            reference = gold_passages(q["gold"])
            verdict = with_retries(
                lambda q=q, row=row, reference=reference: judge_correctness(
                    q["question"], reference, row["report"], judge_model
                )
            )
            row["grade"], row["grade_reason"] = verdict["grade"], verdict.get("reasoning", "")
            row["claims"] = with_retries(
                lambda row=row: judge_faithfulness(row["report"], row["notes"], judge_model)
            )["claims"]
            row["gold_cited"] = gold_cited(row["report"], row["notes"], q["gold"])
        rows.append(row)
        time.sleep(pause)

    # Judge sanity: grade each report against the *next* question's reference.
    # A judge that calls these correct is not reading the reference.
    ok = [(q, r) for q, r in zip(queries, rows, strict=True) if "grade" in r]
    for (q, r), (other_q, _) in zip(ok, ok[1:] + ok[:1], strict=True):
        if other_q["id"] == q["id"]:
            continue
        verdict = with_retries(
            lambda other_q=other_q, r=r: judge_correctness(
                other_q["question"], gold_passages(other_q["gold"]), r["report"], judge_model
            )
        )
        r["sanity_grade"] = verdict["grade"]

    negative_rows = []
    for neg in negatives:
        print(f"[neg] {neg['question']}", file=sys.stderr)
        row = {"type": neg["type"], "question": neg["question"], **run_pipeline(neg["question"])}
        if "error" not in row:
            row["no_fabrication"] = not any(s.startswith("rag:") for s in cited_ids(row["report"]))
        negative_rows.append(row)
        time.sleep(pause)

    from app.config import get_settings

    return {
        "meta": {
            "model": get_settings().gemini_model,
            "judge_model": judge_model,
            "max_distance": get_settings().max_distance,
            "retrieval_mode": get_settings().retrieval_mode,
        },
        "summary": summarise(rows, negative_rows),
        "rows": rows,
        "negative_rows": negative_rows,
    }


def render_table(result: dict) -> str:
    meta, s = result["meta"], result["summary"]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    by_type = s["correctness_by_type"]
    return "\n".join(
        [
            f"_Live run, {s['answerable']} answerable + {s['unanswerable']} unanswerable "
            f"questions. Pipeline model `{meta['model']}`, judge `{meta['judge_model']}`. "
            f"Recorded {stamp}._",
            "",
            "| Metric | Result | How it is measured |",
            "| --- | --- | --- |",
            f"| Correctness | {s['correctness']:.2f} | judge vs gold evidence; "
            "correct = 1, partial = 0.5 |",
            f"| Fully correct | {s['fully_correct_rate']:.0%} | share graded `correct` |",
            f"| ↳ keyword / paraphrase / multi-doc | {by_type.get('keyword', 0):.2f} / "
            f"{by_type.get('paraphrase', 0):.2f} / {by_type.get('multi', 0):.2f} | |",
            f"| Faithfulness | {s['faithfulness']:.2f} | supported claims / all claims "
            f"({s['claims_checked']} checked against cited passages) |",
            f"| Gold evidence cited | {s['gold_cited_rate']:.0%} | deterministic |",
            f"| No fabricated internal answer | {s['no_fabrication_rate']:.0%} | "
            "unanswerable questions citing no internal doc; deterministic |",
            f"| Judge sanity | {s['judge_sanity']:.0%} | "
            "mismatched answers the judge correctly fails |",
            f"| Errors | {s['errors']} | runs that raised |",
            f"| Mean latency | {s['mean_latency_s']:.1f} s | full pipeline, per question |",
        ]
    )


def update_readme(result: dict) -> bool:
    start, end = "<!-- eval:answers:start -->", "<!-- eval:answers:end -->"
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
    parser.add_argument(
        "--judge-model", default=os.environ.get("AGENTDESK_JUDGE_MODEL", "gemini-3.5-flash-lite")
    )
    parser.add_argument("--pause", type=float, default=3.0, help="seconds between pipeline runs")
    parser.add_argument("--limit", type=int, help="only the first N answerable questions (smoke)")
    parser.add_argument("--write", action="store_true", help="save results and update README")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not os.environ.get("GEMINI_API_KEY"):
        parser.error("needs GEMINI_API_KEY")

    result = run(args.judge_model, args.pause, args.limit)
    print(render_table(result))
    if args.write:
        with open(RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"wrote {os.path.relpath(RESULTS_PATH, REPO_ROOT)}", file=sys.stderr)
        if update_readme(result):
            print("updated the answer-quality table in README.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
