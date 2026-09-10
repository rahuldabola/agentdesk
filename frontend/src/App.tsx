import { useEffect, useRef, useState } from "react";
import { checkPassword, clearStoredPassword, getStoredPassword, streamReport } from "./api";
import type { ReportResult, TraceEntry } from "./api";
import PasswordGate from "./components/PasswordGate";
import QuestionComposer from "./components/QuestionComposer";
import ReportCard from "./components/ReportCard";
import StageTracker from "./components/StageTracker";
import TraceLog from "./components/TraceLog";

interface Run {
  id: string;
  question: string;
  trace: TraceEntry[];
  result: ReportResult | null;
  error: string | null;
  running: boolean;
}

type GateState = "checking" | "locked" | "unlocked";

export default function App() {
  const [gate, setGate] = useState<GateState>("checking");
  const [password, setPassword] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stored = getStoredPassword();
    if (!stored) {
      setGate("locked");
      return;
    }
    checkPassword(stored).then((ok) => {
      if (ok) {
        setPassword(stored);
        setGate("unlocked");
      } else {
        clearStoredPassword();
        setGate("locked");
      }
    });
  }, []);

  function handleUnlock(pw: string) {
    setPassword(pw);
    setGate("unlocked");
  }

  function startRun(question: string) {
    const id = crypto.randomUUID();
    const run: Run = { id, question, trace: [], result: null, error: null, running: true };
    setRuns((prev) => [run, ...prev]);
    setActiveId(id);

    const controller = new AbortController();
    abortRef.current = controller;

    streamReport(
      question,
      password,
      {
        onProgress: (entry) =>
          setRuns((prev) =>
            prev.map((r) => (r.id === id ? { ...r, trace: [...r.trace, entry] } : r)),
          ),
        onReport: (result) =>
          setRuns((prev) =>
            prev.map((r) => (r.id === id ? { ...r, result, running: false } : r)),
          ),
        onError: (message) =>
          setRuns((prev) =>
            prev.map((r) => (r.id === id ? { ...r, error: message, running: false } : r)),
          ),
      },
      controller.signal,
    ).catch((err: Error) => {
      if (err.name === "AbortError") return;
      setRuns((prev) =>
        prev.map((r) => (r.id === id ? { ...r, error: err.message, running: false } : r)),
      );
    });
  }

  const active = runs.find((r) => r.id === activeId) ?? null;
  const anyRunning = runs.some((r) => r.running);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [activeId, active?.trace.length, active?.result, active?.error]);

  if (gate === "checking") return null;
  if (gate === "locked") return <PasswordGate onUnlock={handleUnlock} />;

  return (
    <div className="flex h-screen overflow-hidden">
      <aside
        className="hidden w-64 shrink-0 flex-col overflow-y-auto border-r p-4 md:flex"
        style={{ borderColor: "var(--border)" }}
      >
        <button
          onClick={() => setActiveId(null)}
          className="mb-4 flex shrink-0 items-center gap-2 rounded-lg border px-3 py-2 text-sm transition hover:border-[var(--accent)]"
          style={{ borderColor: "var(--border)" }}
        >
          <PlusIcon /> New research
        </button>
        <div className="flex flex-col gap-1">
          {runs.map((r) => (
            <button
              key={r.id}
              onClick={() => setActiveId(r.id)}
              className="truncate rounded-lg px-3 py-2 text-left text-xs transition"
              style={{
                background: r.id === activeId ? "var(--accent-soft)" : "transparent",
                color: r.id === activeId ? "var(--text)" : "var(--text-dim)",
              }}
            >
              {r.running && <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />}
              {r.question}
            </button>
          ))}
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex shrink-0 items-center justify-between border-b px-4 py-4 sm:px-6"
          style={{ borderColor: "var(--border)" }}
        >
          <div className="mx-auto flex w-full max-w-3xl items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-[var(--accent)]">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <path d="M6 18 L12 6 L18 18 M8.5 13.5 H15.5" stroke="white" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div>
                <div className="text-sm font-semibold leading-tight">AgentDesk</div>
                <div className="text-[11px] leading-tight text-[var(--text-faint)]">Multi-agent research orchestrator</div>
              </div>
            </div>
            <a
              href="https://github.com/rahuldabola/agentdesk"
              target="_blank"
              rel="noreferrer"
              className="text-xs text-[var(--text-faint)] transition hover:text-[var(--text-dim)]"
            >
              source →
            </a>
          </div>
        </header>

        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-4 sm:px-6">
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 py-8">
            {!active && (
              <div className="mt-10 flex flex-col items-center gap-2 text-center">
                <h2 className="text-lg font-medium">What do you want researched?</h2>
                <p className="max-w-md text-sm text-[var(--text-dim)]">
                  Five agents plan, research, extract facts, draft, and fact-check a cited report —
                  every sentence traces to a real source.
                </p>
              </div>
            )}

            {active && (
              <div className="flex flex-col gap-5">
                <div className="animate-fade-up flex items-start gap-3 rounded-2xl border px-4 py-3.5" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
                  <span className="mt-0.5 text-[var(--text-faint)]">Q</span>
                  <p className="text-sm">{active.question}</p>
                </div>

                {(active.running || active.trace.length > 0) && !active.error && (
                  <div className="animate-fade-up flex flex-col gap-4 rounded-2xl border px-5 py-4" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
                    <StageTracker trace={active.trace} running={active.running} done={!!active.result} />
                    <TraceLog trace={active.trace} />
                  </div>
                )}

                {active.error && (
                  <div className="animate-fade-up rounded-2xl border px-4 py-3.5 text-sm" style={{ borderColor: "#ff6b6b33", background: "#ff6b6b0c", color: "var(--err)" }}>
                    {active.error}
                  </div>
                )}

                {active.result && <ReportCard result={active.result} />}
              </div>
            )}
          </div>
        </div>

        <div className="shrink-0 border-t px-4 py-4 sm:px-6" style={{ borderColor: "var(--border)" }}>
          <div className="mx-auto w-full max-w-3xl">
            <QuestionComposer disabled={anyRunning} showExamples={!active} onSubmit={startRun} />
          </div>
        </div>
      </main>
    </div>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
      <path d="M12 5 V19 M5 12 H19" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
