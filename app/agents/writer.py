"""Writer: drafts the report from the fact list, citing every claim."""

from app.agents.base import node
from app.llm.claude_client import text_call

SYSTEM = (
    "You are the Writer agent. Write a clear, well-structured report answering the question "
    "using ONLY the provided facts. Cite each claim inline using its source_id in square "
    "brackets, exactly as given, e.g. [rag:engineering_handbook.md#2] or [web:1]. Never invent "
    "a source_id. If the facts are insufficient to fully answer the question, say so "
    "explicitly and state what is missing, rather than guessing."
)


@node("writer")
def writer_node(state: dict) -> dict:
    facts = state.get("facts", [])
    facts_text = "\n".join(f"- {f['claim']} [{f['source_id']}]" for f in facts)

    prompt = f"Question: {state['question']}\n\nFacts:\n{facts_text or '(none)'}"
    feedback = state.get("critic_feedback")
    revision = state.get("revision_count", 0)

    if feedback and revision:
        unsupported = state.get("unsupported_claims") or []
        prompt += f"\n\nThe previous draft was rejected by the Critic: {feedback}"
        if unsupported:
            listed = "\n".join(f"- {c}" for c in unsupported)
            prompt += f"\n\nSpecifically, these claims were not supported by the facts:\n{listed}"
        prompt += "\n\nRewrite the report so every remaining claim is supported and cited."

    report = text_call(system=SYSTEM, user_prompt=prompt)

    return {
        "draft_report": report,
        "_detail": f"drafted {len(report)} chars from {len(facts)} facts (revision {revision})",
    }
