from unittest.mock import MagicMock, patch

from app.mcp.tools import web_search_impl


def test_web_search_duckduckgo_fallback(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    html = """
    <div class="result__body">
      <a class="result__a" href="https://example.com">Example Title</a>
      <a class="result__snippet">Example snippet text.</a>
    </div>
    """
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.raise_for_status = MagicMock()

    with patch("app.mcp.tools.requests.get", return_value=mock_resp):
        result = web_search_impl("test query", max_results=2)

    assert "Example Title" in result
    assert "example.com" in result


def test_web_search_no_results(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    mock_resp = MagicMock()
    mock_resp.text = "<html><body>no results here</body></html>"
    mock_resp.raise_for_status = MagicMock()

    with patch("app.mcp.tools.requests.get", return_value=mock_resp):
        result = web_search_impl("test query")

    assert result == "No results found."
