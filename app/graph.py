from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.analyst import analyst_node
from app.agents.critic import critic_node
from app.agents.planner import planner_node
from app.agents.researcher import research_node
from app.agents.writer import writer_node


class AgentState(TypedDict, total=False):
    question: str
    subtasks: list
    use_rag: bool
    use_web: bool
    research_notes: list
    facts: list
    draft_report: str
    citations: list
    critic_verdict: str
    critic_feedback: str
    revision_count: int
    final_report: str
    trace: list


def route_after_critic(state):
    return "done" if state.get("final_report") is not None else "revise"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("plan", planner_node)
    graph.add_node("research", research_node)
    graph.add_node("analyze", analyst_node)
    graph.add_node("write", writer_node)
    graph.add_node("critique", critic_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "research")
    graph.add_edge("research", "analyze")
    graph.add_edge("analyze", "write")
    graph.add_edge("write", "critique")
    graph.add_conditional_edges("critique", route_after_critic, {"revise": "write", "done": END})

    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def run_agentdesk(question: str) -> dict:
    graph = get_graph()
    initial_state = {"question": question, "revision_count": 0, "trace": []}
    return graph.invoke(initial_state)
