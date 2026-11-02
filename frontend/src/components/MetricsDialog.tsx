import { RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { fetchMetrics, type FleetMetrics } from "../api";
import { AGENT_BY_KEY, AGENTS, formatDuration, isAgentKey } from "../lib/agents";
import { formatCost, formatTokens } from "../lib/usage";

/**
 * Fleet-wide numbers from /api/metrics: volume, quality, latency, spend, and
 * which agents the time and money go to. Stat tiles for headlines; a table with
 * single-hue share bars for the per-agent split (agents are named in text).
 */
export default function MetricsDialog({ open, password, onClose }: { open: boolean; password: string; onClose: () => void }) {
  const [data, setData] = useState<FleetMetrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Each refresh bumps `requested`; `loading` is derived, so the effect only
  // sets state once the request settles.
  const [requested, setRequested] = useState(0);
  const [settled, setSettled] = useState(-1);
  const loading = settled !== requested;
  const load = useCallback(() => setRequested((n) => n + 1), []);

  useEffect(() => {
    if (!open) return;
    const ctrl = new AbortController();
    fetchMetrics(password, ctrl.signal)
      .then((m) => {
        setData(m);
        setError(null);
      })
      .catch((err: Error) => {
        if (err.name !== "AbortError") setError(err.message || "Couldn't load metrics.");
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setSettled(requested);
      });
    return () => ctrl.abort();
  }, [open, password, requested]);

  if (!open) return null;

  const rows = data
    ? Object.entries(data.by_agent).sort(
        (a, b) => (AGENTS.findIndex((x) => x.key === a[0]) + 99) % 99 - (AGENTS.findIndex((x) => x.key === b[0]) + 99) % 99,
      )
    : [];

  return (
    <div className="overlay-in no-print fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="metrics-title"
        onClick={(e) => e.stopPropagation()}
        className="dialog-in max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-[var(--border-strong)] bg-[#10121bfa] p-5 shadow-2xl"
      >
        <div className="mb-1 flex items-center justify-between gap-3">
          <h2 id="metrics-title" className="text-sm font-semibold">
            System metrics
          </h2>
          <div className="flex items-center gap-1">
            <button onClick={() => load()} disabled={loading} aria-label="Refresh" className="rounded-lg p-1 text-[var(--text-dim)] hover:bg-white/5 disabled:opacity-40">
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            </button>
            <button onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-[var(--text-dim)] hover:bg-white/5">
              <X size={15} />
            </button>
          </div>
        </div>
        <p className="mb-4 text-[12px] text-[var(--text-faint)]">
          Across the server's {data?.runs === 1 ? "only run" : `last ${data?.runs ?? "…"} runs`}{data?.window_start ? `, since ${new Date(data.window_start * 1000).toLocaleString()}` : ""}. Latency and averages use completed runs; spend counts every run.
        </p>

        {error && <p className="rounded-xl border border-[var(--err)]/30 bg-[var(--err)]/5 px-3 py-2 text-[12.5px] text-[var(--text-dim)]">{error}</p>}

        {data && data.runs === 0 && <p className="py-6 text-center text-[13px] text-[var(--text-faint)]">No runs on this server yet. Ask a question to start collecting metrics.</p>}

        {data && data.runs > 0 && (
          <>
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              <Tile label="Runs" value={String(data.runs)} sub={statusLine(data.by_status)} />
              <Tile label="Verified by Critic" value={data.pass_rate == null ? "–" : `${Math.round(data.pass_rate * 100)}%`} sub={`of ${data.completed} completed`} />
              <Tile
                label="Latency p50 / p95"
                value={data.latency_ms.p50 == null ? "–" : formatDuration(data.latency_ms.p50)}
                sub={data.latency_ms.p95 == null ? "" : `p95 ${formatDuration(data.latency_ms.p95)}`}
              />
              <Tile label="Tokens per run" value={data.avg_tokens_per_run == null ? "–" : formatTokens(data.avg_tokens_per_run)} sub={`${formatTokens(data.total_tokens)} total`} />
              <Tile label="Cost per run" value={data.avg_cost_per_run_usd == null ? "–" : formatCost(data.avg_cost_per_run_usd)} sub="list price, paid tier" />
              <Tile label="Total spend" value={formatCost(data.total_cost_usd)} sub="free tier bills $0" />
            </dl>

            {rows.length > 0 && (
              <div className="mt-5">
                <h3 className="mb-2 text-[13px] font-semibold">Where time and money go</h3>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] text-[12px]">
                    <thead>
                      <tr className="text-left text-[10.5px] uppercase tracking-wider text-[var(--text-faint)]">
                        <th className="pb-2 font-medium">Agent</th>
                        <th className="pb-2 font-medium">Share of time</th>
                        <th className="pb-2 font-medium">Share of cost</th>
                        <th className="pb-2 text-right font-medium">Avg time</th>
                        <th className="pb-2 text-right font-medium">Avg tokens</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(([key, a]) => (
                        <tr key={key} className="border-t border-[var(--border)]">
                          <td className="py-2 pr-3 font-medium">{isAgentKey(key) ? AGENT_BY_KEY[key].label : key}</td>
                          <td className="py-2 pr-3">
                            <Share value={a.time_share} />
                          </td>
                          <td className="py-2 pr-3">
                            <Share value={a.cost_share} />
                          </td>
                          <td className="py-2 text-right font-mono tabular-nums text-[var(--text-dim)]">{formatDuration(a.avg_elapsed_ms)}</td>
                          <td className="py-2 text-right font-mono tabular-nums text-[var(--text-dim)]">{formatTokens(a.avg_tokens)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-3 text-[11px] text-[var(--text-faint)]">
                  Each agent step is also exported as an OpenTelemetry span (with a child span per Gemini call and MCP tool call) when the server has an OTLP endpoint configured.
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function statusLine(byStatus: Record<string, number>): string {
  return Object.entries(byStatus)
    .map(([s, n]) => `${n} ${s.replace("_", " ")}`)
    .join(" · ");
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-white/[0.02] px-3 py-2.5">
      <dt className="text-[11px] text-[var(--text-faint)]">{label}</dt>
      <dd className="mt-0.5 font-mono text-[18px] font-semibold tabular-nums">{value}</dd>
      {sub && <dd className="truncate text-[10.5px] text-[var(--text-faint)]">{sub}</dd>}
    </div>
  );
}

function Share({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-2" title={`${pct}%`}>
      <div className="h-2 w-28 shrink-0 overflow-hidden rounded-full bg-white/[0.05]" role="img" aria-label={`${pct}%`}>
        <div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${value > 0 ? Math.max(2, pct) : 0}%` }} />
      </div>
      <span className="font-mono tabular-nums text-[var(--text-dim)]">{pct}%</span>
    </div>
  );
}
