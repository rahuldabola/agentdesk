import type { RunUsage, TraceEntry, UsageCounts } from "../api";

export function formatTokens(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/** Sub-cent costs are the norm here, so keep significant digits instead of rounding to $0.00. */
export function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toPrecision(2)}`;
  return `$${usd.toFixed(usd < 1 ? 3 : 2)}`;
}

/**
 * Usage for a run: the server's summary when present, else rebuilt from the trace
 * (a run still streaming, or reattached from history).
 */
export function runUsage(trace: TraceEntry[], server?: RunUsage | null): RunUsage {
  if (server) return server;
  const blank = (): UsageCounts => ({ llm_calls: 0, tokens_in: 0, tokens_out: 0, cost_usd: 0, elapsed_ms: 0 });
  const total = blank();
  const by_agent: RunUsage["by_agent"] = {};
  for (const e of trace) {
    const agent = (by_agent[e.node] ??= { ...blank(), runs: 0 });
    agent.runs += 1;
    for (const u of [total, agent]) {
      u.llm_calls += e.llm_calls ?? 0;
      u.tokens_in += e.tokens_in ?? 0;
      u.tokens_out += e.tokens_out ?? 0;
      u.cost_usd += e.cost_usd ?? 0;
      u.elapsed_ms += e.elapsed_ms;
    }
  }
  return { ...total, by_agent };
}
