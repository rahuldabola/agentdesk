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
    localStorage.setItem(HISTORY_KEY, JSON.stringify(runs.slice(0, MAX_RUNS)));
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
    { label: "Today", runs: [] },
    { label: "Yesterday", runs: [] },
    { label: "This week", runs: [] },
    { label: "Older", runs: [] },
  ];
  for (const r of runs) {
    if (r.startedAt >= today) groups[0].runs.push(r);
    else if (r.startedAt >= yesterday) groups[1].runs.push(r);
    else if (r.startedAt >= week) groups[2].runs.push(r);
    else groups[3].runs.push(r);
  }
  return groups.filter((g) => g.runs.length > 0);
}
