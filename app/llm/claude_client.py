import os

_client = None


class LLMQuotaError(RuntimeError):
    """Raised when the configured model provider has exhausted its quota."""


def _provider():
    return os.environ.get("AI_PROVIDER", "anthropic").lower()


def get_client():
    global _client
    if _client is None:
        if _provider() == "gemini":
            from google import genai

            _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        else:
            from anthropic import Anthropic

            _client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def get_model():
    if _provider() == "gemini":
        return os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")


def _generate_gemini(client, **kwargs):
    try:
        return client.models.generate_content(**kwargs)
    except Exception as exc:
        if getattr(exc, "status_code", None) == 429:
            raise LLMQuotaError(
                f"The Gemini quota for model {get_model()} is exhausted. "
                "Check billing or wait for the quota window to reset."
            ) from exc
        raise


def structured_call(system, user_prompt, tool_name, tool_description, input_schema, max_tokens=1024):
    """Force a JSON-schema-shaped response via tool/function calling, instead of parsing free text."""
    client = get_client()

    if _provider() == "gemini":
        from google.genai import types

        response = _generate_gemini(
            client,
            model=get_model(),
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                tools=[
                    types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration(
                                name=tool_name, description=tool_description, parameters=input_schema
                            )
                        ]
                    )
                ],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode="ANY", allowed_function_names=[tool_name]
                    )
                ),
            ),
        )
        for part in response.candidates[0].content.parts:
            if part.function_call:
                return dict(part.function_call.args)
        raise RuntimeError("Model did not return a function_call part")

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

    if _provider() == "gemini":
        from google.genai import types

        response = _generate_gemini(
            client,
            model=get_model(),
            contents=user_prompt,
            config=types.GenerateContentConfig(system_instruction=system, max_output_tokens=max_tokens),
        )
        return response.text

    response = client.messages.create(
        model=get_model(),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
