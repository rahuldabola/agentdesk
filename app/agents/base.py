"""Shared plumbing for graph nodes: timing, logging, and trace entries.

Every node is a plain `state -> partial update` function. The decorator adds
the cross-cutting concerns once instead of five times, and guarantees the
trace entry is emitted even when the node raises.
"""

import functools
import logging
import time
from collections.abc import Callable

log = logging.getLogger("agentdesk.graph")

# Nodes put their human-readable summary here; the decorator moves it into the
# trace entry so it never leaks into the graph state.
DETAIL_KEY = "_detail"


def node(name: str) -> Callable:
    def decorate(fn: Callable[[dict], dict]) -> Callable[[dict], dict]:
        @functools.wraps(fn)
        def wrapper(state: dict) -> dict:
            started = time.perf_counter()
            log.info("node %s: start", name)
            try:
                update = fn(state) or {}
            except Exception as exc:
                elapsed = (time.perf_counter() - started) * 1000
                log.error(
                    "node %s: failed after %.0fms: %s: %s",
                    name,
                    elapsed,
                    type(exc).__name__,
                    exc,
                )
                raise

            elapsed = (time.perf_counter() - started) * 1000
            detail = update.pop(DETAIL_KEY, "")
            log.info("node %s: done in %.0fms - %s", name, elapsed, detail)
            update["trace"] = [{"node": name, "detail": detail, "elapsed_ms": round(elapsed, 1)}]
            return update

        return wrapper

    return decorate
