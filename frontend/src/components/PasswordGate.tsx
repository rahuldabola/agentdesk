import { type FormEvent, useState } from "react";
import { checkPassword, storePassword } from "../api";

export default function PasswordGate({ onUnlock }: { onUnlock: (password: string) => void }) {
  const [value, setValue] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setChecking(true);
    setError(null);
    try {
      const ok = await checkPassword(value.trim());
      if (!ok) {
        setError("That password didn't work. Try again.");
        setChecking(false);
        return;
      }
      storePassword(value.trim());
      onUnlock(value.trim());
    } catch {
      setError("Couldn't reach the AgentDesk API. Is it awake?");
      setChecking(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm animate-fade-up">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[var(--accent)] shadow-[0_0_40px_-8px_var(--accent)]">
            <LogoMark />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">AgentDesk</h1>
          <p className="text-sm text-[var(--text-dim)]">
            Multi-agent research orchestrator. Enter the access password to continue.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border p-5"
          style={{ borderColor: "var(--border)", background: "var(--panel)" }}
        >
          <label className="mb-2 block text-xs font-medium uppercase tracking-wide text-[var(--text-faint)]">
            Access password
          </label>
          <input
            autoFocus
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Enter password"
            className="w-full rounded-lg border bg-[var(--bg-elevated)] px-3 py-2.5 text-sm outline-none transition focus:border-[var(--accent)]"
            style={{ borderColor: "var(--border)" }}
          />
          {error && <p className="mt-2 text-xs text-[var(--err)]">{error}</p>}
          <button
            type="submit"
            disabled={checking || !value}
            className="mt-4 w-full rounded-lg bg-[var(--accent)] py-2.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-40"
          >
            {checking ? "Checking…" : "Enter"}
          </button>
        </form>
      </div>
    </div>
  );
}

function LogoMark() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path
        d="M6 18 L12 6 L18 18 M8.5 13.5 H15.5"
        stroke="white"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
