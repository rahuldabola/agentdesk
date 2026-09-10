"""Gemini access: forced-schema structured calls, free-text calls, and retries.

One `genai.Client` backs both chat/tool-calling here and the embeddings calls in
`app/rag/ingest.py` - a single provider, a single `GEMINI_API_KEY`.
"""

import logging
import os

import httpx
from google import genai
from google.genai import errors, types

from app.config import get_settings
from app.errors import ConfigurationError, LLMError
from app.util.retry import retry_call

log = logging.getLogger("agentdesk.llm")

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ConfigurationError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        settings = get_settings()
        _client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=int(settings.llm_timeout * 1000)),
        )
    return _client


def reset_client() -> None:
    """Drop the cached client so a changed key/timeout takes effect (used by tests)."""
    global _client
    _client = None


def is_retryable(exc: BaseException) -> bool:
    """Transient upstream failures only - never a 4xx we caused ourselves."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True
    if isinstance(exc, errors.APIError):
        return exc.code == 429 or exc.code >= 500
    return False


def retry_delay_hint(exc: BaseException) -> float | None:
    """A 429's own `RetryInfo.retryDelay`, capped so one hint can't stall a run.

    Gemini tells us exactly how long a quota needs to recover; retrying sooner
    just burns another attempt on the same 429.
    """
    if not (isinstance(exc, errors.APIError) and exc.code == 429):
        return None
    try:
        for detail in exc.details["error"]["details"]:
            if str(detail.get("@type", "")).endswith("RetryInfo"):
                return min(float(detail["retryDelay"].rstrip("s")), 30.0)
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return None


def _create(
    *,
    system: str,
    contents: str,
    max_tokens: int,
    tools: list | None = None,
    tool_config: "types.ToolConfig | None" = None,
) -> "types.GenerateContentResponse":
    settings = get_settings()
    client = get_client()
    try:
        return retry_call(
            lambda: client.models.generate_content(
                model=settings.gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    systemInstruction=system,
                    maxOutputTokens=max_tokens,
                    tools=tools,
                    toolConfig=tool_config,
                ),
            ),
            attempts=settings.llm_max_attempts,
            base_delay=settings.llm_backoff_base,
            retryable=is_retryable,
            delay_hint=retry_delay_hint,
            description="gemini.generate_content",
        )
    except errors.APIError as exc:
        raise LLMError(f"Gemini request failed: {type(exc).__name__}: {exc}") from exc


def structured_call(
    system: str,
    user_prompt: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    max_tokens: int = 1024,
) -> dict:
    """Force a JSON-schema-shaped response via function calling, instead of parsing free text."""
    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=tool_name,
                description=tool_description,
                parametersJsonSchema=input_schema,
            )
        ]
    )
    tool_config = types.ToolConfig(
        functionCallingConfig=types.FunctionCallingConfig(
            mode=types.FunctionCallingConfigMode.ANY,
            allowedFunctionNames=[tool_name],
        )
    )
    response = _create(
        system=system,
        contents=user_prompt,
        max_tokens=max_tokens,
        tools=[tool],
        tool_config=tool_config,
    )
    for call in response.function_calls or []:
        if call.name == tool_name:
            return call.args or {}
    raise LLMError(
        f"Gemini returned no function call for '{tool_name}' despite a forced tool_config "
        f"(finish_reason={_finish_reason(response)})."
    )


def text_call(system: str, user_prompt: str, max_tokens: int = 1500) -> str:
    response = _create(system=system, contents=user_prompt, max_tokens=max_tokens)
    text = response.text or ""
    if not text.strip():
        raise LLMError("Gemini returned an empty response.")
    return text


def _finish_reason(response) -> str:
    try:
        return str(response.candidates[0].finish_reason)
    except (AttributeError, IndexError):
        return "unknown"
