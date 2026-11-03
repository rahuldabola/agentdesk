"""One warm MCP tool-server session, shared by every research round in the process.

Why: tracing showed that opening an MCP session - spawning `python -m
app.mcp.server`, importing Chroma, the initialize handshake - took 8.2s of a
27s run, and the Researcher paid it again on every research round of every run.

How: a daemon thread runs a private asyncio event loop. An "owner" task on that
loop enters the session context and keeps it open; stdio_client is anyio-based,
so the same task that entered the context must be the one to exit it. The
Researcher, running in its own short-lived loop per node, sends calls across
with `run_coroutine_threadsafe`-style futures:

    researcher loop  --submit-->  shared loop (owner task holds the session)
         ^                              |
         +------- concurrent.Future <---+

Each call runs in a copy of the caller's contextvars, so OpenTelemetry spans
(and anything else context-scoped) nest under the calling agent as before.

A call that fails at the transport level (the subprocess died, the pipe
broke) tears the session down and is retried once on a fresh one. Tool calls
are read-only searches and page fetches, so a retry is safe. Errors a tool
reports about itself come back as results, not exceptions, and are never retried.
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import contextlib
import contextvars
import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger("agentdesk.mcp")


class SharedSession:
    """A long-lived MCP session behind a thread-safe `call_tool`."""

    def __init__(self, factory: Callable[[], Any]):
        self.factory = factory
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name="agentdesk-mcp", daemon=True
        )
        self._thread.start()
        self._session = None
        self._owner: asyncio.Task | None = None
        self._ready: asyncio.Future | None = None
        self._close: asyncio.Event | None = None
        self.sessions_opened = 0  # observable for tests and logs

    # --- runs on the shared loop ---------------------------------------------

    async def _own(self, ready: asyncio.Future, close: asyncio.Event) -> None:
        try:
            async with self.factory() as session:
                self._session = session
                self.sessions_opened += 1
                log.info("MCP session opened (#%d), kept warm", self.sessions_opened)
                ready.set_result(session)
                await close.wait()
        except BaseException as exc:  # surface start-up failures to the waiting caller
            if not ready.done():
                ready.set_exception(exc)
            if not isinstance(exc, (Exception, asyncio.CancelledError)):
                raise
        finally:
            self._session = None

    async def _session_ready(self):
        if self._owner is None or self._owner.done():
            self._ready = self._loop.create_future()
            self._close = asyncio.Event()
            self._owner = self._loop.create_task(self._own(self._ready, self._close))
        return await asyncio.shield(self._ready)

    async def _discard(self) -> None:
        """Drop a session that failed mid-call; the next call opens a new one."""
        owner, close = self._owner, self._close
        self._owner = None
        if owner is not None and not owner.done():
            close.set()
            try:
                await asyncio.wait_for(owner, timeout=5)
            except BaseException:  # a broken transport may not close cleanly
                owner.cancel()

    async def _call(self, tool_name: str, arguments: dict):
        for attempt in (1, 2):
            session = await self._session_ready()
            try:
                return await session.call_tool(tool_name, arguments)
            except Exception as exc:
                if attempt == 2:
                    raise
                log.warning(
                    "MCP call %s failed (%s: %s); reopening the session and retrying once",
                    tool_name,
                    type(exc).__name__,
                    exc,
                )
                await self._discard()
        raise AssertionError("unreachable")

    # --- called from any thread / loop ---------------------------------------

    def _submit(self, coro_fn: Callable[[], Any]) -> concurrent.futures.Future:
        ctx = contextvars.copy_context()
        result: concurrent.futures.Future = concurrent.futures.Future()

        def start() -> None:
            if not result.set_running_or_notify_cancel():
                return
            task = self._loop.create_task(coro_fn(), context=ctx)

            def finish(t: asyncio.Task) -> None:
                if t.cancelled():
                    result.cancel()
                elif t.exception() is not None:
                    result.set_exception(t.exception())
                else:
                    result.set_result(t.result())

            task.add_done_callback(finish)
            # A caller timing out (asyncio.wait_for) cancels its wrapper future;
            # pass that on so the call stops occupying the shared session.
            result.add_done_callback(
                lambda f: f.cancelled() and self._loop.call_soon_threadsafe(task.cancel)
            )

        self._loop.call_soon_threadsafe(start)
        return result

    async def call_tool(self, tool_name: str, arguments: dict):
        """Same signature as `ClientSession.call_tool`, usable from any event loop."""
        return await asyncio.wrap_future(self._submit(lambda: self._call(tool_name, arguments)))

    def warm(self) -> concurrent.futures.Future:
        """Open the session now (e.g. at server start) instead of on the first question."""
        return self._submit(self._session_ready)

    async def _shutdown(self) -> None:
        """Close the session, then cancel and await anything still running.

        Stopping the loop with tasks pending would abandon them mid-flight - a
        tool call could be inside Chroma when its thread is torn down.
        """
        await self._discard()
        me = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not me and not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=3)

    def close(self, timeout: float = 8.0) -> None:
        if self._loop.is_closed():
            return
        with contextlib.suppress(Exception):  # shutting down: best effort
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop).result(timeout)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
        if self._thread.is_alive():
            log.warning("MCP session thread did not stop within %.0fs", timeout)
        else:
            self._loop.close()


_lock = threading.Lock()
_shared: SharedSession | None = None


def shared_session(factory: Callable[[], Any]) -> SharedSession:
    """The process-wide session for `factory`, created on first use.

    Keyed on the factory so swapping it (tests do) gets a fresh session rather
    than one connected to the old server.
    """
    global _shared
    with _lock:
        # `!=`, not `is not`: a bound method is a fresh object on every access.
        if _shared is not None and _shared.factory != factory:
            _shared.close()
            _shared = None
        if _shared is None:
            _shared = SharedSession(factory)
        return _shared


def reset_shared_session() -> None:
    global _shared
    with _lock:
        if _shared is not None:
            _shared.close()
        _shared = None


atexit.register(reset_shared_session)
