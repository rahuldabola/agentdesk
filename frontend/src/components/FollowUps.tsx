import { ArrowRight, Layers, ListChecks, Scale, TriangleAlert } from "lucide-react";
import TiltCard from "./TiltCard";

const MAX_LEN = 2000;

function followUpsFor(question: string) {
  const q = question.trim().replace(/\s+/g, " ");
  const withQ = (suffix: string) => `${q} ${suffix}`.slice(0, MAX_LEN);
  return [
    { icon: Layers, label: "Go deeper", question: withQ("Go deeper, with specific details, numbers and examples.") },
    { icon: Scale, label: "Compare with industry practice", question: withQ("How does this compare with industry best practices?") },
    { icon: TriangleAlert, label: "Exceptions and risks", question: withQ("What are the exceptions, edge cases and risks?") },
    { icon: ListChecks, label: "Turn into a checklist", question: `Summarize as an actionable checklist: ${q}`.slice(0, MAX_LEN) },
  ];
}

export default function FollowUps({ question, disabled, onAsk }: { question: string; disabled: boolean; onAsk: (q: string) => void }) {
  return (
    <section className="no-print animate-fade-up" aria-label="Suggested follow-ups">
      <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--accent-strong)]">Keep going</h3>
      <div className="grid gap-2 sm:grid-cols-2">
        {followUpsFor(question).map((f) => (
          <TiltCard
            key={f.label}
            as="button"
            max={6}
            onClick={() => !disabled && onAsk(f.question)}
            className={`glass group flex items-center gap-3 rounded-xl px-3.5 py-3 text-left ${disabled ? "cursor-not-allowed opacity-50" : "hover:border-[var(--border-strong)]"}`}
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent-strong)]">
              <f.icon size={15} />
            </span>
            <span className="min-w-0 flex-1 text-[13px] font-medium">{f.label}</span>
            <ArrowRight size={14} className="shrink-0 text-[var(--text-faint)] transition group-hover:translate-x-0.5 group-hover:text-[var(--accent-strong)]" />
          </TiltCard>
        ))}
      </div>
    </section>
  );
}
