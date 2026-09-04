"""A scripted stand-in for Claude, so the pipeline can be evaluated offline.

This exists to test the *harness*, not the model. It answers every agent's
structured call deterministically, which makes the model-independent metrics
(did a report get produced, does every citation resolve, does the control loop
terminate) reproducible in CI at zero cost.

The stub is deliberately not clairvoyant: the planner heuristic below is a
keyword rule that gets some routing decisions wrong. Metrics that depend on
the quality of the model's judgement are reported but are properties of this
stub, not of Claude - see "Evaluation" in the README.
"""

import re

INTERNAL_HINTS = (
    "our",
    "we ",
    "internal",
    "company",
    "policy",
    "handbook",
    "on-call",
    "oncall",
    "api key",
    "rate limit",
    "retention",
    "incident",
    "severity",
    "deploy",
)
EXTERNAL_HINTS = (
    "latest",
    "current",
    "industry",
    "standard",
    "compare",
    "typical",
    "best practice",
    "version of",
    "released",
    "public",
)

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def plan(question: str) -> dict:
    q = question.lower()
    use_rag = any(h in q for h in INTERNAL_HINTS)
    use_web = any(h in q for h in EXTERNAL_HINTS)
    if not (use_rag or use_web):
        use_rag = True
    return {"subtasks": [question], "use_rag": use_rag, "use_web": use_web}


def extract_facts(prompt: str) -> dict:
    """Pull one claim per note straight out of the prompt the Analyst built."""
    facts = []
    for line in prompt.splitlines():
        match = re.match(r"\[([^\]]+)\]\s*(.+)", line.strip())
        if not match:
            continue
        source_id, body = match.group(1), match.group(2).strip()
        claim = SENTENCE_END.split(body)[0].strip()
        if claim:
            facts.append({"claim": claim[:300], "source_id": source_id})
    return {"facts": facts[:12]}


def write_report(prompt: str) -> str:
    """Echo the fact list back as a cited report - never inventing a source_id."""
    facts = re.findall(r"^- (.+?) \[([^\]]+)\]$", prompt, flags=re.MULTILINE)
    if not facts:
        return "The available facts are insufficient to answer this question."
    body = " ".join(f"{claim} [{source_id}]" for claim, source_id in facts)
    return f"## Findings\n\n{body}\n"


def critique(prompt: str) -> dict:
    """Pass only if the draft cites at least one fact and invents no source_id."""
    facts_block, _, draft = prompt.partition("Draft report:")
    known = set(re.findall(r"\[([^\]]+)\]", facts_block))
    cited = set(re.findall(r"\[([^\]]+)\]", draft))
    invented = sorted(cited - known)

    if not known:
        return {
            "verdict": "revise",
            "feedback": "No facts were gathered; the question needs more research.",
            "unsupported_claims": [],
            "missing_information": ["gather source material for the question"],
        }
    if invented:
        return {
            "verdict": "revise",
            "feedback": f"The draft cites unknown sources: {', '.join(invented)}.",
            "unsupported_claims": invented,
            "missing_information": [],
        }
    if not cited:
        return {
            "verdict": "revise",
            "feedback": "The draft cites nothing.",
            "unsupported_claims": [],
            "missing_information": [],
        }
    return {
        "verdict": "pass",
        "feedback": "Every claim is cited and every citation resolves.",
        "unsupported_claims": [],
        "missing_information": [],
    }


def structured_call(system, user_prompt, tool_name, tool_description, input_schema, **kwargs):
    if tool_name == "submit_plan":
        return plan(user_prompt)
    if tool_name == "submit_facts":
        return extract_facts(user_prompt)
    if tool_name == "submit_verdict":
        return critique(user_prompt)
    raise AssertionError(f"stub model has no script for tool '{tool_name}'")


def text_call(system, user_prompt, **kwargs):
    return write_report(user_prompt)


def synthetic_web_search(query, max_results, timeout):
    """Deterministic stand-in for a search provider."""
    topic = query.strip().rstrip("?")
    return [
        {
            "title": f"Reference {i + 1} on {topic[:60]}",
            "url": f"https://example.invalid/{i + 1}",
            "snippet": f"Published guidance discussing {topic[:80]}.",
        }
        for i in range(max_results)
    ]
