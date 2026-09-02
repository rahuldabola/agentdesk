from app.llm.claude_client import structured_call

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "revise"]},
        "feedback": {"type": "string"},
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "feedback", "unsupported_claims"],
}

SYSTEM = (
    "You are the Critic agent. Check the draft report against the provided facts. Flag any "
    "claim in the report that is NOT supported by the facts list (a hallucination), and any "
    "citation that references a source_id not present in the facts. Return verdict='revise' "
    "if there are unsupported claims or missing citations, otherwise 'pass'."
)

MAX_REVISIONS = 2


def critic_node(state):
    facts = state.get("facts", [])
    facts_text = "\n".join(f"- {f['claim']} [{f['source_id']}]" for f in facts)
    user_prompt = (
        f"Question: {state['question']}\n\nFacts:\n{facts_text or '(none)'}\n\n"
        f"Draft report:\n{state.get('draft_report', '')}"
    )

    data = structured_call(
        system=SYSTEM,
        user_prompt=user_prompt,
        tool_name="submit_verdict",
        tool_description="Submit the critique verdict",
        input_schema=VERDICT_SCHEMA,
    )

    trace = state.get("trace", [])
    trace.append(f"critic: verdict={data['verdict']}")

    revision_count = state.get("revision_count", 0)
    result = {
        "critic_verdict": data["verdict"],
        "critic_feedback": data["feedback"],
        "trace": trace,
    }

    if data["verdict"] == "revise" and revision_count < MAX_REVISIONS:
        result["revision_count"] = revision_count + 1
    else:
        result["final_report"] = state.get("draft_report", "")

    return result
