"""Shared plumbing for graph nodes: timing, logging, and trace entries.

Every node is a plain `state -> partial update` function. The decorator adds
the cross-cutting concerns once instead of five times, and guarantees the
trace entry is emitted even when the node raises.
"""

import functools
import logging
import time
from collections.abc import Callable

from app.observability import measure, tracer

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
            with (
                tracer.start_as_current_span(f"agent.{name}") as span,
                measure() as ledger,
            ):
                span.set_attribute("agentdesk.agent", name)
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
                    raise  # the span context manager records the exception

                elapsed = (time.perf_counter() - started) * 1000
                detail = update.pop(DETAIL_KEY, "")
                usage = ledger.usage.as_dict()
                for key, value in usage.items():
                    span.set_attribute(f"agentdesk.{key}", value)
                span.set_attribute("agentdesk.detail", str(detail))

            log.info(
                "node %s: done in %.0fms, %d LLM call(s), %d tokens - %s",
                name,
                elapsed,
                usage["llm_calls"],
                usage["tokens_in"] + usage["tokens_out"],
                detail,
            )
            update["trace"] = [
                {"node": name, "detail": detail, "elapsed_ms": round(elapsed, 1), **usage}
            ]
            return update

        return wrapper

    return decorate
