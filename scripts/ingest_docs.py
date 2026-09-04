"""Embed data/sample_docs/*.md into the local Chroma store.

Usage: python -m scripts.ingest_docs [docs_dir]
"""

import logging
import sys

from dotenv import load_dotenv

load_dotenv()

from app.config import get_settings  # noqa: E402
from app.errors import AgentDeskError  # noqa: E402
from app.rag.ingest import ingest_docs  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    docs_dir = sys.argv[1] if len(sys.argv) > 1 else "data/sample_docs"
    settings = get_settings()
    try:
        count = ingest_docs(docs_dir=docs_dir)
    except AgentDeskError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        f"Ingested {count} chunks from {docs_dir} into collection "
        f"'{settings.collection_name}' at {settings.chroma_dir}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
