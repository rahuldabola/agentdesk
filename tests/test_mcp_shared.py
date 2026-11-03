"""The warm, shared MCP session: reuse, concurrency, recovery, cancellation, context.

Uses stand-in sessions for the failure cases and the real in-memory MCP server
(tests/doubles.py) for the end-to-end reuse case.
"""

import asyncio
import contextvars
import threading
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.agents.researcher as researcher
from app.mcp.client import call_tool
from app.mcp.shared import SharedSession, reset_shared_session, shared_session
from tests.doubles import in_memory_mcp_session

REQUEST_ID = contextvars.ContextVar("request_id", default=None)


def result(text='{"results": []}', is_error=False):
    return SimpleNamespace(isError=is_error, content=[SimpleNamespace(text=text)])


class FakeServer:
    """Counts sessions; each session can be told to fail its next N calls."""

    def __init__(self, fail_calls=0, delay=0.0):
        self.opened = 0
        self.closed = 0
        self.calls = []
        self.fail_calls = fail_calls
        self.delay = delay
        self.seen_request_ids = []

    @asynccontextmanager
    async def factory(self):
        self.opened += 1
        server = self

        class Session:
            async def call_tool(self, name, args):
                server.seen_request_ids.append(REQUEST_ID.get())
                if server.delay:
                    await asyncio.sleep(server.delay)
                server.calls.append(name)
                if server.fail_calls:
                    server.fail_calls -= 1
                    raise BrokenPipeError("tool server went away")
                return result()

        try:
            yield Session()
        finally:
            self.closed += 1


@pytest.fixture
def shared():
    sessions = []

    def make(factory):
        s = SharedSession(factory)
        sessions.append(s)
        return s

    yield make
    for s in sessions:
        s.close()


def test_one_session_serves_every_call():
    server = FakeServer()
    session = shared_session(server.factory)

    async def calls():
        return await asyncio.gather(*(call_tool(session, "rag_search", {}) for _ in range(5)))

    asyncio.run(calls())
    asyncio.run(calls())  # a second "research round" on a new event loop

    assert server.opened == 1
    assert len(server.calls) == 10


def test_calls_from_many_threads_share_the_session(shared):
    server = FakeServer(delay=0.01)
    session = shared(server.factory)
    errors = []

    def worker():
        try:
            asyncio.run(call_tool(session, "web_search", {}))
        except Exception as exc:  # pragma: no cover - surfaced by the assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert server.opened == 1 and len(server.calls) == 8


def test_a_dead_transport_is_reopened_and_the_call_retried_once(shared):
    server = FakeServer(fail_calls=1)
    session = shared(server.factory)

    payload = asyncio.run(call_tool(session, "rag_search", {}))

    assert payload == {"results": []}
    assert server.opened == 2, "the broken session is replaced"
    assert server.closed >= 1
    assert session.sessions_opened == 2


def test_a_second_consecutive_failure_is_raised_not_retried_forever(shared):
    server = FakeServer(fail_calls=5)
    session = shared(server.factory)

    with pytest.raises(BrokenPipeError):
        asyncio.run(call_tool(session, "rag_search", {}))
    assert len(server.calls) == 2


def test_an_error_the_tool_reports_is_a_result_not_a_retry(shared):
    class ErrorServer(FakeServer):
        @asynccontextmanager
        async def factory(self):
            self.opened += 1

            class Session:
                async def call_tool(inner, name, args):
                    self.calls.append(name)
                    return result("boom", is_error=True)

            yield Session()

    server = ErrorServer()
    session = shared(server.factory)

    with pytest.raises(Exception, match="reported an error"):
        asyncio.run(call_tool(session, "rag_search", {}))
    assert server.calls == ["rag_search"] and server.opened == 1


def test_a_caller_timeout_cancels_the_call_and_the_session_survives(shared):
    server = FakeServer(delay=5)
    session = shared(server.factory)

    async def impatient():
        await asyncio.wait_for(session.call_tool("slow", {}), timeout=0.2)

    started = time.perf_counter()
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(impatient())
    assert time.perf_counter() - started < 2

    server.delay = 0
    assert asyncio.run(call_tool(session, "fast", {})) == {"results": []}
    assert server.opened == 1, "a timeout is not a transport failure"


def test_calls_run_in_the_callers_context(shared):
    """OpenTelemetry parenting rides on contextvars; they must cross the thread hop."""
    server = FakeServer()
    session = shared(server.factory)

    async def as_request(rid):
        REQUEST_ID.set(rid)
        await call_tool(session, "rag_search", {})

    asyncio.run(as_request("run-a"))
    asyncio.run(as_request("run-b"))

    assert server.seen_request_ids == ["run-a", "run-b"]


def test_a_start_up_failure_reaches_the_caller_and_the_next_call_retries(shared):
    attempts = {"n": 0}

    @asynccontextmanager
    async def flaky_factory():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise FileNotFoundError("python not found")
        yield SimpleNamespace(call_tool=lambda name, args: asyncio.sleep(0, result()))

    session = shared(flaky_factory)

    with pytest.raises(FileNotFoundError):
        session.warm().result(timeout=5)
    assert asyncio.run(call_tool(session, "rag_search", {})) == {"results": []}


def test_warm_opens_the_session_before_the_first_question(shared):
    server = FakeServer()
    session = shared(server.factory)

    session.warm().result(timeout=5)

    assert server.opened == 1 and server.calls == []


def test_swapping_the_factory_replaces_the_session_and_reset_closes_it():
    first, second = FakeServer(), FakeServer()

    a = shared_session(first.factory)
    assert shared_session(first.factory) is a
    asyncio.run(call_tool(a, "x", {}))

    b = shared_session(second.factory)
    assert b is not a and first.closed == 1

    asyncio.run(call_tool(b, "x", {}))
    reset_shared_session()
    assert second.closed == 1


# --- the Researcher, end to end over the real (in-memory) MCP server -------------


def counting(factory):
    count = {"opened": 0}

    @asynccontextmanager
    async def wrapped():
        count["opened"] += 1
        async with factory() as session:
            yield session

    return wrapped, count


def test_research_rounds_reuse_one_session(monkeypatch, isolated_chroma, fake_embed, no_network):
    factory, count = counting(in_memory_mcp_session)
    monkeypatch.setattr(researcher, "mcp_session", factory)

    for _ in range(3):
        researcher.research_node(
            {"question": "q", "subtasks": ["on-call"], "use_rag": True, "use_web": True}
        )

    assert count["opened"] == 1


def test_reuse_can_be_switched_off(monkeypatch, isolated_chroma, fake_embed, no_network):
    monkeypatch.setenv("AGENTDESK_MCP_REUSE", "0")
    factory, count = counting(in_memory_mcp_session)
    monkeypatch.setattr(researcher, "mcp_session", factory)

    for _ in range(2):
        researcher.research_node({"question": "q", "subtasks": ["x"], "use_rag": True})

    assert count["opened"] == 2


def test_the_api_prewarms_the_session_at_startup(monkeypatch):
    import app.main as main

    server = FakeServer()
    monkeypatch.setattr(main, "mcp_session", server.factory)
    monkeypatch.setenv("AGENTDESK_MCP_PREWARM", "1")

    with TestClient(main.app) as client:  # `with` runs the lifespan
        deadline = time.time() + 5
        while server.opened == 0 and time.time() < deadline:
            time.sleep(0.02)
        assert client.get("/health").status_code == 200

    assert server.opened == 1
    assert server.closed == 1, "shutdown closes the warm session"
