"""Planner: decomposes the question and routes it to the right tools."""

from app.agents.base import node
from app.llm.claude_client import structured_call

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "subtasks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 concrete research subtasks that together answer the question",
        },
        "use_rag": {
            "type": "boolean",
            "description": "true if the internal engineering/API/security docs are likely relevant",
        },
        "use_web": {
            "type": "boolean",
            "description": "true if current or external public information is needed",
        },
    },
    "required": ["subtasks", "use_rag", "use_web"],
}

SYSTEM = (
    "You are the Planner agent in a multi-agent research system. Break the user's question "
    "into 2-4 concrete research subtasks, and decide whether the internal knowledge base "
    "(use_rag) and/or public web search (use_web) are needed to answer it. The internal "
    "knowledge base holds this company's own engineering, API, and security policy docs. "
    "Set both flags when the question compares internal practice against external practice."
)


@node("planner")
def planner_node(state: dict) -> dict:
    data = structured_call(
        system=SYSTEM,
        user_prompt=state["question"],
        tool_name="submit_plan",
        tool_description="Submit the research plan",
        input_schema=PLAN_SCHEMA,
    )
    subtasks = [s for s in data.get("subtasks", []) if s and s.strip()]
    use_rag = bool(data.get("use_rag", True))
    use_web = bool(data.get("use_web", False))

    # A plan with no tools cannot be researched; fall back to the knowledge base.
    if not (use_rag or use_web):
        use_rag = True

    return {
        "subtasks": subtasks or [state["question"]],
        "use_rag": use_rag,
        "use_web": use_web,
        "_detail": f"{len(subtasks)} subtasks, use_rag={use_rag}, use_web={use_web}",
    }
