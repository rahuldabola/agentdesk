from app.llm.claude_client import structured_call

FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["claim", "source_id"],
            },
        }
    },
    "required": ["facts"],
}

SYSTEM = (
    "You are the Analyst agent. Given raw research notes (each tagged with a source_id), "
    "extract the distinct factual claims relevant to the question. Every fact must cite the "
    "exact source_id it came from. Do not invent facts that are not present in the notes."
)


def analyst_node(state):
    notes = state.get("research_notes", [])
    trace = state.get("trace", [])

    if not notes:
        trace.append("analyst: no research notes available, skipping")
        return {"facts": [], "trace": trace}

    notes_text = "\n\n".join(f"[{n['source_id']}] {n['content']}" for n in notes)
    user_prompt = f"Question: {state['question']}\n\nResearch notes:\n{notes_text}"

    data = structured_call(
        system=SYSTEM,
        user_prompt=user_prompt,
        tool_name="submit_facts",
        tool_description="Submit extracted facts with source citations",
        input_schema=FACTS_SCHEMA,
    )

    trace.append(f"analyst: extracted {len(data['facts'])} facts")
    return {"facts": data["facts"], "trace": trace}
