import type { ReportResult, TraceEntry } from "../api";

export interface Run {
  id: string;
  question: string;
  trace: TraceEntry[];
  result: ReportResult | null;
  error: string | null;
  running: boolean;
  startedAt: number;
  finishedAt: number | null;
  pinned?: boolean;
}

const HISTORY_KEY = "agentdesk:history:v1";
const MAX_RUNS = 40;

export function loadRuns(): Run[] {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Run[];
    if (!Array.isArray(parsed)) return [];
    // A run that was still streaming when the page closed can never finish.
    return parsed.map((r) =>
      r.running
        ? { ...r, running: false, error: r.error ?? "Interrupted — the page was closed mid-run.", finishedAt: r.finishedAt ?? r.startedAt }
        : r,
    );
  } catch {
    return [];
  }
}

export function saveRuns(runs: Run[]) {
  try {
    // Pinned runs never age out of the cap.
    const pinned = runs.filter((r) => r.pinned);
    const rest = runs.filter((r) => !r.pinned).slice(0, Math.max(0, MAX_RUNS - pinned.length));
    const kept = new Set([...pinned, ...rest]);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(runs.filter((r) => kept.has(r))));
  } catch {
    // Storage full or unavailable — history just won't survive a reload.
  }
}

export function groupRunsByDay(runs: Run[]): { label: string; runs: Run[] }[] {
  const startOfToday = new Date();
  startOfToday.setHours(0, 0, 0, 0);
  const today = startOfToday.getTime();
  const yesterday = today - 86_400_000;
  const week = today - 6 * 86_400_000;

  const groups: { label: string; runs: Run[] }[] = [
    { label: "Pinned", runs: [] },
    { label: "Today", runs: [] },
    { label: "Yesterday", runs: [] },
    { label: "This week", runs: [] },
    { label: "Older", runs: [] },
  ];
  for (const r of runs) {
    if (r.pinned) groups[0].runs.push(r);
    else if (r.startedAt >= today) groups[1].runs.push(r);
    else if (r.startedAt >= yesterday) groups[2].runs.push(r);
    else if (r.startedAt >= week) groups[3].runs.push(r);
    else groups[4].runs.push(r);
  }
  return groups.filter((g) => g.runs.length > 0);
}
