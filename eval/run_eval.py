import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.graph import run_agentdesk  # noqa: E402


def load_eval_set(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "eval_set.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_eval(path=None):
    cases = load_eval_set(path)
    rows = []
    completed = revised = routing_correct = cited = 0

    for case in cases:
        try:
            result = run_agentdesk(case["question"])
        except Exception as e:
            rows.append({"question": case["question"], "error": str(e)})
            continue

        report = result.get("final_report")
        routing_ok = (
            result.get("use_rag") == case.get("expects_rag")
            and result.get("use_web") == case.get("expects_web")
        )

        completed += bool(report)
        revised += result.get("revision_count", 0) > 0
        routing_correct += routing_ok
        cited += bool(result.get("citations"))

        rows.append({
            "question": case["question"],
            "completed": bool(report),
            "revisions": result.get("revision_count", 0),
            "routing_correct": routing_ok,
            "citations": len(result.get("citations", [])),
        })

    n = len(cases) or 1
    summary = {
        "task_completion_rate": completed / n,
        "critic_revision_rate": revised / n,
        "tool_routing_accuracy": routing_correct / n,
        "citation_coverage": cited / n,
    }
    return summary, rows


if __name__ == "__main__":
    summary, rows = run_eval()
    print(json.dumps({"summary": summary, "rows": rows}, indent=2))
