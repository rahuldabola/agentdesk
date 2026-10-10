"""Synthesizer: organises the Analyst's flat facts into themes before anything is written.

The Writer used to receive an unordered bullet list, so a report's structure was
whatever the model improvised. This node decides the structure first - which
facts belong together, where sources disagree, and what is still unknown - so
the Writer is arranging a plan rather than inventing one.

It only ever references facts by index, and any fact it forgets to place is
kept in a catch-all theme, so synthesis can reorder the evidence but never
drop or alter it.
"""

from app.agents.base import node
from app.config import agent_model
from app.llm.gemini_client import structured_call

SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "themes": {
            "type": "array",
            "description": "Groups of related facts, in the order a reader should meet them",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "A short section heading"},
                    "fact_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Indices of the facts in this theme, as numbered",
                    },
                },
                "required": ["title", "fact_ids"],
            },
        },
        "conflicts": {
            "type": "array",
            "description": "Facts that disagree with each other, or internal vs external practice",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "What the disagreement is"},
                    "fact_ids": {"type": "array", "items": {"type": "integer"}},
                },
                "required": ["description", "fact_ids"],
            },
        },
        "gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Things the question asks about that no fact addresses",
        },
    },
    "required": ["themes", "conflicts", "gaps"],
}

SYSTEM = (
    "You are the Synthesizer agent. You receive numbered facts, each tagged with how "
    "trustworthy its source is (internal = the company's own documents, external = public "
    "web). Group the facts into 2-5 themes that suit the question and its success criteria. "
    "Refer to facts ONLY by their number; never restate or alter a fact. Report a conflict "
    "wherever two facts disagree, or where internal practice differs from external practice "
    "- internal documents are authoritative for how this company works. List gaps for any "
    "success criterion that no fact addresses."
)

OTHER_THEME = "Other findings"


def source_trust(source_id: str) -> str:
    """Internal documents are authoritative for company practice; the web is not."""
    return "internal" if source_id.startswith("rag:") else "external"


def _valid_ids(raw, count: int) -> list[int]:
    ids = []
    for value in raw or []:
        is_index = isinstance(value, int) and not isinstance(value, bool)
        if is_index and 0 <= value < count and value not in ids:
            ids.append(value)
    return ids


def build_synthesis(data: dict, count: int) -> dict:
    """Validate the model's plan against the real fact list.

    Out-of-range indices are discarded, a fact claimed by two themes stays in
    the first, and anything unplaced lands in a final catch-all theme.
    """
    placed: set[int] = set()
    themes = []
    for theme in data.get("themes") or []:
        ids = [i for i in _valid_ids(theme.get("fact_ids"), count) if i not in placed]
        title = (theme.get("title") or "").strip()
        if ids and title:
            placed.update(ids)
            themes.append({"title": title, "fact_ids": ids})

    leftover = [i for i in range(count) if i not in placed]
    if leftover:
        themes.append({"title": OTHER_THEME if themes else "Findings", "fact_ids": leftover})

    conflicts = []
    for conflict in data.get("conflicts") or []:
        description = (conflict.get("description") or "").strip()
        ids = _valid_ids(conflict.get("fact_ids"), count)
        if description:
            conflicts.append({"description": description, "fact_ids": ids})

    gaps = [g.strip() for g in data.get("gaps") or [] if g and g.strip()]
    return {"themes": themes, "conflicts": conflicts, "gaps": gaps}


def _facts_listing(facts: list[dict]) -> str:
    return "\n".join(
        f"{i}. ({source_trust(f['source_id'])}, {f.get('kind', 'claim')}) {f['claim']}"
        for i, f in enumerate(facts)
    )


@node("synthesizer")
def synthesizer_node(state: dict) -> dict:
    facts = state.get("facts") or []
    if not facts:
        return {
            "synthesis": {"themes": [], "conflicts": [], "gaps": []},
            "_detail": "no facts to organise",
        }

    if state.get("depth") == "quick":
        return {
            "synthesis": {"themes": [], "conflicts": [], "gaps": []},
            "_detail": f"skipped in quick mode ({len(facts)} facts passed through)",
        }

    criteria = state.get("success_criteria") or []
    prompt = f"Question: {state['question']}\nQuestion type: {state.get('question_type', '')}\n"
    if criteria:
        prompt += "Success criteria:\n" + "\n".join(f"- {c}" for c in criteria) + "\n"
    prompt += f"\nFacts:\n{_facts_listing(facts)}"

    data = structured_call(
        system=SYSTEM,
        user_prompt=prompt,
        tool_name="submit_synthesis",
        tool_description="Submit the themes, conflicts and gaps",
        input_schema=SYNTHESIS_SCHEMA,
        max_tokens=1536,
        model=agent_model("synthesizer"),
    )
    synthesis = build_synthesis(data, len(facts))
    return {
        "synthesis": synthesis,
        "_detail": (
            f"{len(synthesis['themes'])} theme(s), {len(synthesis['conflicts'])} conflict(s), "
            f"{len(synthesis['gaps'])} gap(s) across {len(facts)} facts"
        ),
    }
