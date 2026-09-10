import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation, ReportResult } from "../api";

// The Writer is told one source_id per bracket, but a model occasionally packs
// several into one anyway (`[rag:a#0, web:1]`) - split those into one chip
// each rather than rendering the whole unmatched bracket as plain text.
const CITE_RE = /\[([A-Za-z0-9_:.#/-]+(?:\s*,\s*[A-Za-z0-9_:.#/-]+)*)\](?!\()/g;

function linkifyCitations(report: string): string {
  return report.replace(CITE_RE, (_match, group: string) =>
    group
      .split(",")
      .map((id) => id.trim())
      .map((id) => `[[${id}]](#cite-${encodeURIComponent(id)})`)
      .join(""),
  );
}

export default function ReportCard({ result }: { result: ReportResult }) {
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const linkified = useMemo(() => linkifyCitations(result.report ?? ""), [result.report]);

  function scrollToCitation(id: string) {
    setHighlighted(id);
    document.getElementById(`cite-${id}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    window.setTimeout(() => setHighlighted((cur) => (cur === id ? null : cur)), 1600);
  }

  const passed = result.status === "passed";

  return (
    <div className="animate-fade-up flex flex-col gap-5">
      <div
        className="flex items-center justify-between rounded-xl border px-4 py-3"
        style={{
          borderColor: passed ? "#3ddc9733" : "#f5b23e33",
          background: passed ? "#3ddc970c" : "#f5b23e0c",
        }}
      >
        <div className="flex items-center gap-2">
          <StatusDot ok={passed} />
          <span className="text-sm font-medium">
            {passed ? "Verified by the Critic" : "Shipped without full verification"}
          </span>
        </div>
        <div className="flex gap-4 text-xs text-[var(--text-faint)]">
          <span>{result.revisions} revision{result.revisions === 1 ? "" : "s"}</span>
          <span>{result.research_rounds} research round{result.research_rounds === 1 ? "" : "s"}</span>
          <span>{result.citations.length} citation{result.citations.length === 1 ? "" : "s"}</span>
        </div>
      </div>

      {!passed && result.critic.unsupported_claims?.length > 0 && (
        <div
          className="rounded-xl border px-4 py-3 text-sm"
          style={{ borderColor: "#f5b23e33", background: "#f5b23e0c", color: "var(--warn)" }}
        >
          <p className="mb-1.5 font-medium">Flagged claims (unsupported by retrieved evidence)</p>
          <ul className="list-inside list-disc space-y-1 text-[var(--text-dim)]">
            {result.critic.unsupported_claims.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}

      <article
        className="prose-invert max-w-none rounded-2xl border px-6 py-5 text-[14.5px] leading-relaxed"
        style={{ borderColor: "var(--border)", background: "var(--panel)" }}
      >
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              if (href?.startsWith("#cite-")) {
                const id = decodeURIComponent(href.slice(6));
                const known = result.citations.some((c) => c.source_id === id);
                return (
                  <button
                    type="button"
                    onClick={() => known && scrollToCitation(id)}
                    className="mx-0.5 inline-flex translate-y-[-1px] cursor-pointer items-center rounded-md border px-1.5 py-0.5 align-middle font-mono text-[11px] font-medium no-underline transition hover:brightness-125"
                    style={{
                      borderColor: known ? "var(--accent)" : "var(--border)",
                      background: known ? "var(--accent-soft)" : "transparent",
                      color: known ? "var(--accent-strong)" : "var(--text-faint)",
                    }}
                  >
                    {children}
                  </button>
                );
              }
              return (
                <a href={href} target="_blank" rel="noreferrer" className="text-[var(--accent-strong)]">
                  {children}
                </a>
              );
            },
            p: ({ children }) => <p className="mb-3 last:mb-0">{children}</p>,
          }}
        >
          {linkified}
        </ReactMarkdown>
      </article>

      {result.citations.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-[var(--text-faint)]">
            Sources ({result.citations.length})
          </h3>
          <div className="flex flex-col gap-2">
            {result.citations.map((c) => (
              <CitationRow key={c.source_id} citation={c} highlighted={highlighted === c.source_id} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CitationRow({ citation, highlighted }: { citation: Citation; highlighted: boolean }) {
  const isWeb = citation.type === "web";
  return (
    <div
      id={`cite-${citation.source_id}`}
      className="flex items-start gap-3 rounded-xl border px-3.5 py-3 transition-colors duration-300"
      style={{
        borderColor: highlighted ? "var(--accent)" : "var(--border)",
        background: highlighted ? "var(--accent-soft)" : "var(--bg-elevated)",
      }}
    >
      <span
        className="mt-0.5 shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
        style={{
          background: isWeb ? "#3ddc9722" : "#7c6dfa22",
          color: isWeb ? "var(--ok)" : "var(--accent-strong)",
        }}
      >
        {isWeb ? "web" : "rag"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate font-mono text-[11px] text-[var(--text-faint)]">{citation.source_id}</div>
        {isWeb ? (
          <a
            href={citation.url}
            target="_blank"
            rel="noreferrer"
            className="block truncate text-sm text-[var(--accent-strong)] hover:underline"
          >
            {citation.title || citation.url}
          </a>
        ) : (
          <div className="truncate text-sm">
            {citation.file}
            {citation.chunk_index !== undefined && (
              <span className="text-[var(--text-faint)]"> · chunk {citation.chunk_index}</span>
            )}
          </div>
        )}
      </div>
      {citation.score !== undefined && (
        <div className="shrink-0 pt-0.5 text-right">
          <div className="font-mono text-[11px] text-[var(--text-faint)]">{citation.score.toFixed(2)}</div>
        </div>
      )}
    </div>
  );
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className="h-2 w-2 rounded-full"
      style={{ background: ok ? "var(--ok)" : "var(--warn)" }}
    />
  );
}
