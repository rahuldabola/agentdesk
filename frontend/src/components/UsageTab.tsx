import type { ReportResult, TraceEntry } from "../api";
import { AGENT_BY_KEY, AGENTS, formatDuration, isAgentKey } from "../lib/agents";
import { formatCost, formatTokens, runUsage } from "../lib/usage";

/**
 * Where this run's tokens and money went. Stat tiles for the headline numbers,
 * then one row per agent; each bar is a single measure in a single hue, and the
 * agent is named in text, so nothing depends on telling colors apart.
 */
export default function UsageTab({ result, trace }: { result: ReportResult; trace: TraceEntry[] }) {
  const usage = runUsage(trace, result.usage);
  const tokens = usage.tokens_in + usage.tokens_out;

  if (usage.llm_calls === 0 && tokens === 0) {
    return <p className="p-6 text-center text-[13px] text-[var(--text-faint)]">No usage data for this run. It was recorded before token tracking existed.</p>;
  }

  const order = (key: string) => {
    const i = AGENTS.findIndex((a) => a.key === key);
    return i === -1 ? 99 : i;
  };
  const rows = Object.entries(usage.by_agent)
    .map(([key, u]) => ({ key, ...u, tokens: u.tokens_in + u.tokens_out }))
    .sort((a, b) => order(a.key) - order(b.key));
  const maxTokens = Math.max(...rows.map((r) => r.tokens), 1);
  const maxCost = Math.max(...rows.map((r) => r.cost_usd), 1e-12);
  const top = rows.reduce((a, b) => (b.cost_usd > a.cost_usd ? b : a), rows[0]);

  const tiles = [
    { label: "Tokens", value: formatTokens(tokens), sub: `${formatTokens(usage.tokens_in)} in · ${formatTokens(usage.tokens_out)} out` },
    { label: "LLM calls", value: String(usage.llm_calls), sub: `across ${rows.filter((r) => r.llm_calls > 0).length} agents` },
    { label: "Cost", value: formatCost(usage.cost_usd), sub: "list price, paid tier" },
    { label: "Compute time", value: formatDuration(usage.elapsed_ms), sub: "sum of agent steps" },
  ];

  return (
    <div className="flex flex-col gap-6 p-4 sm:p-5">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-xl border border-[var(--border)] bg-white/[0.02] px-3 py-2.5">
            <dt className="text-[11px] text-[var(--text-faint)]">{t.label}</dt>
            <dd className="mt-0.5 font-mono text-[19px] font-semibold tabular-nums">{t.value}</dd>
            <dd className="text-[10.5px] text-[var(--text-faint)]">{t.sub}</dd>
          </div>
        ))}
      </dl>

      <div>
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-[13px] font-semibold">Usage per agent</h3>
          {top && top.cost_usd > 0 && (
            <span className="text-[11.5px] text-[var(--text-dim)]">
              {isAgentKey(top.key) ? AGENT_BY_KEY[top.key].label : top.key} is the biggest spender ({Math.round((top.cost_usd / (usage.cost_usd || 1)) * 100)}% of cost)
            </span>
          )}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-[12px]">
            <thead>
              <tr className="text-left text-[10.5px] uppercase tracking-wider text-[var(--text-faint)]">
                <th className="pb-2 font-medium">Agent</th>
                <th className="pb-2 font-medium">Calls</th>
                <th className="pb-2 font-medium">Tokens</th>
                <th className="pb-2 font-medium">Cost</th>
                <th className="pb-2 text-right font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const meta = isAgentKey(r.key) ? AGENT_BY_KEY[r.key] : null;
                return (
                  <tr key={r.key} className="border-t border-[var(--border)]">
                    <td className="py-2 pr-3">
                      <span className="flex items-center gap-2 font-medium">
                        <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: meta?.color ?? "var(--text-faint)" }} />
                        {meta?.label ?? r.key}
                        {r.runs > 1 && <span className="font-mono text-[10px] text-[var(--text-faint)]">×{r.runs}</span>}
                      </span>
                    </td>
                    <td className="py-2 pr-3 font-mono tabular-nums text-[var(--text-dim)]">{r.llm_calls}</td>
                    <td className="py-2 pr-3">
                      <Bar value={r.tokens} max={maxTokens} label={formatTokens(r.tokens)} title={`${r.tokens_in} in · ${r.tokens_out} out`} />
                    </td>
                    <td className="py-2 pr-3">
                      <Bar value={r.cost_usd} max={maxCost} label={formatCost(r.cost_usd)} title={`$${r.cost_usd.toFixed(6)}`} />
                    </td>
                    <td className="py-2 text-right font-mono tabular-nums text-[var(--text-dim)]">{formatDuration(r.elapsed_ms)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-[var(--text-faint)]">
          Tokens come from Gemini's own usage metadata, billed to the agent that made the call (including the Researcher's parallel lanes). Cost uses the published paid-tier
          price for the model that answered; on the free tier the actual bill is $0. Agents with time but no calls are waiting on tools.
        </p>
      </div>
    </div>
  );
}

function Bar({ value, max, label, title }: { value: number; max: number; label: string; title: string }) {
  const pct = value > 0 ? Math.max(2, (value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2" title={title}>
      <div className="h-2 w-24 shrink-0 overflow-hidden rounded-full bg-white/[0.05] sm:w-32" role="img" aria-label={title}>
        <div className="grow-x h-full rounded-full bg-[var(--accent)]" style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono tabular-nums text-[var(--text-dim)]">{label}</span>
    </div>
  );
}
