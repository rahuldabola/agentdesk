import { motion } from "motion/react";
import { ArrowRight, Eye, EyeOff, Lock } from "lucide-react";
import { type FormEvent, lazy, Suspense, useState } from "react";
import { checkPassword, storePassword } from "../api";
import Logo from "./Logo";

const AgentOrbit = lazy(() => import("../three/AgentOrbit"));
const EMPTY_VISITS = new Map<string, number>();

export default function PasswordGate({ onUnlock }: { onUnlock: (password: string) => void }) {
  const [value, setValue] = useState("");
  const [show, setShow] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shake, setShake] = useState(0);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const pw = value.trim();
    if (!pw) return;
    setChecking(true);
    setError(null);
    try {
      const ok = await checkPassword(pw);
      if (!ok) {
        setError("That password didn't work. Try again.");
        setShake((s) => s + 1);
        setChecking(false);
        return;
      }
      storePassword(pw);
      onUnlock(pw);
    } catch {
      setError("Couldn't reach the AgentDesk API. It may be waking up, so try again in a few seconds.");
      setChecking(false);
    }
  }

  return (
    <div className="relative flex min-h-full items-center justify-center overflow-hidden px-4 py-10">
      <div className="app-backdrop" />
      <div className="pointer-events-auto absolute inset-0 opacity-70">
        <Suspense fallback={null}>
          <AgentOrbit demo active={null} visits={EMPTY_VISITS} lastNode={null} running={false} done={false} compact className="h-full w-full" />
        </Suspense>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20, rotateX: 12 }}
        animate={{ opacity: 1, y: 0, rotateX: 0 }}
        transition={{ duration: 0.7, ease: [0.2, 0.8, 0.2, 1] }}
        style={{ transformPerspective: 900 }}
        className="relative z-10 w-full max-w-sm"
      >
        <div className="mb-7 flex flex-col items-center gap-3 text-center">
          <Logo size={52} />
          <h1 className="gradient-text text-3xl font-bold tracking-tight">AgentDesk</h1>
          <p className="max-w-xs text-sm text-[var(--text-dim)]">Five AI agents that research, write and fact-check a cited report for you.</p>
        </div>

        <motion.form
          key={shake}
          animate={shake ? { x: [0, -10, 10, -6, 6, 0] } : {}}
          transition={{ duration: 0.4 }}
          onSubmit={handleSubmit}
          className="gradient-border glass rounded-2xl p-5 shadow-[0_30px_80px_-30px_#7c6dfa99]"
        >
          <label htmlFor="pw" className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-faint)]">
            <Lock size={11} /> Access password
          </label>
          <div className="flex items-center rounded-xl border border-[var(--border-strong)] bg-black/30 transition focus-within:border-[var(--accent)] focus-within:shadow-[0_0_0_4px_#7c6dfa22]">
            <input
              id="pw"
              autoFocus
              type={show ? "text" : "password"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Enter password"
              autoComplete="current-password"
              className="min-w-0 flex-1 bg-transparent px-3.5 py-3 text-sm outline-none placeholder:text-[var(--text-faint)]"
            />
            <button
              type="button"
              onClick={() => setShow((s) => !s)}
              aria-label={show ? "Hide password" : "Show password"}
              className="px-3 text-[var(--text-faint)] transition hover:text-[var(--text)]"
            >
              {show ? <EyeOff size={15} /> : <Eye size={15} />}
            </button>
          </div>
          {error && (
            <p role="alert" className="mt-2.5 text-xs leading-relaxed text-[var(--err)]">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={checking || !value.trim()}
            className="btn-primary mt-4 flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-40 disabled:shadow-none"
          >
            {checking ? (
              <>
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" /> Checking…
              </>
            ) : (
              <>
                Enter <ArrowRight size={15} />
              </>
            )}
          </button>
        </motion.form>
        <p className="mt-4 text-center text-[11px] text-[var(--text-faint)]">
          Protected so the demo's model quota isn't drained. Ask the owner for access.
        </p>
      </motion.div>
    </div>
  );
}
