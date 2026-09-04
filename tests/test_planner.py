from unittest.mock import patch

from app.agents.planner import planner_node


def _plan(**data):
    return patch("app.agents.planner.structured_call", return_value=data)


def test_planner_passes_through_a_valid_plan():
    with _plan(subtasks=["a", "b"], use_rag=True, use_web=False):
        update = planner_node({"question": "What is our on-call rotation?"})

    assert update["subtasks"] == ["a", "b"]
    assert update["use_rag"] is True and update["use_web"] is False
    assert update["trace"][0]["node"] == "planner"
    assert update["trace"][0]["elapsed_ms"] >= 0


def test_planner_drops_blank_subtasks():
    with _plan(subtasks=["real", "  ", ""], use_rag=True, use_web=True):
        update = planner_node({"question": "q"})

    assert update["subtasks"] == ["real"]


def test_planner_falls_back_to_the_question_when_no_subtasks_come_back():
    with _plan(subtasks=[], use_rag=True, use_web=False):
        update = planner_node({"question": "the original question"})

    assert update["subtasks"] == ["the original question"]


def test_planner_never_returns_a_plan_with_no_tools():
    """A toolless plan would make the Researcher a no-op and the report empty."""
    with _plan(subtasks=["a"], use_rag=False, use_web=False):
        update = planner_node({"question": "q"})

    assert update["use_rag"] is True
