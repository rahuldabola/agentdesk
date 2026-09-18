import type { TraceEntry } from "../api";

export type AgentKey = "planner" | "researcher" | "analyst" | "writer" | "critic";

export interface AgentMeta {
  key: AgentKey;
  label: string;
  blurb: string;
  description: string;
  color: string;
}

export const AGENTS: AgentMeta[] = [
  {
    key: "planner",
    label: "Planner",
    blurb: "Decomposes the question",
    description: "Splits your question into focused sub-questions and decides whether to search the internal knowledge base, the web, or both.",
    color: "#8b7cff",
  },
  {
    key: "researcher",
    label: "Researcher",
    blurb: "RAG + web search",
    description: "Runs every sub-question in parallel through MCP tools: vector search over the knowledge base and live web search.",
    color: "#38bdf8",
  },
  {
    key: "analyst",
    label: "Analyst",
    blurb: "Extracts cited facts",
    description: "Reads the raw evidence and pulls out atomic facts, each pinned to the exact source it came from.",
    color: "#34d399",
  },
  {
    key: "writer",
    label: "Writer",
    blurb: "Drafts the report",
    description: "Turns the fact sheet into a readable report where every sentence carries an inline citation.",
    color: "#fbbf24",
  },
  {
    key: "critic",
    label: "Critic",
    blurb: "Checks every claim",
    description: "Fact-checks the draft against the evidence. Unsupported claims send it back for a rewrite, evidence gaps send it back to research.",
    color: "#f472b6",
  },
];

export const AGENT_BY_KEY = Object.fromEntries(AGENTS.map((a) => [a.key, a])) as Record<AgentKey, AgentMeta>;

export function isAgentKey(value: string | undefined): value is AgentKey {
  return !!value && value in AGENT_BY_KEY;
}

/**
 * Which agent is working right now. Trace entries are emitted when a node
 * *finishes*, so the active agent is the one that follows the last entry —
 * and after the Critic, its verdict says whether we loop back to research,
 * back to the writer, or are done.
 */
export function inferActiveAgent(trace: TraceEntry[], running: boolean): AgentKey | null {
  if (!running) return null;
  const last = trace.at(-1);
  if (!last) return "planner";
  switch (last.node) {
    case "planner":
      return "researcher";
    case "researcher":
      return "analyst";
    case "analyst":
      return "writer";
    case "writer":
      return "critic";
    case "critic":
      if (/research/i.test(last.detail)) return "researcher";
      if (/revise|rewrite/i.test(last.detail)) return "writer";
      return null;
    default:
      return null;
  }
}

export function visitCounts(trace: TraceEntry[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const entry of trace) counts.set(entry.node, (counts.get(entry.node) ?? 0) + 1);
  return counts;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}
