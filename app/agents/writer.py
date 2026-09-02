from app.llm.claude_client import text_call

SYSTEM = (
    "You are the Writer agent. Write a clear, well-structured report answering the question "
    "using ONLY the provided facts. Cite each claim inline using its source_id in square "
    "brackets, e.g. [rag:engineering_handbook.md#2]. If the facts are insufficient to fully "
    "answer the question, say so explicitly rather than guessing."
)


def writer_node(state):
    facts = state.get("facts", [])
    facts_text = "\n".join(f"- {f['claim']} [{f['source_id']}]" for f in facts)
    feedback = state.get("critic_feedback")

    user_prompt = f"Question: {state['question']}\n\nFacts:\n{facts_text or '(none)'}"
    if feedback:
        user_prompt += (
            f"\n\nThe previous draft was rejected by the Critic for this reason: {feedback}\n"
            "Revise the report accordingly."
        )

    report = text_call(system=SYSTEM, user_prompt=user_prompt)
    citations = sorted({f["source_id"] for f in facts})

    trace = state.get("trace", [])
    trace.append(f"writer: drafted report ({len(report)} chars), revision #{state.get('revision_count', 0)}")
    return {"draft_report": report, "citations": citations, "trace": trace}
