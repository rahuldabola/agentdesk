"""Claude access: forced-schema structured calls, free-text calls, and retries."""

import logging
import os

import anthropic
from anthropic import Anthropic

from app.config import get_settings
from app.errors import ConfigurationError, LLMError
from app.util.retry import retry_call

log = logging.getLogger("agentdesk.llm")

_client: Anthropic | None = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ConfigurationError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        _client = Anthropic(api_key=key, timeout=get_settings().llm_timeout)
    return _client


def reset_client() -> None:
    """Drop the cached client so a changed key/timeout takes effect (used by tests)."""
    global _client
    _client = None


def is_retryable(exc: BaseException) -> bool:
    """Transient upstream failures only - never a 4xx we caused ourselves."""
    if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
        return True
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code >= 500
    return False


def _create(**kwargs):
    settings = get_settings()
    client = get_client()
    try:
        return retry_call(
            lambda: client.messages.create(model=settings.anthropic_model, **kwargs),
            attempts=settings.llm_max_attempts,
            base_delay=settings.llm_backoff_base,
            retryable=is_retryable,
            description="anthropic.messages.create",
        )
    except anthropic.APIError as exc:
        raise LLMError(f"Claude request failed: {type(exc).__name__}: {exc}") from exc


def structured_call(
    system: str,
    user_prompt: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    max_tokens: int = 1024,
) -> dict:
    """Force a JSON-schema-shaped response via tool use, instead of parsing free text."""
    response = _create(
        max_tokens=max_tokens,
        system=system,
        tools=[{"name": tool_name, "description": tool_description, "input_schema": input_schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user_prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise LLMError(
        f"Claude returned no tool_use block for '{tool_name}' despite a forced tool_choice "
        f"(stop_reason={getattr(response, 'stop_reason', 'unknown')})."
    )


def text_call(system: str, user_prompt: str, max_tokens: int = 1500) -> str:
    response = _create(
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        raise LLMError("Claude returned an empty response.")
    return text
