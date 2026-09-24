"""Cross-encoder reranking of retrieval candidates.

Bi-encoder retrieval (dense or BM25) scores the query and each chunk
independently. A cross-encoder reads the query and the chunk together, which is
far more precise but too slow to run over a whole corpus - so it only reorders
the short candidate list that retrieval already produced.

The model runs locally on ONNX via fastembed (no API calls, no torch). It is an
optional dependency: install with `pip install .[rerank]`.
"""

import logging
import threading

log = logging.getLogger("agentdesk.rag")

_models: dict[str, object] = {}
_lock = threading.Lock()


class RerankerUnavailable(RuntimeError):
    """fastembed is not installed, or the model could not be loaded."""


def _load(model_name: str):
    model = _models.get(model_name)
    if model is not None:
        return model
    with _lock:
        model = _models.get(model_name)
        if model is None:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
            except ImportError as exc:
                raise RerankerUnavailable(
                    "reranking needs fastembed - install with `pip install .[rerank]`"
                ) from exc
            try:
                model = TextCrossEncoder(model_name=model_name)
            except Exception as exc:
                raise RerankerUnavailable(f"could not load reranker '{model_name}': {exc}") from exc
            log.info("loaded cross-encoder reranker %s", model_name)
            _models[model_name] = model
        return model


def rerank_scores(query: str, documents: list[str], model_name: str) -> list[float]:
    """One relevance score per document, in input order. Higher is more relevant."""
    if not documents:
        return []
    return [float(s) for s in _load(model_name).rerank(query, documents)]


def warm_up(model_name: str) -> None:
    """Load (and if needed download) the model now rather than on the first query."""
    _load(model_name)
