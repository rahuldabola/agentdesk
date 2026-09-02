from app.rag.ingest import embed_texts, get_chroma_collection


def rag_search(query, k=4):
    collection = get_chroma_collection()
    count = collection.count()
    if count == 0:
        return []
    query_embedding = embed_texts([query])[0]
    results = collection.query(query_embeddings=[query_embedding], n_results=min(k, count))
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    ids = results.get("ids", [[]])[0]
    notes = []
    for doc, meta, id_ in zip(docs, metas, ids):
        notes.append({
            "source_id": f"rag:{id_}",
            "source_type": "rag",
            "content": doc,
        })
    return notes
