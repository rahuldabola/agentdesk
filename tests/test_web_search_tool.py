import json
from unittest.mock import MagicMock, patch

import pytest

from app.mcp.tools import web_search_impl

DDG_HTML = """
<div class="result__body">
  <a class="result__a" href="https://sre.example/oncall">On-call at Scale</a>
  <a class="result__snippet">Weekly rotations are the norm.</a>
</div>
<div class="result__body">
  <a class="result__a" href="https://ops.example/handover">Handover Checklists</a>
  <a class="result__snippet">Write down what is still burning.</a>
</div>
"""


def _response(text="", payload=None):
    resp = MagicMock()
    resp.text = text
    resp.json.return_value = payload or {}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture(autouse=True)
def no_tavily_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


def test_duckduckgo_results_are_parsed_into_structured_json():
    with patch("app.mcp.tools.requests.get", return_value=_response(text=DDG_HTML)):
        payload = json.loads(web_search_impl("on-call", max_results=2))

    assert payload["provider"] == "duckduckgo"
    assert payload["results"] == [
        {
            "title": "On-call at Scale",
            "url": "https://sre.example/oncall",
            "snippet": "Weekly rotations are the norm.",
        },
        {
            "title": "Handover Checklists",
            "url": "https://ops.example/handover",
            "snippet": "Write down what is still burning.",
        },
    ]


def test_max_results_is_honoured():
    with patch("app.mcp.tools.requests.get", return_value=_response(text=DDG_HTML)):
        payload = json.loads(web_search_impl("on-call", max_results=1))

    assert len(payload["results"]) == 1


def test_tavily_is_preferred_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    tavily = _response(
        payload={
            "results": [
                {"title": "T", "url": "https://t.example", "content": "snippet"},
            ]
        }
    )

    with (
        patch("app.mcp.tools.requests.post", return_value=tavily) as post,
        patch("app.mcp.tools.requests.get") as get,
    ):
        payload = json.loads(web_search_impl("q", max_results=3))

    get.assert_not_called()
    assert payload["provider"] == "tavily"
    assert payload["results"][0]["url"] == "https://t.example"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer tvly-test"


def test_a_tavily_failure_actually_falls_back_to_duckduckgo(monkeypatch):
    """The fallback only counts if a provider error does not occupy the result slot."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    with (
        patch("app.mcp.tools.requests.post", side_effect=RuntimeError("tavily is down")),
        patch("app.mcp.tools.requests.get", return_value=_response(text=DDG_HTML)),
    ):
        payload = json.loads(web_search_impl("q", max_results=2))

    assert payload["provider"] == "duckduckgo"
    assert len(payload["results"]) == 2
    assert all("tavily" not in r["title"].lower() for r in payload["results"])


def test_total_failure_returns_an_empty_result_set_with_the_reason():
    with patch("app.mcp.tools.requests.get", side_effect=RuntimeError("blocked")):
        payload = json.loads(web_search_impl("q"))

    assert payload["results"] == []
    assert "blocked" in payload["error"]


def test_unparseable_html_is_reported_rather_than_faked():
    with patch("app.mcp.tools.requests.get", return_value=_response(text="<html></html>")):
        payload = json.loads(web_search_impl("q"))

    assert payload["results"] == []
    assert "no results" in payload["error"]


def test_results_without_a_title_link_are_skipped():
    html = '<div class="result__body"><span>no anchor here</span></div>'
    with patch("app.mcp.tools.requests.get", return_value=_response(text=html)):
        payload = json.loads(web_search_impl("q"))

    assert payload["results"] == []


def test_duckduckgo_redirector_links_are_unwrapped_to_the_real_url():
    from app.mcp.tools import _unwrap_duckduckgo

    wrapped = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fsre.example%2Foncall%3Fa%3D1&rut=abc"

    assert _unwrap_duckduckgo(wrapped) == "https://sre.example/oncall?a=1"
    assert _unwrap_duckduckgo("https://sre.example/direct") == "https://sre.example/direct"
    assert _unwrap_duckduckgo("//cdn.example/x") == "https://cdn.example/x"


def test_wikipedia_is_the_keyless_last_resort(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("AGENTDESK_WIKIPEDIA_FALLBACK", "1")
    api = MagicMock()
    api.json.return_value = {
        "query": {
            "search": [
                {
                    "title": "Site reliability engineering",
                    "snippet": 'Uses <span class="s">SRE</span> teams',
                }
            ]
        }
    }
    with (
        patch("app.mcp.tools._duckduckgo_search", return_value=[]),
        patch("app.mcp.tools.requests.get", return_value=api) as get,
    ):
        payload = json.loads(web_search_impl("sre on-call", 3))

    assert payload["provider"] == "wikipedia"
    [hit] = payload["results"]
    assert hit["title"] == "Site reliability engineering - Wikipedia"
    assert hit["url"] == "https://en.wikipedia.org/wiki/Site_reliability_engineering"
    assert hit["snippet"] == "Uses SRE teams", "markup is stripped from the snippet"
    assert get.call_args.kwargs["params"]["srsearch"] == "sre on-call"


def test_wikipedia_is_not_consulted_when_duckduckgo_works(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("AGENTDESK_WIKIPEDIA_FALLBACK", "1")
    hit = [{"title": "T", "url": "https://x.example", "snippet": "s"}]
    with (
        patch("app.mcp.tools._duckduckgo_search", return_value=hit),
        patch("app.mcp.tools._wikipedia_search") as wiki,
    ):
        payload = json.loads(web_search_impl("q", 3))

    assert payload["provider"] == "duckduckgo"
    wiki.assert_not_called()


def test_all_providers_failing_reports_every_error(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("AGENTDESK_WIKIPEDIA_FALLBACK", "1")
    with (
        patch("app.mcp.tools._duckduckgo_search", return_value=[]),
        patch("app.mcp.tools._wikipedia_search", side_effect=RuntimeError("down")),
    ):
        payload = json.loads(web_search_impl("q", 3))

    assert payload["provider"] == "none" and payload["results"] == []
    assert "duckduckgo" in payload["error"] and "wikipedia: down" in payload["error"]


def test_the_wikipedia_fallback_can_be_switched_off(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("AGENTDESK_WIKIPEDIA_FALLBACK", "0")
    with (
        patch("app.mcp.tools._duckduckgo_search", return_value=[]),
        patch("app.mcp.tools._wikipedia_search") as wiki,
    ):
        payload = json.loads(web_search_impl("q", 3))

    wiki.assert_not_called()
    assert payload["provider"] == "none"
