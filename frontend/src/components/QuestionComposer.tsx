import { type FormEvent, useState } from "react";

const EXAMPLES = [
  "What is our on-call rotation and how does it compare to typical SRE practice?",
  "What is our API rate limit?",
  "What is our incident severity scheme?",
  "How should access be revoked when someone leaves the team?",
];

export default function QuestionComposer({
  disabled,
  showExamples,
  onSubmit,
}: {
  disabled: boolean;
  showExamples: boolean;
  onSubmit: (question: string) => void;
}) {
  const [value, setValue] = useState("");

  function submit(q: string) {
    const trimmed = q.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setValue("");
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submit(value);
  }

  return (
    <div className="flex flex-col gap-3">
      <form onSubmit={handleSubmit} className="relative">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit(value);
            }
          }}
          placeholder="Ask a question worth researching…"
          rows={2}
          disabled={disabled}
          className="w-full resize-none rounded-2xl border px-4 py-3.5 pr-24 text-sm outline-none transition focus:border-[var(--accent)] disabled:opacity-50"
          style={{ borderColor: "var(--border)", background: "var(--panel)" }}
        />
        <button
          type="submit"
          disabled={disabled || !value.trim()}
          className="absolute bottom-3 right-3 rounded-lg bg-[var(--accent)] px-4 py-2 text-xs font-medium text-white transition hover:brightness-110 disabled:opacity-30"
        >
          {disabled ? "Researching…" : "Research"}
        </button>
      </form>
      {showExamples && !disabled && (
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => submit(ex)}
              className="rounded-full border px-3 py-1.5 text-xs text-[var(--text-dim)] transition hover:border-[var(--accent)] hover:text-[var(--text)]"
              style={{ borderColor: "var(--border)" }}
            >
              {ex}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
