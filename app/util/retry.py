"""Exponential backoff for calls that cross a network boundary."""

import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

log = logging.getLogger("agentdesk.retry")

T = TypeVar("T")


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int,
    base_delay: float,
    retryable: Callable[[BaseException], bool],
    description: str,
    sleep: Callable[[float], None] = time.sleep,
    delay_hint: Callable[[BaseException], float | None] | None = None,
) -> T:
    """Call `fn`, retrying transient failures with jittered exponential backoff.

    `sleep` is injectable so tests exercise the backoff path without waiting.
    `delay_hint`, when given, lets a 429 that names its own cooldown (Gemini's
    `RetryInfo.retryDelay`) override the guessed exponential wait instead of
    retrying blind into a quota that is not back yet.
    """
    last: BaseException | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last = exc
            if attempt >= attempts or not retryable(exc):
                raise
            hinted = delay_hint(exc) if delay_hint else None
            if hinted is not None:
                delay = hinted
            else:
                delay = base_delay * (2 ** (attempt - 1))
                delay += random.uniform(0, delay / 2)  # jitter, so parallel callers desync
            log.warning(
                "%s failed (attempt %d/%d): %s: %s - retrying in %.2fs",
                description,
                attempt,
                attempts,
                type(exc).__name__,
                exc,
                delay,
            )
            sleep(delay)
    raise last  # unreachable; keeps type checkers honest
