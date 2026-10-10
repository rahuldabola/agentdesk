"""Planner: decomposes the question and routes it to the right tools."""

from app.agents.base import node
from app.config import agent_model
from app.llm.gemini_client import structured_call

QUESTION_TYPES = ["comparison", "how_to", "risk_compliance", "factual_lookup", "open_ended"]

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "question_type": {
            "type": "string",
            "enum": QUESTION_TYPES,
            "description": (
                "comparison = weighs two or more options or internal vs external practice; "
                "how_to = asks for steps or a procedure; risk_compliance = asks about risks, "
                "policy or obligations; factual_lookup = a single checkable fact; "
                "open_ended = anything else"
            ),
        },
        "success_criteria": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "2-5 things a complete answer MUST contain, each phrased as a checkable "
                "statement (e.g. 'states the internal escalation timeline')"
            ),
        },
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
    "required": ["question_type", "success_criteria", "subtasks", "use_rag", "use_web"],
}

SYSTEM = (
    "You are the Planner agent in a multi-agent research system. Break the user's question "
    "into 2-4 concrete research subtasks, and decide whether the internal knowledge base "
    "(use_rag) and/or public web search (use_web) are needed to answer it. The internal "
    "knowledge base holds this company's own engineering, API, and security policy docs. "
    "Set both flags when the question compares internal practice against external practice. "
    "Before decomposing, classify the question (question_type) and write the success_criteria: "
    "the specific things a complete answer must contain. A later Critic grades the finished "
    "report against these criteria, so make each one concrete and checkable, not generic "
    "('is well written'). Write subtasks so that together they cover every criterion, and "
    "phrase each as a self-contained search query rather than a sentence that depends on the "
    "others."
)


@node("planner")
def planner_node(state: dict) -> dict:
    data = structured_call(
        system=SYSTEM,
        user_prompt=state["question"],
        tool_name="submit_plan",
        tool_description="Submit the research plan",
        input_schema=PLAN_SCHEMA,
        model=agent_model("planner"),
    )
    subtasks = [s for s in data.get("subtasks", []) if s and s.strip()]
    use_rag = bool(data.get("use_rag", True))
    use_web = bool(data.get("use_web", False))

    # A plan with no tools cannot be researched; fall back to the knowledge base.
    if not (use_rag or use_web):
        use_rag = True

    question_type = data.get("question_type")
    if question_type not in QUESTION_TYPES:
        question_type = "open_ended"
    criteria = [c.strip() for c in data.get("success_criteria") or [] if c and c.strip()]

    return {
        "question_type": question_type,
        "success_criteria": criteria,
        "subtasks": subtasks or [state["question"]],
        "use_rag": use_rag,
        "use_web": use_web,
        "_detail": (
            f"{question_type}: {len(subtasks)} subtasks, {len(criteria)} criteria, "
            f"use_rag={use_rag}, use_web={use_web}"
        ),
    }
