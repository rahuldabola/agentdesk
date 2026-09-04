"""Retry policy and structured-output handling for the Claude client."""

import httpx
import pytest
from anthropic import APIConnectionError, APIStatusError, BadRequestError, RateLimitError

import app.llm.claude_client as claude_client
from app.errors import ConfigurationError, LLMError
from app.util.retry import retry_call


def _status_error(code):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(code, request=request)
    if code == 429:
        return RateLimitError("rate limited", response=response, body=None)
    if code == 400:
        return BadRequestError("bad request", response=response, body=None)
    return APIStatusError("server error", response=response, body=None)


def test_retry_call_returns_on_first_success():
    calls = []
    result = retry_call(
        lambda: calls.append(1) or "ok",
        attempts=3,
        base_delay=0,
        retryable=lambda e: True,
        description="t",
        sleep=lambda d: None,
    )

    assert result == "ok"
    assert len(calls) == 1


def test_retry_call_retries_then_succeeds():
    attempts = {"n": 0}
    delays = []

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = retry_call(
        flaky,
        attempts=5,
        base_delay=1.0,
        retryable=lambda e: True,
        description="t",
        sleep=delays.append,
    )

    assert result == "ok"
    assert attempts["n"] == 3
    assert len(delays) == 2
    assert delays[1] > delays[0], "backoff must grow between attempts"


def test_retry_call_gives_up_after_the_attempt_budget():
    attempts = {"n": 0}

    def always_fails():
        attempts["n"] += 1
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        retry_call(
            always_fails,
            attempts=3,
            base_delay=0,
            retryable=lambda e: True,
            description="t",
            sleep=lambda d: None,
        )

    assert attempts["n"] == 3


def test_retry_call_does_not_retry_what_it_cannot_fix():
    attempts = {"n": 0}

    def bad_request():
        attempts["n"] += 1
        raise ValueError("your fault")

    with pytest.raises(ValueError):
        retry_call(
            bad_request,
            attempts=5,
            base_delay=0,
            retryable=lambda e: False,
            description="t",
            sleep=lambda d: None,
        )

    assert attempts["n"] == 1, "a non-retryable error must fail immediately"


@pytest.mark.parametrize(
    "exc,expected",
    [
        (APIConnectionError(request=httpx.Request("POST", "https://x")), True),
        (_status_error(429), True),
        (_status_error(500), True),
        (_status_error(503), True),
        (_status_error(400), False),
        (ValueError("unrelated"), False),
    ],
)
def test_only_transient_upstream_failures_are_retryable(exc, expected):
    assert claude_client.is_retryable(exc) is expected


def test_a_missing_api_key_is_a_configuration_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    claude_client.reset_client()

    with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
        claude_client.get_client()


def test_structured_call_returns_the_tool_input(monkeypatch):
    monkeypatch.setattr(
        claude_client,
        "_create",
        lambda **kw: _FakeResponse(
            [
                _Block("text", text="thinking..."),
                _Block("tool_use", input={"verdict": "pass"}),
            ]
        ),
    )

    result = claude_client.structured_call("s", "u", "submit", "d", {"type": "object"})

    assert result == {"verdict": "pass"}


def test_structured_call_raises_when_the_forced_tool_never_arrives(monkeypatch):
    monkeypatch.setattr(
        claude_client,
        "_create",
        lambda **kw: _FakeResponse(
            [
                _Block("text", text="I would rather not."),
            ]
        ),
    )

    with pytest.raises(LLMError, match="no tool_use block"):
        claude_client.structured_call("s", "u", "submit", "d", {"type": "object"})


def test_text_call_rejects_an_empty_completion(monkeypatch):
    monkeypatch.setattr(
        claude_client,
        "_create",
        lambda **kw: _FakeResponse(
            [
                _Block("text", text="   "),
            ]
        ),
    )

    with pytest.raises(LLMError, match="empty response"):
        claude_client.text_call("s", "u")


class _Block:
    def __init__(self, type_, **kwargs):
        self.type = type_
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeResponse:
    def __init__(self, content):
        self.content = content
        self.stop_reason = "end_turn"
