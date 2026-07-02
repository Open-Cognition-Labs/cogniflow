"use client";

import { motion, useReducedMotion } from "framer-motion";
import {
  ArrowDownUp,
  Boxes,
  Clock,
  FileCheck2,
  FileText,
  MessageSquareText,
  Network,
  Scissors,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

type Stage = {
  stage: string;
  title: string;
  desc: string;
  icon: ReactNode;
  hub?: boolean;
};

const STAGES: Stage[] = [
  { stage: "Ingest", title: "Documents in", desc: "Any PDF, markdown, or text - with the date each fact was true.", icon: <FileText className="size-5" /> },
  { stage: "Ingest", title: "Parse & chunk", desc: "Structure-preserving chunks; tables and sections kept intact.", icon: <Scissors className="size-5" /> },
  { stage: "Ingest", title: "Embed", desc: "Semantic vectors for meaning-based recall.", icon: <Boxes className="size-5" /> },
  { stage: "Memory", title: "Bi-temporal knowledge graph", desc: "Facts stored bi-temporally - when they were true, and when we learned them. The core.", icon: <Network className="size-5" />, hub: true },
  { stage: "Answer", title: "As-of retrieval", desc: "Filter context to the moment you ask about - the past, correctly un-known.", icon: <Clock className="size-5" /> },
  { stage: "Answer", title: "Rerank", desc: "Optional cross-encoder sharpens ranking - on by evidence.", icon: <ArrowDownUp className="size-5" /> },
  { stage: "Answer", title: "Grounded generation", desc: "Answer only from the retrieved facts - no leaking the present into the past.", icon: <MessageSquareText className="size-5" /> },
  { stage: "Answer", title: "Cited answer", desc: "Every claim traces to a fact, and every fact to a document.", icon: <FileCheck2 className="size-5" /> },
];

const STEP_MS = 950;

export function RagFlow() {
  const reduce = useReducedMotion();
  // -1 = nothing active (reduced motion / SSR). Advances through the pipeline on a loop.
  const [active, setActive] = useState(-1);

  useEffect(() => {
    if (reduce) return;
    setActive(0);
    const id = setInterval(() => setActive((a) => (a + 1) % STAGES.length), STEP_MS);
    return () => clearInterval(id);
  }, [reduce]);

  return (
    <div className="relative">
      {/* spine */}
      <div className="absolute left-[27px] top-2 bottom-2 w-px bg-border sm:left-[31px]" aria-hidden />
      {!reduce && (
        <>
          {/* two staggered data packets flowing down the spine */}
          {[0, 2.25].map((delay) => (
            <motion.div
              key={delay}
              aria-hidden
              className="absolute left-[24px] size-2.5 rounded-full bg-brand sm:left-[28px]"
              style={{ boxShadow: "0 0 16px 3px color-mix(in oklab, var(--brand) 60%, transparent)" }}
              initial={{ top: "0%", opacity: 0 }}
              animate={{ top: ["0%", "100%"], opacity: [0, 1, 1, 0] }}
              transition={{ duration: 4.5, repeat: Infinity, ease: "easeInOut", delay }}
            />
          ))}
        </>
      )}

      <ol className="space-y-3">
        {STAGES.map((s, i) => {
          const on = i === active;
          return (
            <motion.li
              key={s.title}
              className="relative flex gap-4 pl-0"
              initial={reduce ? false : { opacity: 0, x: 12 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.45, delay: i * 0.06, ease: [0.22, 1, 0.36, 1] }}
            >
              <div className="relative">
                {/* activation ping ring */}
                {!reduce && on && (
                  <motion.span
                    aria-hidden
                    className="absolute inset-0 z-0 rounded-2xl"
                    style={{ boxShadow: "0 0 0 2px color-mix(in oklab, var(--brand) 55%, transparent)" }}
                    initial={{ opacity: 0.7, scale: 1 }}
                    animate={{ opacity: 0, scale: 1.45 }}
                    transition={{ duration: 0.9, ease: "easeOut" }}
                  />
                )}
                <motion.div
                  className={`relative z-10 flex size-14 shrink-0 items-center justify-center rounded-2xl border transition-colors duration-300 ${
                    s.hub
                      ? "border-brand/40 bg-brand/10 text-brand ring-glow"
                      : on
                        ? "border-brand/50 bg-brand/10 text-brand"
                        : "border-border bg-card text-foreground elev"
                  }`}
                  animate={reduce ? undefined : { scale: on ? 1.08 : 1 }}
                  transition={{ type: "spring", stiffness: 320, damping: 20 }}
                >
                  {s.icon}
                </motion.div>
              </div>
              <div
                className={`flex-1 rounded-xl border p-4 transition-colors duration-300 ${
                  s.hub
                    ? "border-brand/30 bg-brand/[0.04]"
                    : on
                      ? "border-brand/40 bg-brand/[0.035]"
                      : "border-border bg-card"
                } elev`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-semibold uppercase tracking-wider text-brand">
                    {s.stage}
                  </span>
                  <span className="text-xs text-muted-foreground">step {i + 1}</span>
                  {!reduce && on && (
                    <motion.span
                      className="ml-auto inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-brand"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                    >
                      <span className="size-1.5 rounded-full bg-brand" /> processing
                    </motion.span>
                  )}
                </div>
                <div className="mt-0.5 font-display text-[15px] font-semibold">{s.title}</div>
                <p className="mt-1 text-sm text-muted-foreground">{s.desc}</p>
              </div>
            </motion.li>
          );
        })}
      </ol>
    </div>
  );
}
