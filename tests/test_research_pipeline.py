"""End-to-end test of the path that carries retrieved text into the agents.

This is the seam the rest of the suite used to step over: unit tests proved
`rag_search_impl` returned the right thing, and the graph test mocked the
Researcher entirely, so nothing checked that a retrieved passage survives the
trip from Chroma -> MCP tool -> JSON -> Researcher -> notes.

An earlier version serialised passages to `[source_id] text` and reparsed them
by splitting on blank lines, which silently truncated every markdown passage at
its first blank line. `test_multi_paragraph_passage_survives_the_tool_round_trip`
is the regression guard for exactly that.
"""

import json

import pytest

import app.rag.ingest as ingest_module
from app.agents.researcher import assemble_notes, index_web_sources, research_node
from app.mcp.tools import rag_search_impl

MULTI_PARAGRAPH_DOC = """# Engineering Handbook

## On-call Rotation

On-call is a weekly rotation starting Monday at 09:00 UTC. The primary
acknowledges pages within 5 minutes.

## Escalation

Unacknowledged pages escalate to the secondary after 10 minutes, then to the
engineering manager.
"""


@pytest.fixture
def ingested_handbook(tmp_path, isolated_chroma, fake_embed):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "handbook.md").write_text(MULTI_PARAGRAPH_DOC, encoding="utf-8")
    assert ingest_module.ingest_docs(docs_dir=str(docs)) > 0
    return docs


def test_rag_tool_returns_the_whole_passage_as_json(ingested_handbook):
    payload = json.loads(rag_search_impl("on-call rotation escalation", k=4))

    assert payload["provider"] == "chroma"
    assert payload["results"], "expected at least one chunk above the relevance floor"
    joined = " ".join(r["content"] for r in payload["results"])
    assert "Escalation" in joined
    assert "engineering manager" in joined


def test_multi_paragraph_passage_survives_the_tool_round_trip(
    ingested_handbook, real_mcp_session, no_network
):
    state = {
        "question": "What is the on-call rotation?",
        "subtasks": ["on-call rotation escalation policy"],
        "use_rag": True,
        "use_web": False,
    }

    update = research_node(state)
    notes = update["research_notes"]

    assert notes, "the Researcher produced no notes from a populated knowledge base"
    body = " ".join(n["content"] for n in notes)

    # Content from after the first, second and third blank lines of the source
    # document must all be present - not just the leading heading.
    assert "weekly rotation" in body
    assert "Escalation" in body
    assert "engineering manager" in body

    # And the passage must arrive substantially intact, not truncated.
    assert len(body) > 0.6 * len(MULTI_PARAGRAPH_DOC), (
        f"only {len(body)} of {len(MULTI_PARAGRAPH_DOC)} chars reached the agents"
    )


def test_notes_are_registered_against_resolvable_sources(
    ingested_handbook, real_mcp_session, no_network
):
    update = research_node(
        {
            "question": "on-call?",
            "subtasks": ["on-call rotation"],
            "use_rag": True,
            "use_web": False,
        }
    )

    sources = update["sources"]
    for note in update["research_notes"]:
        assert note["source_id"] in sources
        meta = sources[note["source_id"]]
        assert meta["type"] == "rag"
        assert meta["file"] == "handbook.md"
        assert note["source_id"].startswith("rag:handbook.md#")


def test_web_results_get_short_stable_citation_ids(real_mcp_session, monkeypatch):
    """Citations must be readable: [web:1], not [web:<the whole subtask>#0]."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(
        "app.mcp.tools._duckduckgo_search",
        lambda query, max_results, timeout: [
            {"title": "SRE Book", "url": "https://sre.example/oncall", "snippet": "Rotations."},
            {"title": "Dupe", "url": "https://sre.example/oncall", "snippet": "Same page."},
        ],
    )

    update = research_node(
        {
            "question": "How do other teams run on-call?",
            "subtasks": ["typical SRE on-call rotation", "on-call handover practice"],
            "use_rag": False,
            "use_web": True,
        }
    )

    ids = {n["source_id"] for n in update["research_notes"]}
    assert ids == {"web:1"}, f"the same URL across subtasks must collapse to one id, got {ids}"
    assert update["sources"]["web:1"]["url"] == "https://sre.example/oncall"


def test_tool_failure_degrades_instead_of_crashing(real_mcp_session, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    def _explode(*args, **kwargs):
        raise RuntimeError("network is down")

    monkeypatch.setattr("app.mcp.tools._duckduckgo_search", _explode)

    update = research_node(
        {
            "question": "q",
            "subtasks": ["s"],
            "use_rag": False,
            "use_web": True,
        }
    )

    assert update["research_notes"] == []
    assert "degraded" in update["trace"][0]["detail"]


# --- the note/citation mapping, tested directly on payload fixtures -----------


def test_assemble_notes_maps_rag_payloads_onto_citable_sources():
    sources: dict = {}
    pairs = [
        (
            "rag",
            "subtask",
            {
                "results": [
                    {
                        "doc_id": "h.md#2",
                        "file": "h.md",
                        "chunk_index": 2,
                        "score": 0.8,
                        "content": "First para.\n\nSecond para.",
                    },
                ]
            },
        )
    ]

    notes, failures = assemble_notes(pairs, sources, {})

    assert failures == []
    assert notes == [
        {
            "source_id": "rag:h.md#2",
            "source_type": "rag",
            "content": "First para.\n\nSecond para.",
        }
    ]
    assert sources["rag:h.md#2"]["file"] == "h.md"


def test_assemble_notes_skips_empty_passages():
    notes, _ = assemble_notes(
        [("rag", "s", {"results": [{"doc_id": "h.md#0", "content": "   "}]})], {}, {}
    )

    assert notes == []


def test_assemble_notes_numbers_distinct_urls_and_reuses_repeats():
    sources: dict = {}
    url_index: dict = {}
    pairs = [
        (
            "web",
            "s1",
            {
                "results": [
                    {"title": "A", "url": "https://a.example", "snippet": "one"},
                    {"title": "B", "url": "https://b.example", "snippet": "two"},
                ]
            },
        ),
        (
            "web",
            "s2",
            {
                "results": [
                    {"title": "A again", "url": "https://a.example", "snippet": "three"},
                ]
            },
        ),
    ]

    notes, _ = assemble_notes(pairs, sources, url_index)

    assert [n["source_id"] for n in notes] == ["web:1", "web:2", "web:1"]
    assert sources["web:2"]["url"] == "https://b.example"


def test_assemble_notes_records_a_provider_error_without_losing_other_results():
    pairs = [
        ("web", "s", {"results": [], "error": "duckduckgo: blocked"}),
        ("rag", "s", {"results": [{"doc_id": "h.md#0", "content": "kept"}]}),
    ]

    notes, failures = assemble_notes(pairs, {}, {})

    assert [n["content"] for n in notes] == ["kept"]
    assert failures == ["web: duckduckgo: blocked"]


def test_index_web_sources_lets_a_follow_up_round_reuse_ids():
    sources = {
        "web:1": {"source_id": "web:1", "type": "web", "url": "https://a.example"},
        "rag:h.md#0": {"source_id": "rag:h.md#0", "type": "rag"},
    }

    assert index_web_sources(sources) == {"https://a.example": "web:1"}
