import { useEffect, useRef } from "react";
import type { TraceEntry } from "../api";

const NODE_LABEL: Record<string, string> = {
  planner: "planner",
  researcher: "researcher",
  analyst: "analyst",
  writer: "writer",
  critic: "critic",
};

export default function TraceLog({ trace }: { trace: TraceEntry[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [trace.length]);

  if (trace.length === 0) return null;

  return (
    <div
      className="max-h-48 overflow-y-auto rounded-xl border px-3 py-2.5 font-mono text-[11.5px] leading-relaxed"
      style={{ borderColor: "var(--border)", background: "#0a0b10" }}
    >
      {trace.map((entry, i) => (
        <div key={i} className="animate-fade-up flex gap-2 py-0.5">
          <span className="shrink-0 text-[var(--text-faint)]">
            {(entry.elapsed_ms / 1000).toFixed(2)}s
          </span>
          <span className="shrink-0 font-medium text-[var(--accent-strong)]">
            {NODE_LABEL[entry.node] ?? entry.node}
          </span>
          <span className="text-[var(--text-dim)]">{entry.detail}</span>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
