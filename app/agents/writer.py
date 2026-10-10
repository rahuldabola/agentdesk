"""Writer: drafts the report from the organised facts, citing every claim."""

from app.agents.base import node
from app.agents.synthesizer import source_trust
from app.config import agent_model
from app.llm.gemini_client import text_call

SYSTEM = (
    "You are the Writer agent. Write a clear, well-structured report answering the question "
    "using ONLY the provided facts. Cite each claim inline using its source_id in square "
    "brackets, exactly as given, e.g. [rag:engineering_handbook.md#2] or [web:1]. Put exactly "
    "one source_id per bracket - if a claim draws on two sources, cite them as two consecutive "
    "brackets like [rag:a.md#0][web:2], never combined in one bracket like [rag:a.md#0, web:2]. "
    "Never invent a source_id. If the facts are insufficient to fully answer the question, say "
    "so explicitly and state what is missing, rather than guessing. Open with a short direct "
    "answer, then the detail. Where the facts are grouped under headings, use them as your "
    "section structure. Treat internal sources as authoritative for how this company works; "
    "present external sources as context or comparison, and never let one override the other "
    "silently."
)

# Each question type has a shape that serves it; the model is told the shape, not
# left to improvise one. Unknown types fall back to the open-ended shape.
TEMPLATES = {
    "comparison": (
        "Shape: a comparison. State the verdict first, then a Markdown table with one row per "
        "dimension and one column per option, headed by the real name of that option or "
        "source (never 'Option A'), citing inside the cells; then a short note on where the "
        "options differ most and what is not covered by the evidence."
    ),
    "how_to": (
        "Shape: a procedure. Give a one-line goal, then numbered steps in order, each step "
        "short and cited, then a brief list of prerequisites or pitfalls if the facts mention "
        "any."
    ),
    "risk_compliance": (
        "Shape: a risk review. Give the bottom-line exposure first, then a list of risks or "
        "obligations, each with what the requirement is, who it applies to, and its source, "
        "then what is unclear or unverified."
    ),
    "factual_lookup": (
        "Shape: a direct answer. One or two sentences stating the answer with its citation, "
        "followed by only the supporting context that is needed. Do not pad."
    ),
    "open_ended": (
        "Shape: a brief. A short summary, then a section per theme, then a closing line on "
        "limits of the evidence."
    ),
}


def _facts_block(facts: list[dict], synthesis: dict | None) -> str:
    """Facts grouped under the Synthesizer's headings, or flat when there is no plan.

    Every fact line keeps the `- claim [source_id]` form so a citation always
    sits next to the claim it supports.
    """

    def line(fact: dict) -> str:
        return f"- {fact['claim']} [{fact['source_id']}]"

    themes = (synthesis or {}).get("themes") or []
    placed = {i for t in themes for i in t["fact_ids"]}
    if not themes or any(i >= len(facts) for i in placed):
        return "\n".join(line(f) for f in facts)

    sections = []
    for theme in themes:
        body = "\n".join(line(facts[i]) for i in theme["fact_ids"])
        sections.append(f"### {theme['title']}\n{body}")
    return "\n\n".join(sections)


def _source_legend(facts: list[dict]) -> str:
    internal = sorted({f["source_id"] for f in facts if source_trust(f["source_id"]) == "internal"})
    external = sorted({f["source_id"] for f in facts if source_trust(f["source_id"]) == "external"})
    parts = []
    if internal:
        parts.append("Internal company documents: " + ", ".join(internal))
    if external:
        parts.append("External web sources: " + ", ".join(external))
    return "\n".join(parts)


def _synthesis_notes(synthesis: dict | None, facts: list[dict]) -> str:
    notes = ""
    conflicts = (synthesis or {}).get("conflicts") or []
    if conflicts:
        lines = []
        for c in conflicts:
            ids = [facts[i]["source_id"] for i in c["fact_ids"] if i < len(facts)]
            suffix = f" (sources: {', '.join(ids)})" if ids else ""
            lines.append(f"- {c['description']}{suffix}")
        notes += "\n\nThe evidence conflicts here - say so in the report, do not hide it:\n"
        notes += "\n".join(lines)
    gaps = (synthesis or {}).get("gaps") or []
    if gaps:
        notes += "\n\nNo fact addresses these - state that they are not covered:\n"
        notes += "\n".join(f"- {g}" for g in gaps)
    return notes


@node("writer")
def writer_node(state: dict) -> dict:
    facts = state.get("facts", [])
    synthesis = state.get("synthesis")
    facts_text = _facts_block(facts, synthesis)

    prompt = f"Question: {state['question']}\n\nFacts:\n{facts_text or '(none)'}"
    legend = _source_legend(facts)
    if legend:
        prompt += f"\n\n{legend}"
    prompt += _synthesis_notes(synthesis, facts)

    criteria = state.get("success_criteria") or []
    if criteria:
        listed = "\n".join(f"- {c}" for c in criteria)
        prompt += (
            "\n\nA complete answer must address each of these (say so explicitly if the "
            f"facts cannot support one):\n{listed}"
        )
    prompt += f"\n\n{TEMPLATES.get(state.get('question_type'), TEMPLATES['open_ended'])}"

    feedback = state.get("critic_feedback")
    revision = state.get("revision_count", 0)

    if feedback and revision:
        unsupported = state.get("unsupported_claims") or []
        prompt += f"\n\nThe previous draft was rejected by the Critic: {feedback}"
        if unsupported:
            listed = "\n".join(f"- {c}" for c in unsupported)
            prompt += f"\n\nSpecifically, these claims were not supported by the facts:\n{listed}"
        prompt += "\n\nRewrite the report so every remaining claim is supported and cited."

    report = text_call(system=SYSTEM, user_prompt=prompt, model=agent_model("writer"))

    return {
        "draft_report": report,
        "_detail": f"drafted {len(report)} chars from {len(facts)} facts (revision {revision})",
    }
