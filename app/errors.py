"""Typed errors so the API can distinguish a bad config from a flaky upstream."""


class AgentDeskError(Exception):
    """Base class for every error this system raises deliberately."""


class ConfigurationError(AgentDeskError):
    """A required key or setting is missing or malformed. Not retryable."""


class LLMError(AgentDeskError):
    """The LLM provider failed, or returned something unusable."""


class RetrievalError(AgentDeskError):
    """The vector store could not be queried."""


class ToolError(AgentDeskError):
    """An MCP tool call failed, or returned a payload we could not parse."""
