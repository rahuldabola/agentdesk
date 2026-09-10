"""Critic: checks the draft against the facts, and decides what to do about it.

The Critic has three outcomes, not two. A draft can fail because the Writer
overreached (fixable by rewriting) or because the evidence was never gathered
(fixable only by researching again). Routing both failures back to the Writer
would let it rephrase the same gap forever, so a gap that names missing
information sends the graph back to the Researcher instead.
"""

from app.agents.base import node
from app.config import get_settings
from app.llm.gemini_client import structured_call

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["pass", "revise"]},
        "feedback": {"type": "string", "description": "Why the draft passed or failed"},
        "unsupported_claims": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Claims in the draft not backed by any fact, or citing an unknown source_id"
            ),
        },
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Research questions that must be answered to finish the report. Only fill "
                "this in when the FACTS are insufficient - not when the draft merely "
                "overstates the facts it already has."
            ),
        },
    },
    "required": ["verdict", "feedback", "unsupported_claims", "missing_information"],
}

SYSTEM = (
    "You are the Critic agent. Check the draft report against the provided facts. Flag any "
    "claim in the report that is NOT supported by the facts (a hallucination), and any "
    "citation referencing a source_id absent from the facts. Return verdict='revise' if there "
    "are unsupported claims, missing citations, or the report cannot answer the question from "
    "the facts available. Use missing_information ONLY when more research is needed; if the "
    "facts are adequate and the draft simply overstates them, leave it empty."
)


@node("critic")
def critic_node(state: dict) -> dict:
    settings = get_settings()
    facts = state.get("facts", [])
    facts_text = "\n".join(f"- {f['claim']} [{f['source_id']}]" for f in facts)
    draft = state.get("draft_report", "")

    data = structured_call(
        system=SYSTEM,
        user_prompt=(
            f"Question: {state['question']}\n\nFacts:\n{facts_text or '(none)'}\n\n"
            f"Draft report:\n{draft}"
        ),
        tool_name="submit_verdict",
        tool_description="Submit the critique verdict",
        input_schema=VERDICT_SCHEMA,
    )

    verdict = data.get("verdict", "pass")
    unsupported = data.get("unsupported_claims") or []
    missing = [m for m in (data.get("missing_information") or []) if m and m.strip()]
    revision_count = state.get("revision_count", 0)
    research_rounds = state.get("research_rounds", 0)

    result = {
        "critic_verdict": verdict,
        "critic_feedback": data.get("feedback", ""),
        "unsupported_claims": unsupported,
        "missing_information": [],
    }

    if verdict == "pass":
        result["final_report"] = draft
        result["status"] = "passed"
        detail = f"pass ({len(unsupported)} flagged claims)"
    elif missing and research_rounds < settings.max_research_rounds:
        result["missing_information"] = missing
        result["pending_subtasks"] = missing
        detail = f"revise: {len(missing)} evidence gap(s), routing back to research"
    elif revision_count < settings.max_revisions:
        result["revision_count"] = revision_count + 1
        detail = f"revise: rewrite {revision_count + 1}/{settings.max_revisions}"
    else:
        # Out of attempts. Ship the draft, but say so in the response rather
        # than presenting a rejected report as if it had passed.
        result["final_report"] = draft
        result["status"] = "revision_limit_reached"
        detail = (
            f"revision limit ({settings.max_revisions}) reached; returning last draft unverified"
        )

    result["_detail"] = detail
    return result
