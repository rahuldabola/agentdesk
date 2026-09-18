import { BookOpen, Keyboard, LogOut, Plus, Search, Trash2, Workflow, X } from "lucide-react";
import { useMemo, useState } from "react";
import { groupRunsByDay, type Run } from "../lib/history";
import Logo from "./Logo";

export type HealthState = { state: "checking" | "online" | "waking" | "offline"; model?: string };

export default function Sidebar({
  runs,
  activeId,
  health,
  onSelect,
  onNew,
  onDelete,
  onClearAll,
  onNavigate,
  onShowShortcuts,
  onSignOut,
  onClose,
}: {
  runs: Run[];
  activeId: string | null;
  health: HealthState;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onClearAll: () => void;
  onNavigate: (section: "how-it-works" | "knowledge-base") => void;
  onShowShortcuts: () => void;
  onSignOut: () => void;
  onClose?: () => void;
}) {
  const [query, setQuery] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? runs.filter((r) => r.question.toLowerCase().includes(q)) : runs;
  }, [runs, query]);
  const groups = groupRunsByDay(filtered);

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <div className="flex items-center justify-between px-1.5 pt-1">
        <div className="flex items-center gap-2.5">
          <Logo size={30} />
          <div>
            <div className="text-[14px] font-semibold leading-tight tracking-tight">AgentDesk</div>
            <div className="text-[10.5px] leading-tight text-[var(--text-faint)]">Research orchestrator</div>
          </div>
        </div>
        {onClose && (
          <button onClick={onClose} aria-label="Close menu" className="rounded-lg p-1.5 text-[var(--text-dim)] hover:bg-white/5">
            <X size={16} />
          </button>
        )}
      </div>

      <button
        onClick={onNew}
        className="btn-primary flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[13px] font-semibold text-white transition hover:brightness-110 active:scale-[0.98]"
      >
        <Plus size={15} strokeWidth={2.5} /> New research
        <span className="ml-auto hidden rounded-md bg-white/15 px-1.5 py-px font-mono text-[10px] font-medium sm:inline">Ctrl K</span>
      </button>

      {runs.length > 0 && (
        <label className="flex items-center gap-2 rounded-xl border border-[var(--border)] bg-white/[0.02] px-2.5 py-2 text-[12.5px] focus-within:border-[var(--accent)]">
          <Search size={13} className="shrink-0 text-[var(--text-faint)]" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search history"
            className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-[var(--text-faint)]"
          />
        </label>
      )}

      <nav className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1" aria-label="Research history">
        {runs.length === 0 && (
          <div className="mt-6 rounded-xl border border-dashed border-[var(--border)] px-4 py-6 text-center text-[12px] leading-relaxed text-[var(--text-faint)]">
            Your research history appears here and stays saved in this browser.
          </div>
        )}
        {runs.length > 0 && filtered.length === 0 && <p className="px-2 py-4 text-[12px] text-[var(--text-faint)]">No matches for “{query}”.</p>}
        {groups.map((g) => (
          <div key={g.label} className="mb-3">
            <div className="px-2 pb-1 text-[10.5px] font-semibold uppercase tracking-wider text-[var(--text-faint)]">{g.label}</div>
            <div className="flex flex-col gap-0.5">
              {g.runs.map((r) => {
                const isActive = r.id === activeId;
                return (
                  <div
                    key={r.id}
                    className={`group relative flex items-center rounded-lg transition ${isActive ? "bg-white/[0.07]" : "hover:bg-white/[0.04]"}`}
                  >
                    {isActive && <span className="absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-r bg-[var(--accent)]" />}
                    <button
                      onClick={() => onSelect(r.id)}
                      className={`flex min-w-0 flex-1 items-center gap-2 py-2 pl-2.5 pr-1 text-left text-[12.5px] ${isActive ? "text-[var(--text)]" : "text-[var(--text-dim)]"}`}
                      title={r.question}
                    >
                      <RunDot run={r} />
                      <span className="truncate">{r.question}</span>
                    </button>
                    {!r.running && (
                      <button
                        onClick={() => onDelete(r.id)}
                        aria-label="Delete from history"
                        className="mr-1 rounded-md p-1 text-[var(--text-faint)] opacity-0 transition hover:bg-white/5 hover:text-[var(--err)] focus:opacity-100 group-hover:opacity-100"
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
        {runs.length > 1 && !query && (
          <button
            onClick={() => {
              if (confirmClear) {
                onClearAll();
                setConfirmClear(false);
              } else {
                setConfirmClear(true);
                window.setTimeout(() => setConfirmClear(false), 3000);
              }
            }}
            className={`mt-1 w-full rounded-lg px-2.5 py-1.5 text-left text-[11px] transition ${confirmClear ? "bg-[var(--err)]/10 text-[var(--err)]" : "text-[var(--text-faint)] hover:text-[var(--text-dim)]"}`}
          >
            {confirmClear ? "Click again to clear all history" : "Clear history"}
          </button>
        )}
      </nav>

      <div className="flex flex-col gap-0.5 border-t border-[var(--border)] pt-2">
        <NavItem icon={Workflow} label="How it works" onClick={() => onNavigate("how-it-works")} />
        <NavItem icon={BookOpen} label="Knowledge base" onClick={() => onNavigate("knowledge-base")} />
        <NavItem icon={Keyboard} label="Keyboard shortcuts" hint="?" onClick={onShowShortcuts} />
        <a
          href="https://github.com/rahuldabola/agentdesk"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[12.5px] text-[var(--text-dim)] transition hover:bg-white/[0.04] hover:text-[var(--text)]"
        >
          <GithubMark /> Source code
        </a>
        <NavItem icon={LogOut} label="Lock" onClick={onSignOut} />
      </div>

      <HealthPill health={health} />
    </div>
  );
}

function NavItem({ icon: Icon, label, hint, onClick }: { icon: typeof Plus; label: string; hint?: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] text-[var(--text-dim)] transition hover:bg-white/[0.04] hover:text-[var(--text)]"
    >
      <Icon size={14} /> {label}
      {hint && <kbd className="ml-auto">{hint}</kbd>}
    </button>
  );
}

function RunDot({ run }: { run: Run }) {
  if (run.running) {
    return (
      <span className="relative flex h-2 w-2 shrink-0">
        <span className="absolute inset-0 animate-ping rounded-full bg-[var(--accent)]" />
        <span className="relative h-2 w-2 rounded-full bg-[var(--accent)]" />
      </span>
    );
  }
  const color = run.error ? "var(--err)" : run.result?.status === "passed" ? "var(--ok)" : "var(--warn)";
  return <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} />;
}

export function HealthPill({ health }: { health: HealthState }) {
  const map = {
    checking: { color: "var(--text-faint)", label: "Connecting…" },
    online: { color: "var(--ok)", label: "API online" },
    waking: { color: "var(--warn)", label: "API waking up…" },
    offline: { color: "var(--err)", label: "API unreachable" },
  } as const;
  const { color, label } = map[health.state];
  return (
    <div className="flex items-center gap-2 rounded-xl border border-[var(--border)] bg-white/[0.02] px-2.5 py-2 text-[11px]">
      <span className="relative flex h-2 w-2 shrink-0">
        {health.state !== "offline" && <span className="absolute inset-0 animate-ping rounded-full opacity-60" style={{ background: color }} />}
        <span className="relative h-2 w-2 rounded-full" style={{ background: color }} />
      </span>
      <span className="text-[var(--text-dim)]">{label}</span>
      {health.model && <span className="ml-auto truncate font-mono text-[10px] text-[var(--text-faint)]">{health.model}</span>}
    </div>
  );
}

function GithubMark() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 .5a12 12 0 0 0-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.7-.3-5.5-1.3-5.5-6 0-1.2.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 0 1 6 0C17 4.7 18 5 18 5c.7 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.1 0 4.7-2.8 5.7-5.5 6 .4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0 0 12 .5Z" />
    </svg>
  );
}
