import { ArrowUp, Square } from "lucide-react";
import { type FormEvent, type RefObject, useLayoutEffect, useState } from "react";

const MIN_LEN = 3;
const MAX_LEN = 2000;

export default function QuestionComposer({
  running,
  onSubmit,
  onStop,
  inputRef,
  autoFocus,
  large,
}: {
  running: boolean;
  onSubmit: (question: string) => void;
  onStop: () => void;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  autoFocus?: boolean;
  large?: boolean;
}) {
  const [value, setValue] = useState("");
  const trimmed = value.trim();
  const valid = trimmed.length >= MIN_LEN && trimmed.length <= MAX_LEN;

  // Grow with the content up to ~8 lines, then scroll.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value, inputRef]);

  function submit() {
    if (!valid || running) return;
    onSubmit(trimmed);
    setValue("");
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    submit();
  }

  const nearLimit = value.length > MAX_LEN * 0.85;

  return (
    <form
      onSubmit={handleSubmit}
      className={`composer gradient-border glass group relative rounded-2xl ${large ? "shadow-[0_20px_70px_-25px_#7c6dfa88]" : ""}`}
    >
      <label htmlFor="question" className="sr-only">
        Research question
      </label>
      <textarea
        id="question"
        ref={inputRef}
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => setValue(e.target.value.slice(0, MAX_LEN))}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder={running ? "Agents are working… press Esc or Stop to cancel" : "Ask a question worth researching…"}
        rows={large ? 2 : 1}
        className={`block w-full resize-none bg-transparent px-4 text-[15px] leading-relaxed text-[var(--text)] outline-none placeholder:text-[var(--text-faint)] ${large ? "pb-12 pt-4" : "pb-11 pt-3.5"}`}
      />
      <div className="absolute inset-x-3 bottom-2.5 flex items-center justify-between gap-2">
        <div className="hidden items-center gap-1.5 text-[11px] text-[var(--text-faint)] sm:flex">
          <kbd>Enter</kbd> to send · <kbd>Shift</kbd>+<kbd>Enter</kbd> new line
        </div>
        <div className="ml-auto flex items-center gap-2.5">
          {value.length > 0 && (
            <span className={`font-mono text-[10.5px] ${nearLimit ? "text-[var(--warn)]" : "text-[var(--text-faint)]"}`}>
              {value.length}/{MAX_LEN}
            </span>
          )}
          {running ? (
            <button
              type="button"
              onClick={onStop}
              title="Stop this run (Esc)"
              className="flex items-center gap-1.5 rounded-xl border border-[var(--err)]/40 bg-[var(--err)]/10 px-3 py-1.5 text-xs font-medium text-[var(--err)] transition hover:bg-[var(--err)]/20"
            >
              <Square size={11} fill="currentColor" /> Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!valid}
              aria-label="Start research"
              className="btn-primary flex items-center gap-1.5 rounded-xl px-3.5 py-1.5 text-xs font-semibold text-white transition hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-35 disabled:shadow-none"
            >
              Research <ArrowUp size={13} strokeWidth={2.5} />
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
