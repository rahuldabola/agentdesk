import { ArrowUp, Keyboard, Menu, Plus, RefreshCw, Search, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { checkPassword, clearStoredPassword, fetchHealth, getStoredPassword, streamReport } from "./api";
import CommandPalette from "./components/CommandPalette";
import DraftingPreview from "./components/DraftingPreview";
import FollowUps from "./components/FollowUps";
import Hero from "./components/Hero";
import Logo from "./components/Logo";
import PasswordGate from "./components/PasswordGate";
import PipelinePanel from "./components/PipelinePanel";
import QuestionComposer from "./components/QuestionComposer";
import ReportView from "./components/ReportView";
import ShortcutsDialog from "./components/ShortcutsDialog";
import Sidebar, { type HealthState } from "./components/Sidebar";
import { useToast } from "./components/Toast";
import { loadRuns, saveRuns, type Run } from "./lib/history";

type GateState = "checking" | "locked" | "unlocked";

export default function App() {
  const [gate, setGate] = useState<GateState>("checking");
  const [password, setPassword] = useState("");
  const [runs, setRuns] = useState<Run[]>(loadRuns);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [showTop, setShowTop] = useState(false);
  const [health, setHealth] = useState<HealthState>({ state: "checking" });
  const abortRef = useRef<Map<string, AbortController>>(new Map());
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const reportAnchorRef = useRef<HTMLDivElement>(null);
  const toast = useToast();

  // ---- Auth -------------------------------------------------------------
  useEffect(() => {
    const stored = getStoredPassword();
    if (!stored) {
      setGate("locked");
      return;
    }
    checkPassword(stored)
      .then((ok) => {
        if (ok) {
          setPassword(stored);
          setGate("unlocked");
        } else {
          clearStoredPassword();
          setGate("locked");
        }
      })
      .catch(() => setGate("locked"));
  }, []);

  // ---- Backend health (Railway can cold-start) ------------------------------
  useEffect(() => {
    let cancelled = false;
    let failures = 0;
    let timer = 0;
    async function probe() {
      const ctrl = new AbortController();
      const t = window.setTimeout(() => ctrl.abort(), 8000);
      try {
        const h = await fetchHealth(ctrl.signal);
        if (cancelled) return;
        failures = 0;
        setHealth({ state: "online", model: h.model });
        timer = window.setTimeout(probe, 60_000);
      } catch {
        if (cancelled) return;
        failures++;
        setHealth({ state: failures >= 4 ? "offline" : "waking" });
        timer = window.setTimeout(probe, failures >= 4 ? 30_000 : 5_000);
      } finally {
        window.clearTimeout(t);
      }
    }
    probe();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  // ---- Persist history ---------------------------------------------------------
  useEffect(() => {
    saveRuns(runs);
  }, [runs]);

  const patchRun = useCallback((id: string, patch: Partial<Run> | ((r: Run) => Partial<Run>)) => {
    setRuns((prev) => prev.map((r) => (r.id === id ? { ...r, ...(typeof patch === "function" ? patch(r) : patch) } : r)));
  }, []);

  const anyRunning = runs.some((r) => r.running);
  const active = runs.find((r) => r.id === activeId) ?? null;

  // ---- Runs ------------------------------------------------------------------------
  const startRun = useCallback(
    (question: string) => {
      if (runs.some((r) => r.running)) {
        toast("Wait for the current research to finish, or stop it first", "info");
        return;
      }
      const id = crypto.randomUUID();
      const run: Run = { id, question, trace: [], result: null, error: null, running: true, startedAt: Date.now(), finishedAt: null };
      setRuns((prev) => [run, ...prev]);
      setActiveId(id);
      setDrawerOpen(false);
      scrollRef.current?.scrollTo({ top: 0 });

      const controller = new AbortController();
      abortRef.current.set(id, controller);

      streamReport(
        question,
        password,
        {
          onProgress: (entry) => patchRun(id, (r) => ({ trace: [...r.trace, entry] })),
          onReport: (result) => {
            patchRun(id, { result, running: false, finishedAt: Date.now() });
            toast(result.status === "passed" ? "Report ready and verified" : "Report ready (not fully verified)", result.status === "passed" ? "success" : "info");
            if (document.hidden) document.title = "✓ Report ready · AgentDesk";
          },
          onError: (message) => patchRun(id, { error: message, running: false, finishedAt: Date.now() }),
        },
        controller.signal,
      )
        .catch((err: Error & { status?: number }) => {
          if (err.name === "AbortError") return;
          if (err.status === 401) {
            clearStoredPassword();
            setGate("locked");
          }
          const message = err instanceof TypeError ? "Couldn't reach the AgentDesk API. It may be waking up, so try again in a moment." : err.message;
          patchRun(id, { error: message, running: false, finishedAt: Date.now() });
        })
        .finally(() => {
          abortRef.current.delete(id);
          // A stream that closes without a report or error event shouldn't spin forever.
          patchRun(id, (r) => (r.running ? { running: false, error: "The connection closed before the report arrived.", finishedAt: Date.now() } : {}));
        });
    },
    [password, patchRun, runs, toast],
  );

  const stopRun = useCallback(() => {
    const running = runs.find((r) => r.running);
    if (!running) return;
    abortRef.current.get(running.id)?.abort();
    abortRef.current.delete(running.id);
    patchRun(running.id, { running: false, error: "Stopped. You cancelled this run.", finishedAt: Date.now() });
    toast("Research stopped", "info");
  }, [runs, patchRun, toast]);

  function newResearch() {
    setActiveId(null);
    setDrawerOpen(false);
    scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    window.setTimeout(() => inputRef.current?.focus(), 50);
  }

  function deleteRun(id: string) {
    setRuns((prev) => prev.filter((r) => r.id !== id));
    if (activeId === id) setActiveId(null);
    toast("Removed from history", "info");
  }

  function navigateTo(section: "how-it-works" | "knowledge-base") {
    setActiveId(null);
    setDrawerOpen(false);
    window.setTimeout(() => document.getElementById(section)?.scrollIntoView({ behavior: "smooth", block: "start" }), 80);
  }

  function togglePin(id: string) {
    const run = runs.find((r) => r.id === id);
    patchRun(id, (r) => ({ pinned: !r.pinned }));
    toast(run?.pinned ? "Unpinned" : "Pinned to the top of your history", "info");
  }

  function lock() {
    clearStoredPassword();
    setPassword("");
    setGate("locked");
  }

  // Restore the tab title once the user comes back.
  useEffect(() => {
    const onVis = () => {
      if (!document.hidden) document.title = "AgentDesk · Multi-Agent Research Orchestrator";
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  // ---- Keyboard shortcuts ------------------------------------------------------------
  useEffect(() => {
    if (gate !== "unlocked") return;
    function onKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      const typing = target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      } else if (paletteOpen) {
        return; // the palette handles its own keys
      } else if (e.key === "Escape") {
        if (shortcutsOpen) setShortcutsOpen(false);
        else if (drawerOpen) setDrawerOpen(false);
        else if (anyRunning) stopRun();
      } else if (!typing && e.key === "/") {
        e.preventDefault();
        inputRef.current?.focus();
      } else if (!typing && e.key === "?") {
        setShortcutsOpen(true);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ---- Scrolling: follow the live log, then bring the report into view ----------------
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !active?.running) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 240;
    if (nearBottom) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  }, [active?.trace.length, active?.running]);

  const hasResult = !!active?.result;
  useEffect(() => {
    if (hasResult && active?.finishedAt && Date.now() - active.finishedAt < 2000) {
      window.setTimeout(() => reportAnchorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 150);
    }
  }, [hasResult, active?.finishedAt]);

  const paletteActions = useMemo(
    () => ({
      newResearch,
      ask: startRun,
      openRun: (id: string) => setActiveId(id),
      navigate: navigateTo,
      showShortcuts: () => setShortcutsOpen(true),
      lock,
    }),
    [startRun],
  );

  // ---- Render --------------------------------------------------------------------------
  if (gate === "checking") {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="app-backdrop" />
        <div className="relative animate-pulse">
          <Logo size={48} />
        </div>
      </div>
    );
  }
  if (gate === "locked") return <PasswordGate onUnlock={(pw) => { setPassword(pw); setGate("unlocked"); }} />;

  const sidebar = (onClose?: () => void) => (
    <Sidebar
      runs={runs}
      activeId={activeId}
      health={health}
      onSelect={(id) => {
        setActiveId(id);
        setDrawerOpen(false);
      }}
      onNew={newResearch}
      onDelete={deleteRun}
      onTogglePin={togglePin}
      onClearAll={() => {
        setRuns((prev) => prev.filter((r) => r.running));
        setActiveId(null);
        toast("History cleared", "info");
      }}
      onNavigate={navigateTo}
      onShowShortcuts={() => setShortcutsOpen(true)}
      onSignOut={lock}
      onClose={onClose}
    />
  );

  const composer = (large?: boolean) => (
    <QuestionComposer running={anyRunning} onSubmit={startRun} onStop={stopRun} inputRef={inputRef} autoFocus={large} large={large} />
  );

  return (
    <div className="relative flex h-full overflow-hidden">
      <div className="app-backdrop" />

      <aside className="glass no-print relative z-10 hidden w-72 shrink-0 border-y-0 border-l-0 md:block">{sidebar()}</aside>

      <div
        aria-hidden
        className={`no-print fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity duration-300 md:hidden ${drawerOpen ? "opacity-100" : "pointer-events-none opacity-0"}`}
        onClick={() => setDrawerOpen(false)}
      />
      <aside
        inert={!drawerOpen}
        className={`no-print fixed inset-y-0 left-0 z-50 w-[82%] max-w-[300px] border-r border-[var(--border)] bg-[#0b0c13f5] backdrop-blur-xl transition-transform duration-300 ease-[cubic-bezier(0.2,0.8,0.2,1)] md:hidden ${drawerOpen ? "translate-x-0" : "-translate-x-full"}`}
      >
        {sidebar(() => setDrawerOpen(false))}
      </aside>

      <main className="relative z-10 flex min-w-0 flex-1 flex-col">
        <header className="no-print flex shrink-0 items-center gap-3 border-b border-[var(--border)] px-4 py-3 backdrop-blur-md sm:px-6">
          <button onClick={() => setDrawerOpen(true)} aria-label="Open menu" className="-ml-1 rounded-lg p-1.5 text-[var(--text-dim)] hover:bg-white/5 md:hidden">
            <Menu size={18} />
          </button>
          <div className="flex min-w-0 flex-1 items-center gap-2 text-[13px]">
            <span className="md:hidden">
              <Logo size={24} />
            </span>
            {active ? (
              <>
                <button onClick={newResearch} className="hidden shrink-0 text-[var(--text-faint)] transition hover:text-[var(--text-dim)] sm:inline">
                  Research
                </button>
                <span className="hidden text-[var(--text-faint)] sm:inline">/</span>
                <span className="truncate font-medium">{active.question}</span>
              </>
            ) : (
              <span className="font-medium">New research</span>
            )}
          </div>
          <button
            onClick={() => setPaletteOpen(true)}
            className="hidden shrink-0 items-center gap-2 rounded-lg border border-[var(--border)] bg-white/[0.02] py-1.5 pl-2.5 pr-1.5 text-xs text-[var(--text-faint)] transition hover:border-[var(--border-strong)] hover:text-[var(--text-dim)] sm:flex"
          >
            <Search size={13} /> Search or ask…
            <kbd className="ml-3">Ctrl K</kbd>
          </button>
          <button onClick={() => setPaletteOpen(true)} aria-label="Search or ask" className="rounded-lg p-1.5 text-[var(--text-dim)] hover:bg-white/5 sm:hidden">
            <Search size={17} />
          </button>
          {active && (
            <button
              onClick={newResearch}
              className="flex shrink-0 items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs text-[var(--text-dim)] transition hover:border-[var(--accent)] hover:text-[var(--text)]"
            >
              <Plus size={13} /> <span className="hidden sm:inline">New</span>
            </button>
          )}
          <button
            onClick={() => setShortcutsOpen(true)}
            aria-label="Keyboard shortcuts"
            className="hidden rounded-lg p-1.5 text-[var(--text-faint)] transition hover:bg-white/5 hover:text-[var(--text)] sm:block"
          >
            <Keyboard size={16} />
          </button>
        </header>

        {health.state === "waking" && (
          <div className="no-print flex items-center justify-center gap-2 border-b border-[#fbbf2433] bg-[#fbbf240d] px-4 py-1.5 text-[11.5px] text-[var(--warn)]">
            <span className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--warn)]/30 border-t-[var(--warn)]" />
            The research API is waking up from sleep. The first request can take a few extra seconds.
          </div>
        )}

        <div
          ref={scrollRef}
          onScroll={(e) => {
            const next = e.currentTarget.scrollTop > 900;
            if (next !== showTop) setShowTop(next);
          }}
          className="print-root min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4 sm:px-6">
          <div className="mx-auto w-full max-w-4xl py-8">
            {!active ? (
              <Hero composer={composer(true)} onAsk={startRun} />
            ) : (
              <div key={active.id} className="flex flex-col gap-5 pb-4">
                <div className="no-print animate-fade-up flex items-start gap-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-[#38bdf8] to-[#7c6dfa] text-[11px] font-bold">You</span>
                  <div className="glass rounded-2xl rounded-tl-md px-4 py-3 text-[14.5px] leading-relaxed">{active.question}</div>
                </div>

                <div className="no-print">
                  <PipelinePanel key={active.id} run={active} onStop={stopRun} />
                </div>

                {active.error && (
                  <div className="no-print animate-fade-up flex flex-wrap items-center gap-3 rounded-2xl border border-[#ff6b6b40] bg-[#ff6b6b0d] px-4 py-3.5 text-sm">
                    <TriangleAlert size={16} className="shrink-0 text-[var(--err)]" />
                    <span className="min-w-0 flex-1 text-[var(--text-dim)]">{active.error}</span>
                    <button
                      onClick={() => startRun(active.question)}
                      disabled={anyRunning}
                      className="flex items-center gap-1.5 rounded-lg border border-[var(--border-strong)] px-3 py-1.5 text-xs font-medium transition hover:border-[var(--accent)] disabled:opacity-40"
                    >
                      <RefreshCw size={12} /> Try again
                    </button>
                  </div>
                )}

                {active.running && <DraftingPreview trace={active.trace} />}

                <div ref={reportAnchorRef} className="scroll-mt-4">
                  {active.result && <ReportView result={active.result} trace={active.trace} onRerun={() => startRun(active.question)} />}
                </div>

                {active.result && <FollowUps question={active.question} disabled={anyRunning} onAsk={startRun} />}
              </div>
            )}
          </div>
        </div>

        {active && (
          <div className="no-print shrink-0 border-t border-[var(--border)] px-4 py-3 backdrop-blur-md sm:px-6">
            <div className="mx-auto w-full max-w-4xl">{composer()}</div>
          </div>
        )}
      </main>

      {showTop && (
        <button
          onClick={() => scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" })}
          aria-label="Back to top"
          title="Back to top"
          className="glass no-print animate-fade-up fixed bottom-28 right-5 z-30 flex h-10 w-10 items-center justify-center rounded-full text-[var(--text-dim)] shadow-xl transition hover:text-[var(--text)] sm:right-8"
        >
          <ArrowUp size={16} />
        </button>
      )}

      <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} runs={runs} running={anyRunning} actions={paletteActions} />
    </div>
  );
}
