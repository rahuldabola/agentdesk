import type { TraceEntry } from "../api";

export type AgentKey = "planner" | "researcher" | "analyst" | "synthesizer" | "writer" | "critic";

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
    description: "Classifies your question, writes the checklist a complete answer must satisfy, and splits it into focused sub-questions routed to the knowledge base, the web, or both.",
    color: "#8b7cff",
  },
  {
    key: "researcher",
    label: "Researcher",
    blurb: "RAG + web search",
    description: "Two specialists run in parallel through MCP tools: an internal lane that searches the knowledge base (rewording queries that find nothing) and a web lane that searches, then reads the top pages in full.",
    color: "#38bdf8",
  },
  {
    key: "analyst",
    label: "Analyst",
    blurb: "Extracts cited facts",
    description: "Reads the raw evidence and pulls out atomic, typed facts (numbers, policies, procedures), each pinned to the exact source it came from.",
    color: "#34d399",
  },
  {
    key: "synthesizer",
    label: "Synthesizer",
    blurb: "Organises the evidence",
    description: "Groups the facts into themes, flags where sources disagree (including internal vs external practice) and lists what no source covers. Skipped in quick mode.",
    color: "#2dd4bf",
  },
  {
    key: "writer",
    label: "Writer",
    blurb: "Drafts the report",
    description: "Turns the organised facts into a report shaped for the question (comparison table, steps, risk review, direct answer) where every sentence carries an inline citation.",
    color: "#fbbf24",
  },
  {
    key: "critic",
    label: "Critic",
    blurb: "Checks every claim",
    description: "Fact-checks the draft against the evidence, the Planner's checklist and itself. Unsupported or missing points send it back for a rewrite, evidence gaps send it back to research.",
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
      return "synthesizer";
    case "synthesizer":
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
