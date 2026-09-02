import os

from anthropic import Anthropic

_client = None


def get_client():
    global _client
    if _client is None:
        _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def get_model():
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


def structured_call(system, user_prompt, tool_name, tool_description, input_schema, max_tokens=1024):
    """Force a JSON-schema-shaped response via Claude tool use, instead of parsing free text."""
    client = get_client()
    response = client.messages.create(
        model=get_model(),
        max_tokens=max_tokens,
        system=system,
        tools=[{"name": tool_name, "description": tool_description, "input_schema": input_schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": user_prompt}],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise RuntimeError("Model did not return a tool_use block")


def text_call(system, user_prompt, max_tokens=1500):
    client = get_client()
    response = client.messages.create(
        model=get_model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
