import type { TraceEntry } from "../api";

const STAGES = [
  { key: "planner", label: "Planner", blurb: "Decomposes the question" },
  { key: "researcher", label: "Researcher", blurb: "RAG + web search" },
  { key: "analyst", label: "Analyst", blurb: "Extracts cited facts" },
  { key: "writer", label: "Writer", blurb: "Drafts the report" },
  { key: "critic", label: "Critic", blurb: "Checks every claim" },
] as const;

export default function StageTracker({
  trace,
  running,
  done,
}: {
  trace: TraceEntry[];
  running: boolean;
  done: boolean;
}) {
  const visitCounts = new Map<string, number>();
  for (const entry of trace) {
    visitCounts.set(entry.node, (visitCounts.get(entry.node) ?? 0) + 1);
  }
  const lastNode = trace.at(-1)?.node;
  const activeIndex = running ? STAGES.findIndex((s) => s.key === lastNode) : -1;

  return (
    <div className="flex flex-col gap-0 sm:flex-row sm:items-start sm:gap-0">
      {STAGES.map((stage, i) => {
        const visits = visitCounts.get(stage.key) ?? 0;
        const isActive = i === activeIndex;
        const isPast = visits > 0 && !isActive;
        const isFuture = visits === 0;
        return (
          <div key={stage.key} className="flex flex-1 sm:flex-col">
            <div className="flex items-center sm:w-full">
              <StageDot state={isActive ? "active" : isFuture ? "future" : done ? "done" : "past"} />
              {i < STAGES.length - 1 && (
                <div
                  className="hidden h-px flex-1 sm:block"
                  style={{
                    background: isPast || done ? "var(--accent)" : "var(--border)",
                    opacity: isPast || done ? 0.5 : 1,
                  }}
                />
              )}
              {i < STAGES.length - 1 && (
                <div
                  className="mx-3 w-px flex-1 sm:hidden"
                  style={{ minHeight: 22 }}
                />
              )}
            </div>
            <div className="ml-0 mt-2 pb-5 sm:ml-0 sm:pb-0 sm:pr-3">
              <div className="flex items-center gap-1.5">
                <span
                  className="text-sm font-medium"
                  style={{ color: isActive ? "var(--text)" : isFuture ? "var(--text-faint)" : "var(--text-dim)" }}
                >
                  {stage.label}
                </span>
                {visits > 1 && (
                  <span
                    className="rounded-full px-1.5 py-0.5 text-[10px] font-medium"
                    style={{ background: "var(--accent-soft)", color: "var(--accent-strong)" }}
                  >
                    ×{visits}
                  </span>
                )}
              </div>
              <p className="text-xs text-[var(--text-faint)]">{stage.blurb}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StageDot({ state }: { state: "active" | "past" | "future" | "done" }) {
  if (state === "active") {
    return (
      <span className="relative flex h-3 w-3 shrink-0 items-center justify-center">
        <span
          className="absolute h-3 w-3 rounded-full"
          style={{ background: "var(--accent)", animation: "pulse-ring 1.4s ease-out infinite" }}
        />
        <span className="h-3 w-3 rounded-full" style={{ background: "var(--accent)" }} />
      </span>
    );
  }
  if (state === "future") {
    return (
      <span
        className="h-3 w-3 shrink-0 rounded-full border-2"
        style={{ borderColor: "var(--border)", background: "transparent" }}
      />
    );
  }
  const color = state === "done" ? "var(--ok)" : "var(--accent)";
  return (
    <span
      className="flex h-3 w-3 shrink-0 items-center justify-center rounded-full"
      style={{ background: color, opacity: state === "done" ? 1 : 0.65 }}
    />
  );
}
