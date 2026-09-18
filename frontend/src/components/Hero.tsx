import { motion } from "motion/react";
import { BookOpen, FileText, Globe, Layers, MousePointer2, Sparkles } from "lucide-react";
import { lazy, Suspense, useState, type ReactNode } from "react";
import { AGENT_BY_KEY, AGENTS, type AgentKey } from "../lib/agents";
import { EXAMPLES, KNOWLEDGE_BASE } from "../lib/content";
import { AGENT_ICONS } from "../lib/icons";
import TiltCard from "./TiltCard";

const AgentOrbit = lazy(() => import("../three/AgentOrbit"));

const CATEGORY_ICON = { "Knowledge base": BookOpen, Web: Globe, Hybrid: Layers } as const;
const EMPTY_VISITS = new Map<string, number>();

export default function Hero({ composer, onAsk }: { composer: ReactNode; onAsk: (q: string) => void }) {
  const [highlight, setHighlight] = useState<AgentKey | null>(null);
  const [selected, setSelected] = useState<AgentKey>("planner");
  const selectedMeta = AGENT_BY_KEY[selected];
  const SelectedIcon = AGENT_ICONS[selected];

  return (
    <div className="flex flex-col gap-14 pb-10">
      <section className="flex flex-col items-center text-center">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass mb-5 inline-flex items-center gap-2 rounded-full px-3 py-1 text-[11.5px] text-[var(--text-dim)]"
        >
          <Sparkles size={12} className="text-[var(--accent-strong)]" />
          5 agents · LangGraph · MCP tools · RAG + web
        </motion.div>
        <motion.h1
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="gradient-text max-w-2xl text-[2rem] font-bold leading-[1.1] tracking-tight sm:text-5xl"
        >
          Ask once. Get a cited, fact-checked report.
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="mt-4 max-w-lg text-[15px] leading-relaxed text-[var(--text-dim)]"
        >
          A team of AI agents plans, researches, extracts facts, writes and cross-examines every claim, so each sentence traces back to a real source.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, scale: 0.96 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.15, duration: 0.6 }}
          className="relative -mx-4 mt-2 w-[calc(100%+2rem)] sm:mx-0 sm:w-full"
        >
          <Suspense fallback={<div className="h-[320px] sm:h-[400px]" />}>
            <AgentOrbit
              demo
              active={null}
              visits={EMPTY_VISITS}
              lastNode={null}
              running={false}
              done={false}
              highlight={highlight}
              onSelectAgent={(key) => {
                setSelected(key);
                document.getElementById("how-it-works")?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
              className="h-[320px] sm:h-[400px]"
            />
          </Suspense>
          <div className="pointer-events-none absolute bottom-2 left-1/2 flex -translate-x-1/2 items-center gap-1.5 text-[11px] text-[var(--text-faint)]">
            <MousePointer2 size={11} />
            <span className="pointer-coarse:hidden">Drag to orbit · click an agent to learn what it does</span>
            <span className="hidden pointer-coarse:inline">Tap an agent to learn what it does</span>
          </div>
        </motion.div>

        <div className="w-full">{composer}</div>
      </section>

      <section aria-labelledby="examples-heading">
        <SectionHeading id="examples-heading" kicker="Try one" title="Example questions" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {EXAMPLES.map((ex, i) => {
            const Icon = CATEGORY_ICON[ex.category];
            return (
              <motion.div key={ex.question} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.25 + i * 0.05 }}>
                <TiltCard
                  as="button"
                  onClick={() => onAsk(ex.question)}
                  className="glass group flex h-full w-full flex-col items-start gap-3 rounded-2xl p-4 text-left hover:border-[var(--border-strong)]"
                >
                  <span className="flex items-center gap-1.5 rounded-full bg-white/[0.04] px-2 py-0.5 text-[10.5px] font-medium text-[var(--text-dim)]">
                    <Icon size={11} /> {ex.category}
                  </span>
                  <span className="text-[13.5px] leading-snug text-[var(--text)]">{ex.question}</span>
                  <span className="mt-auto text-[11px] font-medium text-[var(--accent-strong)] opacity-0 transition group-hover:opacity-100">
                    Run this →
                  </span>
                </TiltCard>
              </motion.div>
            );
          })}
        </div>
      </section>

      <section id="how-it-works" aria-labelledby="how-heading" className="scroll-mt-6">
        <SectionHeading id="how-heading" kicker="Under the hood" title="How it works" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {AGENTS.map((agent, i) => {
            const Icon = AGENT_ICONS[agent.key];
            const isSel = selected === agent.key;
            return (
              <TiltCard
                key={agent.key}
                as="button"
                max={12}
                onClick={() => setSelected(agent.key)}
                onMouseEnter={() => setHighlight(agent.key)}
                onMouseLeave={() => setHighlight(null)}
                className={`glass flex flex-col items-start gap-2.5 rounded-2xl p-3.5 text-left ${i === 4 ? "col-span-2 sm:col-span-1" : ""}`}
                style={{
                  borderColor: isSel ? agent.color : undefined,
                  boxShadow: isSel ? `0 0 0 1px ${agent.color}, 0 18px 40px -22px ${agent.color}` : undefined,
                }}
              >
                <div className="flex w-full items-center justify-between">
                  <span className="flex h-8 w-8 items-center justify-center rounded-xl" style={{ background: `${agent.color}22`, color: agent.color }}>
                    <Icon size={16} />
                  </span>
                  <span className="font-mono text-[10px] text-[var(--text-faint)]">0{i + 1}</span>
                </div>
                <div>
                  <div className="text-sm font-semibold">{agent.label}</div>
                  <div className="text-[11.5px] text-[var(--text-dim)]">{agent.blurb}</div>
                </div>
              </TiltCard>
            );
          })}
        </div>
        <div key={selected} className="glass animate-fade-up mt-3 flex items-start gap-3 rounded-2xl p-4">
            <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl" style={{ background: `${selectedMeta.color}22`, color: selectedMeta.color }}>
              <SelectedIcon size={17} />
            </span>
            <div>
              <div className="text-sm font-semibold">{selectedMeta.label}</div>
              <p className="mt-0.5 text-[13px] leading-relaxed text-[var(--text-dim)]">{selectedMeta.description}</p>
            </div>
        </div>
        <p className="mt-3 text-center text-[12px] text-[var(--text-faint)]">
          The Critic can loop a draft back up to the revision limit. A report that never passes is still delivered, clearly marked unverified.
        </p>
      </section>

      <section id="knowledge-base" aria-labelledby="kb-heading" className="scroll-mt-6">
        <SectionHeading
          id="kb-heading"
          kicker="What it knows"
          title="Knowledge base"
          subtitle="Internal docs indexed for retrieval. Anything outside them is answered from live web search."
        />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {KNOWLEDGE_BASE.map((doc) => (
            <TiltCard key={doc.file} className="glass flex flex-col gap-2.5 rounded-2xl p-4">
              <div className="flex items-center gap-2">
                <FileText size={14} className="shrink-0 text-[var(--accent-strong)]" />
                <span className="truncate text-[13px] font-semibold">{doc.title}</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {doc.topics.map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => onAsk(`What does our ${doc.title.toLowerCase()} say about ${t.toLowerCase()}?`)}
                    title={`Ask about ${t}`}
                    className="rounded-md bg-white/[0.04] px-1.5 py-0.5 text-[10.5px] text-[var(--text-dim)] transition hover:bg-[var(--accent-soft)] hover:text-[var(--text)]"
                  >
                    {t}
                  </button>
                ))}
              </div>
              <span className="mt-auto font-mono text-[10px] text-[var(--text-faint)]">{doc.file}</span>
            </TiltCard>
          ))}
        </div>
      </section>
    </div>
  );
}

function SectionHeading({ id, kicker, title, subtitle }: { id: string; kicker: string; title: string; subtitle?: string }) {
  return (
    <div className="mb-4">
      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-[var(--accent-strong)]">{kicker}</div>
      <h2 id={id} className="mt-1 text-xl font-semibold tracking-tight">
        {title}
      </h2>
      {subtitle && <p className="mt-1 text-[13px] text-[var(--text-dim)]">{subtitle}</p>}
    </div>
  );
}
