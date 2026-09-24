"""Okapi BM25 over the chunks already stored in Chroma.

Dense embeddings match meaning but blur exact tokens: `AUTH-1003` and
`AUTH-1007` embed almost identically, and an alert name like `HighConsumerLag`
carries little semantic signal. A lexical index catches those, so the retriever
fuses both rankings (see app/rag/retriever.py).

The index is built from the collection itself rather than from the source
files, so the two retrievers always see exactly the same chunks and ids. It is
small enough to rebuild in memory whenever the collection changes.
"""

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass

# Identifiers keep their joiners (auth-1003, x-signature-256, billing.invoice.paid)
# so an exact code matches as one rare token; their parts are indexed as well so
# a question that says "auth" or "1003" alone still matches.
_TOKEN = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
_SPLIT = re.compile(r"[-_.]")

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "may",
        "must",
        "of",
        "on",
        "or",
        "our",
        "should",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "this",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "you",
        "your",
    ]
)


def _stem(token: str) -> str:
    """Strip a plural 's' - enough to match 'deploys' to 'deploy' without a stemmer."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN.findall(text.lower()):
        parts = _SPLIT.split(raw)
        if len(parts) > 1:
            tokens.append(raw)
        tokens.extend(_stem(p) for p in parts if p and p not in STOPWORDS)
    return tokens


@dataclass
class BM25Index:
    ids: list[str]
    term_freqs: list[Counter]
    doc_lens: list[int]
    doc_freq: Counter
    avg_len: float
    k1: float = 1.5
    b: float = 0.75

    @classmethod
    def build(cls, ids: list[str], documents: list[str]) -> "BM25Index":
        term_freqs = [Counter(tokenize(d)) for d in documents]
        doc_lens = [sum(tf.values()) for tf in term_freqs]
        doc_freq: Counter = Counter()
        for tf in term_freqs:
            doc_freq.update(tf.keys())
        avg_len = (sum(doc_lens) / len(doc_lens)) if doc_lens else 0.0
        return cls(list(ids), term_freqs, doc_lens, doc_freq, avg_len)

    def _idf(self, term: str) -> float:
        n, df = len(self.ids), self.doc_freq.get(term, 0)
        # The +1 inside the log keeps idf positive for terms in most documents.
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, top_n: int) -> list[tuple[str, float]]:
        """Return up to top_n (id, score) pairs with a positive score, best first."""
        terms = set(tokenize(query))
        if not terms or not self.ids:
            return []
        scores = []
        for doc_id, tf, length in zip(self.ids, self.term_freqs, self.doc_lens, strict=True):
            score = 0.0
            norm = self.k1 * (1 - self.b + self.b * length / (self.avg_len or 1.0))
            for term in terms:
                freq = tf.get(term)
                if freq:
                    score += self._idf(term) * freq * (self.k1 + 1) / (freq + norm)
            if score > 0:
                scores.append((doc_id, score))
        scores.sort(key=lambda pair: pair[1], reverse=True)
        return scores[:top_n]


_indexes: dict[tuple[str, str], tuple[int, BM25Index]] = {}
_lock = threading.Lock()


def get_index(collection, cache_key: tuple[str, str]) -> BM25Index:
    """The BM25 index for `collection`, rebuilt only when its chunk count changes.

    Ingest also calls `invalidate()`, which covers a re-ingest that happens to
    produce the same number of chunks with different content.
    """
    count = collection.count()
    cached = _indexes.get(cache_key)
    if cached is not None and cached[0] == count:
        return cached[1]
    with _lock:
        cached = _indexes.get(cache_key)
        if cached is not None and cached[0] == count:
            return cached[1]
        data = collection.get(include=["documents"])
        index = BM25Index.build(data["ids"], data["documents"])
        _indexes[cache_key] = (count, index)
        return index


def invalidate(cache_key: tuple[str, str] | None = None) -> None:
    with _lock:
        if cache_key is None:
            _indexes.clear()
        else:
            _indexes.pop(cache_key, None)
