import { ChevronDown, Pause, Play, RotateCcw, Square, Terminal, Timer } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { AGENT_BY_KEY, AGENTS, formatDuration, inferActiveAgent, isAgentKey, visitCounts } from "../lib/agents";
import type { Run } from "../lib/history";
import { AGENT_ICONS } from "../lib/icons";

const AgentOrbit = lazy(() => import("../three/AgentOrbit"));

export default function PipelinePanel({ run, onStop }: { run: Run; onStop: () => void }) {
  const total = run.trace.length;
  const finished = !run.running;
  // Replay: scrub through the finished run's trace, one agent hand-off at a time.
  // `null` means "follow the live end of the trace"; a number pins the replay cursor.
  const [pinnedStep, setPinnedStep] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [showLog, setShowLog] = useState(true);
  const step = pinnedStep === null ? total : Math.min(pinnedStep, total);

  useEffect(() => {
    if (!playing) return;
    const id = window.setTimeout(() => {
      if (step + 1 >= total) {
        setPinnedStep(null);
        setPlaying(false);
      } else {
        setPinnedStep(step + 1);
      }
    }, 850);
    return () => window.clearTimeout(id);
  }, [playing, step, total]);

  const replaying = finished && step < total;
  const trace = useMemo(() => run.trace.slice(0, step), [run.trace, step]);
  const visits = useMemo(() => visitCounts(trace), [trace]);
  const running = run.running || replaying;
  const active = inferActiveAgent(trace, running);
  const done = !!run.result && !replaying;
  const lastNode = trace.at(-1)?.node ?? null;
  const progress = Math.min(1, trace.length / Math.max(5, total || 5));

  return (
    <div className="glass animate-fade-up overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <StatusBadge run={run} replaying={replaying} />
          {active && (
            <span className="text-[var(--text-dim)]">
              <span style={{ color: AGENT_BY_KEY[active].color }}>{AGENT_BY_KEY[active].label}</span> is working…
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ElapsedClock run={run} />
          {run.running && (
            <button
              onClick={onStop}
              className="flex items-center gap-1.5 rounded-lg border border-[var(--err)]/35 px-2.5 py-1 text-xs text-[var(--err)] transition hover:bg-[var(--err)]/10"
            >
              <Square size={10} fill="currentColor" /> Stop
            </button>
          )}
        </div>
      </div>

      <div className="relative">
        <Suspense fallback={<div className="shimmer h-[260px] sm:h-[300px]" />}>
          <AgentOrbit
            compact
            active={active}
            visits={visits}
            lastNode={lastNode}
            running={running}
            done={done}
            className="h-[260px] sm:h-[300px]"
          />
        </Suspense>
        {/* progress sweep along the bottom edge */}
        <div className="absolute inset-x-0 bottom-0 h-[2px] bg-white/5">
          <div
            className="h-full bg-gradient-to-r from-[#8b7cff] via-[#38bdf8] to-[#f472b6] transition-[width] duration-700"
            style={{ width: `${(done ? 1 : progress) * 100}%` }}
          />
        </div>
      </div>

      <div className="grid grid-cols-5 gap-1.5 border-b border-[var(--border)] px-3 py-3">
        {AGENTS.map((agent) => {
          const Icon = AGENT_ICONS[agent.key];
          const count = visits.get(agent.key) ?? 0;
          const isActive = active === agent.key;
          const state = isActive ? "active" : count > 0 ? "done" : "idle";
          return (
            <div
              key={agent.key}
              className="flex flex-col items-center gap-1 rounded-xl px-1 py-2 text-center transition-colors"
              style={{ background: isActive ? `${agent.color}18` : "transparent" }}
              title={agent.description}
            >
              <span
                className="relative flex h-7 w-7 items-center justify-center rounded-lg transition-all"
                style={{
                  background: state === "idle" ? "rgba(255,255,255,0.04)" : `${agent.color}24`,
                  color: state === "idle" ? "var(--text-faint)" : agent.color,
                  animation: isActive ? "pulse-ring 1.4s ease-out infinite" : undefined,
                }}
              >
                <Icon size={14} />
                {count > 1 && (
                  <span className="absolute -right-1.5 -top-1.5 rounded-full bg-[var(--panel-solid)] px-1 text-[9px] font-semibold" style={{ color: agent.color }}>
                    ×{count}
                  </span>
                )}
              </span>
              <span className={`text-[10.5px] font-medium ${state === "idle" ? "text-[var(--text-faint)]" : "text-[var(--text-dim)]"}`}>{agent.label}</span>
            </div>
          );
        })}
      </div>

      {finished && total > 0 && (
        <div className="flex items-center gap-3 border-b border-[var(--border)] px-4 py-2.5">
          <button
            onClick={() => {
              if (step >= total) setPinnedStep(0);
              setPlaying((p) => !p);
            }}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--accent-soft)] text-[var(--accent-strong)] transition hover:bg-[var(--accent)] hover:text-white"
            aria-label={playing ? "Pause replay" : "Replay this run"}
            title={playing ? "Pause" : "Replay the run in 3D"}
          >
            {playing ? <Pause size={12} fill="currentColor" /> : step >= total ? <RotateCcw size={12} /> : <Play size={12} fill="currentColor" />}
          </button>
          <input
            type="range"
            min={0}
            max={total}
            value={step}
            onChange={(e) => {
              setPlaying(false);
              const v = Number(e.target.value);
              setPinnedStep(v >= total ? null : v);
            }}
            aria-label="Scrub through the run timeline"
            className="h-1 flex-1 cursor-pointer accent-[var(--accent)]"
          />
          <span className="w-16 shrink-0 text-right font-mono text-[10.5px] text-[var(--text-faint)]">
            step {step}/{total}
          </span>
        </div>
      )}

      {run.trace.length > 0 && (
        <div>
          <button
            onClick={() => setShowLog((s) => !s)}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-[11.5px] font-medium text-[var(--text-dim)] transition hover:text-[var(--text)]"
          >
            <Terminal size={12} /> Agent log
            <span className="text-[var(--text-faint)]">({run.trace.length})</span>
            <ChevronDown size={13} className={`ml-auto transition-transform ${showLog ? "rotate-180" : ""}`} />
          </button>
          {showLog && (
            <div className="max-h-52 overflow-y-auto px-4 pb-3 font-mono text-[11.5px] leading-relaxed">
              {run.trace.map((entry, i) => {
                const meta = isAgentKey(entry.node) ? AGENT_BY_KEY[entry.node] : null;
                const dim = finished && i >= step;
                return (
                  <div key={i} className={`animate-fade-up flex gap-2.5 py-0.5 transition-opacity ${dim ? "opacity-30" : ""}`}>
                    <span className="w-12 shrink-0 text-right text-[var(--text-faint)]">{formatDuration(entry.elapsed_ms)}</span>
                    <span className="w-[74px] shrink-0 font-medium" style={{ color: meta?.color ?? "var(--accent-strong)" }}>
                      {entry.node}
                    </span>
                    <span className="min-w-0 break-words text-[var(--text-dim)]">{entry.detail}</span>
                  </div>
                );
              })}
              {run.running && (
                <div className="flex gap-2.5 py-0.5">
                  <span className="w-12" />
                  <span className="shimmer h-3.5 w-40 rounded" />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ run, replaying }: { run: Run; replaying: boolean }) {
  if (replaying) return <Badge color="var(--cyan)" label="Replaying" pulse />;
  if (run.running) return <Badge color="var(--accent-strong)" label="Running" pulse />;
  if (run.error) return <Badge color="var(--err)" label="Stopped" />;
  if (run.result?.status === "passed") return <Badge color="var(--ok)" label="Verified" />;
  return <Badge color="var(--warn)" label="Unverified" />;
}

function Badge({ color, label, pulse }: { color: string; label: string; pulse?: boolean }) {
  return (
    <span className="flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ color, background: "rgba(255,255,255,0.04)" }}>
      <span className="relative flex h-1.5 w-1.5">
        {pulse && <span className="absolute inset-0 animate-ping rounded-full" style={{ background: color }} />}
        <span className="relative h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      </span>
      {label}
    </span>
  );
}

function ElapsedClock({ run }: { run: Run }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!run.running) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [run.running]);
  const end = run.running ? now : (run.finishedAt ?? now);
  return (
    <span className="flex items-center gap-1 font-mono text-[11px] text-[var(--text-faint)]">
      <Timer size={11} /> {formatDuration(Math.max(0, end - run.startedAt))}
    </span>
  );
}
