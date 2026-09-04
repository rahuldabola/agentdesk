"""Analyst: turns raw passages into atomic claims, each bound to a source_id."""

from app.agents.base import node
from app.llm.claude_client import structured_call

FACTS_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string", "description": "One self-contained factual claim"},
                    "source_id": {
                        "type": "string",
                        "description": "The exact source_id of the note this claim came from",
                    },
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
    "exact source_id it came from, copied verbatim. Do not invent facts that are not present "
    "in the notes, and do not merge claims from two sources into one fact."
)

MAX_NOTE_CHARS = 2000


@node("analyst")
def analyst_node(state: dict) -> dict:
    notes = state.get("research_notes", [])
    if not notes:
        return {"facts": [], "_detail": "no research notes available, nothing to extract"}

    notes_text = "\n\n".join(f"[{n['source_id']}] {n['content'][:MAX_NOTE_CHARS]}" for n in notes)
    prompt = f"Question: {state['question']}\n\nResearch notes:\n{notes_text}"

    data = structured_call(
        system=SYSTEM,
        user_prompt=prompt,
        tool_name="submit_facts",
        tool_description="Submit extracted facts with source citations",
        input_schema=FACTS_SCHEMA,
        max_tokens=2048,
    )

    # Drop any fact citing a source_id that was not in the notes - that is a
    # fabricated citation, and it is cheaper to catch here than in the Critic.
    known = {n["source_id"] for n in notes}
    raw_facts = data.get("facts", [])
    facts = [f for f in raw_facts if f.get("source_id") in known and f.get("claim")]
    dropped = len(raw_facts) - len(facts)

    detail = f"extracted {len(facts)} facts from {len(notes)} notes"
    if dropped:
        detail += f"; dropped {dropped} citing unknown source_ids"
    return {"facts": facts, "_detail": detail}
