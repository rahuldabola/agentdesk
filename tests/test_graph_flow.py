from unittest.mock import patch

from app.graph import build_graph


def test_graph_flow_pass_first_try():
    with patch(
        "app.graph.planner_node",
        return_value={"subtasks": ["s1"], "use_rag": True, "use_web": False, "trace": ["plan"]},
    ), patch(
        "app.graph.research_node", return_value={"research_notes": [], "trace": ["research"]}
    ), patch(
        "app.graph.analyst_node", return_value={"facts": [], "trace": ["analyze"]}
    ), patch(
        "app.graph.writer_node",
        return_value={"draft_report": "Report v1", "citations": [], "trace": ["write"]},
    ), patch(
        "app.graph.critic_node",
        return_value={"critic_verdict": "pass", "final_report": "Report v1", "trace": ["critique"]},
    ):
        graph = build_graph()
        result = graph.invoke({"question": "q", "revision_count": 0, "trace": []})

    assert result["final_report"] == "Report v1"


def test_graph_flow_one_revision_then_pass():
    critic_calls = {"n": 0}

    def fake_critic(state):
        critic_calls["n"] += 1
        if critic_calls["n"] == 1:
            return {"critic_verdict": "revise", "critic_feedback": "add more detail", "revision_count": 1, "trace": []}
        return {"critic_verdict": "pass", "final_report": state["draft_report"], "trace": []}

    def fake_writer(state):
        return {"draft_report": f"Report v{state.get('revision_count', 0) + 1}", "citations": [], "trace": []}

    with patch(
        "app.graph.planner_node",
        return_value={"subtasks": ["s1"], "use_rag": True, "use_web": False, "trace": []},
    ), patch(
        "app.graph.research_node", return_value={"research_notes": [], "trace": []}
    ), patch(
        "app.graph.analyst_node", return_value={"facts": [], "trace": []}
    ), patch(
        "app.graph.writer_node", side_effect=fake_writer
    ), patch(
        "app.graph.critic_node", side_effect=fake_critic
    ):
        graph = build_graph()
        result = graph.invoke({"question": "q", "revision_count": 0, "trace": []})

    assert critic_calls["n"] == 2
    assert result["final_report"] == "Report v2"
