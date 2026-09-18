import { X } from "lucide-react";

const SHORTCUTS: [string[], string][] = [
  [["Ctrl", "K"], "Search history, ask, or jump anywhere"],
  [["/"], "Focus the question box"],
  [["Enter"], "Start research"],
  [["Shift", "Enter"], "New line in question"],
  [["Esc"], "Stop the running research / close panels"],
  [["?"], "Show this help"],
];

export default function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    open && (
      <div className="overlay-in no-print fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="shortcuts-title"
          onClick={(e) => e.stopPropagation()}
          className="dialog-in w-full border border-[var(--border-strong)] bg-[#10121bfa] max-w-sm rounded-2xl p-5 shadow-2xl"
        >
          <div className="mb-4 flex items-center justify-between">
            <h2 id="shortcuts-title" className="text-sm font-semibold">
              Keyboard shortcuts
            </h2>
            <button onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-[var(--text-dim)] hover:bg-white/5">
              <X size={15} />
            </button>
          </div>
          <ul className="flex flex-col gap-2.5">
            {SHORTCUTS.map(([keys, label]) => (
              <li key={label} className="flex items-center justify-between text-[13px] text-[var(--text-dim)]">
                {label}
                <span className="flex gap-1">
                  {keys.map((k) => (
                    <kbd key={k}>{k}</kbd>
                  ))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    )
  );
}
