from unittest.mock import patch

from app.agents.synthesizer import build_synthesis, source_trust, synthesizer_node

FACTS = [
    {"claim": "On-call is weekly.", "kind": "policy", "source_id": "rag:h.md#0"},
    {"claim": "Rotations of 1-2 weeks are common.", "kind": "claim", "source_id": "web:1"},
    {"claim": "Pages ack within 5 minutes.", "kind": "number", "source_id": "rag:h.md#1"},
]


def test_source_trust_separates_internal_documents_from_the_web():
    assert source_trust("rag:handbook.md#2") == "internal"
    assert source_trust("web:1") == "external"


def test_build_synthesis_keeps_valid_themes_and_conflicts():
    data = {
        "themes": [{"title": "Rotation", "fact_ids": [0, 1]}, {"title": "Paging", "fact_ids": [2]}],
        "conflicts": [{"description": "weekly vs 1-2 weeks", "fact_ids": [0, 1]}],
        "gaps": ["escalation path", "  "],
    }
    out = build_synthesis(data, 3)

    assert out["themes"] == data["themes"]
    assert out["conflicts"] == data["conflicts"]
    assert out["gaps"] == ["escalation path"]


def test_build_synthesis_never_loses_a_fact_the_model_forgot():
    out = build_synthesis({"themes": [{"title": "A", "fact_ids": [0]}]}, 3)

    assert out["themes"][-1] == {"title": "Other findings", "fact_ids": [1, 2]}


def test_build_synthesis_discards_bad_indices_and_duplicates():
    data = {
        "themes": [
            {"title": "A", "fact_ids": [0, 0, 9, -1, True]},
            {"title": "B", "fact_ids": [0, 1]},
            {"title": "", "fact_ids": [2]},
        ],
        "conflicts": [{"description": "x", "fact_ids": [1, 7]}],
    }
    out = build_synthesis(data, 3)

    assert out["themes"][0] == {"title": "A", "fact_ids": [0]}
    assert out["themes"][1] == {"title": "B", "fact_ids": [1]}
    assert out["themes"][2]["fact_ids"] == [2]  # unplaced because its title was blank
    assert out["conflicts"] == [{"description": "x", "fact_ids": [1]}]


def test_build_synthesis_with_an_empty_plan_still_places_every_fact():
    out = build_synthesis({}, 2)

    assert out["themes"] == [{"title": "Findings", "fact_ids": [0, 1]}]


def test_synthesizer_skips_the_llm_call_when_there_are_no_facts():
    with patch("app.agents.synthesizer.structured_call") as called:
        update = synthesizer_node({"question": "q", "facts": []})

    called.assert_not_called()
    assert update["synthesis"] == {"themes": [], "conflicts": [], "gaps": []}


def test_synthesizer_numbers_facts_and_labels_their_trust_for_the_model():
    plan = {"themes": [{"title": "All", "fact_ids": [0, 1, 2]}], "conflicts": [], "gaps": []}
    with patch("app.agents.synthesizer.structured_call", return_value=plan) as mocked:
        update = synthesizer_node(
            {
                "question": "q",
                "question_type": "comparison",
                "success_criteria": ["c1"],
                "facts": FACTS,
            }
        )

    prompt = mocked.call_args.kwargs["user_prompt"]
    assert "0. (internal, policy) On-call is weekly." in prompt
    assert "1. (external, claim) Rotations of 1-2 weeks are common." in prompt
    assert "- c1" in prompt
    assert update["synthesis"]["themes"][0]["fact_ids"] == [0, 1, 2]
