import asyncio

from app.mcp.client import call_tool


async def _research_subtask(subtask, use_rag, use_web):
    notes = []

    if use_rag:
        text = await call_tool("rag_search", {"query": subtask, "k": 4})
        if text and "No relevant" not in text:
            for block in text.split("\n\n"):
                block = block.strip()
                if block.startswith("["):
                    source_id, _, content = block.partition("]")
                    notes.append({
                        "source_id": source_id.lstrip("["),
                        "source_type": "rag",
                        "content": content.strip(),
                    })

    if use_web:
        text = await call_tool("web_search", {"query": subtask, "max_results": 3})
        if text and "No results" not in text:
            for i, line in enumerate(l for l in text.split("\n") if l.strip()):
                notes.append({
                    "source_id": f"web:{subtask}#{i}",
                    "source_type": "web",
                    "content": line.strip(),
                })

    return notes


async def research_node_async(state):
    subtasks = state.get("subtasks") or [state["question"]]
    use_rag = state.get("use_rag", True)
    use_web = state.get("use_web", False)

    all_notes = []
    for subtask in subtasks:
        all_notes.extend(await _research_subtask(subtask, use_rag, use_web))

    trace = state.get("trace", [])
    trace.append(f"researcher: gathered {len(all_notes)} notes across {len(subtasks)} subtasks")
    return {"research_notes": all_notes, "trace": trace}


def research_node(state):
    return asyncio.run(research_node_async(state))
