import { Check, ClipboardCheck, Database, Globe, Plus, X } from "lucide-react";
import { useState } from "react";
import type { PlanEdits, PlanReview as Plan } from "../api";

const MAX_SUBTASKS = 8;

function sameList(a: string[], b: string[]) {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

/**
 * Human-in-the-loop checkpoint: the graph is paused (and checkpointed) after
 * the Planner. Nothing is researched until the user approves; edits here are
 * exactly what the Researcher receives.
 */
export default function PlanReview({
  plan,
  busy,
  onApprove,
  onReject,
}: {
  plan: Plan;
  busy: boolean;
  onApprove: (edits: PlanEdits) => void;
  onReject: () => void;
}) {
  const [subtasks, setSubtasks] = useState<string[]>(plan.subtasks);
  const [useRag, setUseRag] = useState(plan.use_rag);
  const [useWeb, setUseWeb] = useState(plan.use_web);

  const cleaned = subtasks.map((s) => s.trim()).filter(Boolean);
  const noTools = !useRag && !useWeb;
  const canApprove = cleaned.length > 0 && !noTools && !busy;

  function approve() {
    if (!canApprove) return;
    const edits: PlanEdits = {};
    if (!sameList(cleaned, plan.subtasks)) edits.subtasks = cleaned;
    if (useRag !== plan.use_rag || useWeb !== plan.use_web) {
      edits.use_rag = useRag;
      edits.use_web = useWeb;
    }
    onApprove(edits);
  }

  const edited = !sameList(cleaned, plan.subtasks) || useRag !== plan.use_rag || useWeb !== plan.use_web;

  return (
    <section aria-labelledby="plan-review-title" className="glass animate-fade-up rounded-2xl border border-[var(--accent)]/30 p-4 sm:p-5">
      <header className="mb-4 flex flex-wrap items-start gap-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)]/15 text-[var(--accent)]">
          <ClipboardCheck size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="plan-review-title" className="text-[14.5px] font-semibold">
            Review the research plan
          </h2>
          <p className="mt-0.5 text-[12.5px] leading-relaxed text-[var(--text-dim)]">
            The run is paused and saved on the server. Edit the sub-questions, then approve to start research. You can also come back to it later.
          </p>
        </div>
        {plan.question_type && (
          <span className="rounded-md border border-[var(--border)] px-2 py-0.5 font-mono text-[10.5px] text-[var(--text-faint)]">{plan.question_type.replace(/_/g, " ")}</span>
        )}
      </header>

      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-faint)]">Sub-questions</h3>
      <ol className="flex flex-col gap-2">
        {subtasks.map((task, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="w-5 shrink-0 text-right font-mono text-[11px] text-[var(--text-faint)]">{i + 1}</span>
            <input
              value={task}
              disabled={busy}
              aria-label={`Sub-question ${i + 1}`}
              onChange={(e) => setSubtasks((prev) => prev.map((s, j) => (j === i ? e.target.value.slice(0, 300) : s)))}
              className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-transparent px-3 py-1.5 text-[13.5px] outline-none transition focus:border-[var(--accent)]"
            />
            <button
              type="button"
              disabled={busy || subtasks.length <= 1}
              onClick={() => setSubtasks((prev) => prev.filter((_, j) => j !== i))}
              aria-label={`Remove sub-question ${i + 1}`}
              className="rounded-md p-1.5 text-[var(--text-faint)] transition hover:bg-[var(--err)]/10 hover:text-[var(--err)] disabled:opacity-30"
            >
              <X size={14} />
            </button>
          </li>
        ))}
      </ol>
      {subtasks.length < MAX_SUBTASKS && (
        <button
          type="button"
          disabled={busy}
          onClick={() => setSubtasks((prev) => [...prev, ""])}
          className="mt-2 ml-7 flex items-center gap-1 text-[12px] text-[var(--text-dim)] transition hover:text-[var(--accent)] disabled:opacity-40"
        >
          <Plus size={13} /> Add a sub-question
        </button>
      )}

      {plan.success_criteria.length > 0 && (
        <>
          <h3 className="mb-2 mt-4 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-faint)]">The Critic will check for</h3>
          <ul className="flex flex-col gap-1 text-[12.5px] text-[var(--text-dim)]">
            {plan.success_criteria.map((c, i) => (
              <li key={i} className="flex gap-2">
                <Check size={13} className="mt-0.5 shrink-0 text-[var(--ok)]" />
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      <h3 className="mb-2 mt-4 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-faint)]">Sources</h3>
      <div className="flex flex-wrap gap-2" role="group" aria-label="Sources to search">
        {[
          { on: useRag, set: setUseRag, label: "Knowledge base", Icon: Database },
          { on: useWeb, set: setUseWeb, label: "Web", Icon: Globe },
        ].map(({ on, set, label, Icon }) => (
          <button
            key={label}
            type="button"
            aria-pressed={on}
            disabled={busy}
            onClick={() => set(!on)}
            className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[12px] transition ${on ? "border-[var(--accent)] bg-[var(--accent)]/10 text-[var(--text)]" : "border-[var(--border)] text-[var(--text-faint)] hover:text-[var(--text)]"}`}
          >
            <Icon size={12} /> {label}
          </button>
        ))}
      </div>
      {noTools && <p className="mt-2 text-[12px] text-[var(--warn)]">Pick at least one source.</p>}

      <footer className="mt-5 flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={onReject}
          className="rounded-xl border border-[var(--border-strong)] px-3.5 py-1.5 text-xs font-medium text-[var(--text-dim)] transition hover:border-[var(--err)] hover:text-[var(--err)] disabled:opacity-40"
        >
          Reject plan
        </button>
        <button
          type="button"
          disabled={!canApprove}
          onClick={approve}
          className="btn-primary flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-semibold text-white transition hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-35"
        >
          <Check size={13} strokeWidth={2.5} /> {edited ? "Approve edited plan" : "Approve and research"}
        </button>
      </footer>
    </section>
  );
}
