import { ArrowUp, BookOpen, CornerDownLeft, History, Keyboard, Lock, Plus, Search, Sparkles, Workflow, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { EXAMPLES } from "../lib/content";
import type { Run } from "../lib/history";

export interface PaletteActions {
  newResearch: () => void;
  ask: (question: string) => void;
  openRun: (id: string) => void;
  navigate: (section: "how-it-works" | "knowledge-base") => void;
  showShortcuts: () => void;
  lock: () => void;
}

interface Item {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  run: () => void;
}

export default function CommandPalette({
  open,
  onClose,
  runs,
  running,
  actions,
}: {
  open: boolean;
  onClose: () => void;
  runs: Run[];
  running: boolean;
  actions: PaletteActions;
}) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Reset each time it opens.
  const [lastOpen, setLastOpen] = useState(open);
  if (open !== lastOpen) {
    setLastOpen(open);
    if (open) {
      setQuery("");
      setCursor(0);
    }
  }

  useEffect(() => {
    if (open) window.setTimeout(() => inputRef.current?.focus(), 30);
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const q = query.trim().toLowerCase();
    const match = (s: string) => !q || s.toLowerCase().includes(q);
    const out: Item[] = [];

    if (q.length >= 3 && !running) {
      out.push({ id: "ask", group: "Research", label: `Ask: “${query.trim()}”`, hint: "Enter", icon: ArrowUp, run: () => actions.ask(query.trim()) });
    }

    const commands: Item[] = [
      { id: "new", group: "Actions", label: "New research", icon: Plus, run: actions.newResearch },
      { id: "how", group: "Actions", label: "How it works", icon: Workflow, run: () => actions.navigate("how-it-works") },
      { id: "kb", group: "Actions", label: "Browse the knowledge base", icon: BookOpen, run: () => actions.navigate("knowledge-base") },
      { id: "keys", group: "Actions", label: "Keyboard shortcuts", hint: "?", icon: Keyboard, run: actions.showShortcuts },
      { id: "lock", group: "Actions", label: "Lock AgentDesk", icon: Lock, run: actions.lock },
    ];
    out.push(...commands.filter((c) => match(c.label)));

    out.push(
      ...runs
        .filter((r) => match(r.question))
        .slice(0, 6)
        .map((r) => ({ id: `run-${r.id}`, group: "History", label: r.question, icon: History, run: () => actions.openRun(r.id) })),
    );

    if (!running) {
      out.push(
        ...EXAMPLES.filter((e) => match(e.question))
          .slice(0, 4)
          .map((e) => ({ id: `ex-${e.question}`, group: "Examples", label: e.question, hint: e.category, icon: Sparkles, run: () => actions.ask(e.question) })),
      );
    }
    return out;
  }, [query, runs, running, actions]);

  const safeCursor = Math.min(cursor, Math.max(0, items.length - 1));

  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${safeCursor}"]`)?.scrollIntoView({ block: "nearest" });
  }, [safeCursor]);

  function choose(item: Item | undefined) {
    if (!item) return;
    onClose();
    item.run();
  }

  return (
    open && (
      <div className="overlay-in no-print fixed inset-0 z-[60] flex items-start justify-center bg-black/60 px-4 pt-[12vh] backdrop-blur-sm" onClick={onClose}>
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Command palette"
          onClick={(e) => e.stopPropagation()}
          className="dialog-in gradient-border w-full max-w-xl overflow-hidden rounded-2xl border border-[var(--border-strong)] bg-[#10121bfa] backdrop-blur-xl shadow-[0_40px_120px_-30px_#7c6dfa88]"
        >
          <div className="flex items-center gap-3 border-b border-[var(--border)] px-4">
            <Search size={16} className="shrink-0 text-[var(--text-faint)]" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setCursor(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setCursor((c) => Math.min(c + 1, items.length - 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setCursor((c) => Math.max(c - 1, 0));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  choose(items[safeCursor]);
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  e.stopPropagation();
                  onClose();
                }
              }}
              placeholder="Ask a question, search history, or jump to…"
              aria-label="Command"
              className="min-w-0 flex-1 bg-transparent py-4 text-[15px] outline-none placeholder:text-[var(--text-faint)]"
            />
            <kbd>Esc</kbd>
          </div>

          <div ref={listRef} className="max-h-[50vh] overflow-y-auto p-2" role="listbox">
            {items.length === 0 && (
              <p className="px-3 py-8 text-center text-sm text-[var(--text-faint)]">Nothing matches. Type at least 3 characters to ask it as a question.</p>
            )}
            {items.map((item, i) => {
              const header = i === 0 || items[i - 1].group !== item.group ? item.group : null;
              const selected = i === safeCursor;
              return (
                <div key={item.id}>
                  {header && <div className="px-3 pb-1 pt-2.5 text-[10.5px] font-semibold uppercase tracking-wider text-[var(--text-faint)]">{header}</div>}
                  <button
                    data-index={i}
                    role="option"
                    aria-selected={selected}
                    onMouseMove={() => setCursor(i)}
                    onClick={() => choose(item)}
                    className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-[13.5px] transition-colors ${
                      selected ? "bg-[var(--accent-soft)] text-[var(--text)]" : "text-[var(--text-dim)]"
                    }`}
                  >
                    <item.icon size={15} className={selected ? "text-[var(--accent-strong)]" : "text-[var(--text-faint)]"} />
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.hint && <span className="shrink-0 text-[11px] text-[var(--text-faint)]">{item.hint}</span>}
                    {selected && <CornerDownLeft size={13} className="shrink-0 text-[var(--text-faint)]" />}
                  </button>
                </div>
              );
            })}
          </div>

          <div className="flex items-center gap-4 border-t border-[var(--border)] px-4 py-2 text-[11px] text-[var(--text-faint)]">
            <span>
              <kbd>↑</kbd> <kbd>↓</kbd> navigate
            </span>
            <span>
              <kbd>Enter</kbd> select
            </span>
          </div>
        </div>
      </div>
    )
  );
}
