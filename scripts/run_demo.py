"""Run one question through the full graph and print the result.

Usage: python -m scripts.run_demo "your question"
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from app.errors import AgentDeskError  # noqa: E402
from app.graph import run_agentdesk  # noqa: E402


def render(result: dict) -> None:
    print("\n=== TRACE ===")
    for entry in result.get("trace", []):
        print(f"  {entry['node']:<11} {entry['elapsed_ms']:>8.0f}ms  {entry['detail']}")

    status = result.get("status", "unknown")
    print(f"\n=== REPORT ({status}) ===\n")
    if status == "revision_limit_reached":
        print("!! The Critic never accepted this draft. Returning it unverified.\n")
    print(result.get("final_report") or "(no report produced)")

    citations = result.get("citations", [])
    print(f"\n=== CITATIONS ({len(citations)}) ===")
    for c in citations:
        where = c.get("url") or f"{c.get('file')} chunk {c.get('chunk_index')}"
        print(f"  [{c['source_id']}] {where}")
    if not citations:
        print("  (none - the report cited no retrievable source)")

    unsupported = result.get("unsupported_claims") or []
    if unsupported:
        print(f"\n=== CLAIMS THE CRITIC FLAGGED ({len(unsupported)}) ===")
        for claim in unsupported:
            print(f"  - {claim}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="+", help="the research question")
    parser.add_argument("-v", "--verbose", action="store_true", help="show per-node logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        render(run_agentdesk(" ".join(args.question)))
    except AgentDeskError as exc:
        print(f"\n{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
