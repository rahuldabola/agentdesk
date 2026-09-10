"""Retry policy and structured-output handling for the Gemini client."""

import httpx
import pytest
from google.genai import errors as genai_errors

import app.llm.gemini_client as gemini_client
from app.errors import ConfigurationError, LLMError
from app.util.retry import retry_call


def _api_error(code):
    cls = genai_errors.ClientError if code < 500 else genai_errors.ServerError
    return cls(code, {"error": {"message": "boom", "status": "ERROR"}})


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


def test_retry_call_uses_the_delay_hint_over_the_computed_backoff():
    delays = []

    def flaky():
        if len(delays) < 1:
            raise RuntimeError("transient")
        return "ok"

    result = retry_call(
        flaky,
        attempts=3,
        base_delay=10.0,  # would produce a much longer computed delay
        retryable=lambda e: True,
        description="t",
        sleep=delays.append,
        delay_hint=lambda e: 0.05,
    )

    assert result == "ok"
    assert delays == [0.05]


@pytest.mark.parametrize(
    "exc,expected",
    [
        (httpx.ConnectError("refused"), True),
        (httpx.TimeoutException("timed out"), True),
        (_api_error(429), True),
        (_api_error(500), True),
        (_api_error(503), True),
        (_api_error(400), False),
        (ValueError("unrelated"), False),
    ],
)
def test_only_transient_upstream_failures_are_retryable(exc, expected):
    assert gemini_client.is_retryable(exc) is expected


def test_retry_delay_hint_reads_a_429s_own_retry_info():
    exc = genai_errors.ClientError(
        429,
        {
            "error": {
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "2.5s"}
                ]
            }
        },
    )
    assert gemini_client.retry_delay_hint(exc) == 2.5


def test_retry_delay_hint_caps_an_unreasonably_long_wait():
    exc = genai_errors.ClientError(
        429,
        {
            "error": {
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "120s"}
                ]
            }
        },
    )
    assert gemini_client.retry_delay_hint(exc) == 30.0


@pytest.mark.parametrize(
    "exc",
    [
        _api_error(500),
        _api_error(429),  # no RetryInfo in the details
        ValueError("not even an APIError"),
    ],
)
def test_retry_delay_hint_is_none_when_there_is_nothing_to_read(exc):
    assert gemini_client.retry_delay_hint(exc) is None


def test_a_missing_api_key_is_a_configuration_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gemini_client.reset_client()

    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        gemini_client.get_client()


def test_structured_call_returns_the_matching_function_call_args(monkeypatch):
    monkeypatch.setattr(
        gemini_client,
        "_create",
        lambda **kw: _FakeResponse(function_calls=[_Call("submit", {"verdict": "pass"})]),
    )

    result = gemini_client.structured_call("s", "u", "submit", "d", {"type": "object"})

    assert result == {"verdict": "pass"}


def test_structured_call_raises_when_the_forced_function_never_arrives(monkeypatch):
    monkeypatch.setattr(
        gemini_client,
        "_create",
        lambda **kw: _FakeResponse(function_calls=None, candidates=[]),
    )

    with pytest.raises(LLMError, match="no function call"):
        gemini_client.structured_call("s", "u", "submit", "d", {"type": "object"})


def test_text_call_rejects_an_empty_completion(monkeypatch):
    monkeypatch.setattr(gemini_client, "_create", lambda **kw: _FakeResponse(text="   "))

    with pytest.raises(LLMError, match="empty response"):
        gemini_client.text_call("s", "u")


class _Call:
    def __init__(self, name, args):
        self.name = name
        self.args = args


class _FakeResponse:
    def __init__(self, function_calls=None, text=None, candidates=()):
        self.function_calls = function_calls
        self.text = text
        self.candidates = list(candidates)
