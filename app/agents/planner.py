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
    "(use_rag) and/or public web search (use_web) are needed to answer it."
)


def planner_node(state):
    data = structured_call(
        system=SYSTEM,
        user_prompt=state["question"],
        tool_name="submit_plan",
        tool_description="Submit the research plan",
        input_schema=PLAN_SCHEMA,
    )
    trace = state.get("trace", [])
    trace.append(f"planner: {len(data['subtasks'])} subtasks, use_rag={data['use_rag']}, use_web={data['use_web']}")
    return {
        "subtasks": data["subtasks"],
        "use_rag": data["use_rag"],
        "use_web": data["use_web"],
        "trace": trace,
    }
