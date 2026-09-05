from unittest.mock import Mock, patch

import pytest

from app.llm.claude_client import LLMQuotaError, structured_call


def test_gemini_quota_error_is_actionable():
    provider_error = RuntimeError("RESOURCE_EXHAUSTED")
    provider_error.status_code = 429
    client = Mock()
    client.models.generate_content.side_effect = provider_error

    with patch.dict(
        "os.environ",
        {"AI_PROVIDER": "gemini", "GEMINI_MODEL": "gemini-flash-latest"},
        clear=False,
    ), patch("app.llm.claude_client.get_client", return_value=client):
        with pytest.raises(LLMQuotaError, match="Gemini quota.*exhausted"):
            structured_call("system", "question", "submit_plan", "plan", {})