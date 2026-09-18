import { useEffect, useState } from "react";
import type { TraceEntry } from "../api";
import { AGENT_BY_KEY, inferActiveAgent, type AgentKey } from "../lib/agents";
import { AGENT_ICONS } from "../lib/icons";

const NARRATION: Record<AgentKey, string> = {
  planner: "Breaking your question into focused sub-questions…",
  researcher: "Searching the knowledge base and the web in parallel…",
  analyst: "Pulling atomic, source-pinned facts out of the evidence…",
  writer: "Writing the report, with a citation on every sentence…",
  critic: "Fact-checking each claim against the sources…",
};

const TIPS = [
  "Reports usually take 15–60 seconds. A Critic rewrite or an extra research round adds time.",
  "Every chip like [rag:…] or [web:…] in the report links to the exact source it came from.",
  "Press Esc at any time to stop this run.",
  "Once it's done, press play in the pipeline panel to replay the run step by step.",
  "Press Ctrl+K anywhere to search your history or start a new question.",
];

/** A skeleton of the report-to-be that narrates what the active agent is doing. */
export default function DraftingPreview({ trace }: { trace: TraceEntry[] }) {
  const active = inferActiveAgent(trace, true) ?? "critic";
  const meta = AGENT_BY_KEY[active];
  const Icon = AGENT_ICONS[active];
  const [tip, setTip] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => setTip((t) => (t + 1) % TIPS.length), 6000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div className="glass animate-fade-up overflow-hidden rounded-2xl" aria-live="polite">
      <div className="flex items-center gap-3 border-b border-[var(--border)] px-5 py-3.5">
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl"
          style={{ background: `${meta.color}22`, color: meta.color, animation: "pulse-ring 1.4s ease-out infinite" }}
        >
          <Icon size={15} />
        </span>
        <div className="min-w-0">
          <div key={active} className="animate-fade-up text-[13.5px] font-medium">
            {NARRATION[active]}
          </div>
          <div className="text-[11px] text-[var(--text-faint)]">Your report will appear here</div>
        </div>
      </div>
      <div className="flex flex-col gap-2.5 px-5 py-5">
        <div className="shimmer h-4 w-2/5 rounded-md" />
        <div className="shimmer h-3 w-full rounded-md" />
        <div className="shimmer h-3 w-[94%] rounded-md" />
        <div className="shimmer h-3 w-[97%] rounded-md" />
        <div className="shimmer h-3 w-3/5 rounded-md" />
      </div>
      <div key={tip} className="animate-fade-up border-t border-[var(--border)] px-5 py-2.5 text-[11.5px] text-[var(--text-dim)]">
        <span className="font-semibold text-[var(--accent-strong)]">Tip · </span>
        {TIPS[tip]}
      </div>
    </div>
  );
}
