import glob
import os

import chromadb
from openai import OpenAI

COLLECTION_NAME = "agentdesk_docs"
EMBED_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    if not text:
        return []
    step = max(chunk_size - overlap, 1)
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        chunks.append(text[start:start + chunk_size])
        start += step
    return [c.strip() for c in chunks if c.strip()]


def get_chroma_dir():
    return os.environ.get("AGENTDESK_CHROMA_DIR", "./chroma_db")


def get_openai_client():
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def embed_texts(texts, client=None):
    client = client or get_openai_client()
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def get_chroma_collection():
    chroma_client = chromadb.PersistentClient(path=get_chroma_dir())
    return chroma_client.get_or_create_collection(COLLECTION_NAME)


def ingest_docs(docs_dir="data/sample_docs"):
    """Chunk every markdown file in docs_dir, embed the chunks, and upsert into Chroma."""
    collection = get_chroma_collection()
    files = sorted(glob.glob(os.path.join(docs_dir, "*.md")))
    ids, docs, metadatas = [], [], []
    for path in files:
        fname = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        for i, chunk in enumerate(chunk_text(text)):
            ids.append(f"{fname}#{i}")
            docs.append(chunk)
            metadatas.append({"source_file": fname, "chunk_index": i})
    if not ids:
        return 0
    embeddings = embed_texts(docs)
    collection.upsert(ids=ids, documents=docs, metadatas=metadatas, embeddings=embeddings)
    return len(ids)


if __name__ == "__main__":
    count = ingest_docs()
    print(f"Ingested {count} chunks into Chroma collection '{COLLECTION_NAME}' at {get_chroma_dir()}")
