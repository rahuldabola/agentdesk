from dotenv import load_dotenv

load_dotenv()

from app.rag.ingest import ingest_docs  # noqa: E402

if __name__ == "__main__":
    n = ingest_docs()
    print(f"Ingested {n} chunks.")
