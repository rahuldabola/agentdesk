import sys

from dotenv import load_dotenv

load_dotenv()

from app.graph import run_agentdesk  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print('Usage: python -m scripts.run_demo "your question"')
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    result = run_agentdesk(question)

    print("\n=== TRACE ===")
    for line in result.get("trace", []):
        print(f"- {line}")

    print("\n=== REPORT ===\n")
    print(result.get("final_report") or "(no report produced)")

    print("\n=== CITATIONS ===")
    for c in result.get("citations", []):
        print(f"- {c}")


if __name__ == "__main__":
    main()
