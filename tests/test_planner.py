from unittest.mock import patch

from app.agents.planner import planner_node


def test_planner_node_returns_plan():
    fake_plan = {
        "subtasks": ["find on-call policy", "find rate limits"],
        "use_rag": True,
        "use_web": False,
    }
    with patch("app.agents.planner.structured_call", return_value=fake_plan):
        state = {"question": "What is our on-call rotation and API rate limit?", "trace": []}
        result = planner_node(state)

    assert result["subtasks"] == fake_plan["subtasks"]
    assert result["use_rag"] is True
    assert result["use_web"] is False
    assert any("planner:" in t for t in result["trace"])
