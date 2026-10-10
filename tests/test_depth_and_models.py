"""Depth (quick vs deep) and per-agent model overrides."""

import json
from unittest.mock import patch

import pytest

from app.agents.analyst import analyst_node
from app.agents.critic import critic_node
from app.agents.planner import planner_node
from app.agents.researcher import research_node
from app.agents.synthesizer import synthesizer_node
from app.agents.writer import writer_node
from app.config import agent_model, resolve_depth
from app.graph import _initial_state

# --- depth resolution ---------------------------------------------------------


def test_depth_defaults_to_deep(monkeypatch):
    monkeypatch.delenv("AGENTDESK_DEPTH", raising=False)

    assert resolve_depth(None) == "deep"


def test_a_request_overrides_the_server_default(monkeypatch):
    monkeypatch.setenv("AGENTDESK_DEPTH", "quick")

    assert resolve_depth(None) == "quick"
    assert resolve_depth("deep") == "deep"
    assert resolve_depth(" Quick ") == "quick"


@pytest.mark.parametrize("junk", ["turbo", "", "  "])
def test_an_unknown_depth_falls_back_rather_than_failing(monkeypatch, junk):
    monkeypatch.setenv("AGENTDESK_DEPTH", "nonsense")

    assert resolve_depth(junk) == "deep"


def test_the_initial_state_carries_the_resolved_depth(monkeypatch):
    monkeypatch.delenv("AGENTDESK_DEPTH", raising=False)

    assert _initial_state("a question", "quick")["depth"] == "quick"
    assert _initial_state("a question")["depth"] == "deep"


# --- what quick mode skips ----------------------------------------------------

FACTS = [{"claim": "On-call is weekly.", "kind": "policy", "source_id": "rag:h.md#0"}]


def test_quick_mode_skips_the_synthesizer_llm_call():
    with patch("app.agents.synthesizer.structured_call") as called:
        update = synthesizer_node({"question": "q", "facts": FACTS, "depth": "quick"})

    called.assert_not_called()
    assert update["synthesis"] == {"themes": [], "conflicts": [], "gaps": []}
    assert "skipped in quick mode" in update["trace"][0]["detail"]


def test_deep_mode_still_runs_the_synthesizer():
    plan = {"themes": [{"title": "All", "fact_ids": [0]}], "conflicts": [], "gaps": []}
    with patch("app.agents.synthesizer.structured_call", return_value=plan) as called:
        synthesizer_node({"question": "q", "facts": FACTS, "depth": "deep"})

    called.assert_called_once()


def _web_state(depth):
    return {
        "question": "How do others run on-call?",
        "subtasks": ["typical on-call rotation"],
        "use_rag": False,
        "use_web": True,
        "depth": depth,
    }


@pytest.mark.parametrize(("depth", "pages_asked"), [("deep", 1), ("quick", 0)])
def test_quick_mode_does_not_read_pages(real_mcp_session, monkeypatch, depth, pages_asked):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("AGENTDESK_FETCH_PAGES", "3")
    monkeypatch.setattr(
        "app.mcp.tools._duckduckgo_search",
        lambda q, n, t: [{"title": "T", "url": "https://sre.example/a", "snippet": "S."}],
    )
    asked = []

    def fetch(url, max_chars=None):
        asked.append(url)
        return json.dumps({"url": url, "title": "T", "text": "Body."})

    monkeypatch.setattr("app.mcp.server.fetch_page_impl", fetch)

    research_node(_web_state(depth))

    assert len(asked) == pages_asked


def test_quick_mode_does_not_reword_empty_queries(real_mcp_session, monkeypatch):
    monkeypatch.setenv("AGENTDESK_QUERY_REWRITE", "1")
    state = {
        "question": "q",
        "subtasks": ["nothing matches"],
        "use_rag": True,
        "use_web": False,
        "depth": "quick",
    }
    with (
        patch("app.mcp.tools._rag_search", return_value=[]),
        patch("app.agents.researcher.structured_call") as llm,
    ):
        research_node(state)

    llm.assert_not_called()


# --- per-agent models ---------------------------------------------------------


def test_agent_model_reads_the_per_agent_variable(monkeypatch):
    monkeypatch.setenv("AGENTDESK_MODEL_CRITIC", "big-model")
    monkeypatch.delenv("AGENTDESK_MODEL_WRITER", raising=False)

    assert agent_model("critic") == "big-model"
    assert agent_model("writer") is None


def test_a_blank_override_means_the_default(monkeypatch):
    monkeypatch.setenv("AGENTDESK_MODEL_PLANNER", "")

    assert agent_model("planner") is None


def test_each_agent_passes_its_own_model_override(monkeypatch):
    for agent in ("planner", "analyst", "synthesizer", "critic", "writer"):
        monkeypatch.setenv(f"AGENTDESK_MODEL_{agent.upper()}", f"{agent}-model")

    notes = [{"source_id": "rag:h.md#0", "source_type": "rag", "content": "x"}]
    plan = {"themes": [{"title": "A", "fact_ids": [0]}], "conflicts": [], "gaps": []}
    calls = {
        "planner": ("app.agents.planner.structured_call", {"subtasks": ["a"], "use_rag": True}),
        "analyst": ("app.agents.analyst.structured_call", {"facts": []}),
        "synthesizer": ("app.agents.synthesizer.structured_call", plan),
        "critic": (
            "app.agents.critic.structured_call",
            {"verdict": "pass", "feedback": "", "unsupported_claims": []},
        ),
    }
    state = {"question": "q", "facts": FACTS, "research_notes": notes, "draft_report": "d"}
    nodes = {
        "planner": planner_node,
        "analyst": analyst_node,
        "synthesizer": synthesizer_node,
        "critic": critic_node,
    }

    for agent, (target, payload) in calls.items():
        with patch(target, return_value=payload) as mocked:
            nodes[agent](state)
        assert mocked.call_args.kwargs["model"] == f"{agent}-model", agent

    with patch("app.agents.writer.text_call", return_value="r") as mocked:
        writer_node(state)
    assert mocked.call_args.kwargs["model"] == "writer-model"


def test_text_call_forwards_the_model_to_the_client():
    from app.llm import gemini_client

    class Resp:
        text = "hello"

    with patch.object(gemini_client, "_create", return_value=Resp()) as create:
        gemini_client.text_call("sys", "prompt", model="m")

    assert create.call_args.kwargs["model"] == "m"
