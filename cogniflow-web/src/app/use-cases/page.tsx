import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, Building2, History, Landmark, Lock, LifeBuoy, ShieldCheck } from "lucide-react";
import { Reveal } from "@/components/site/reveal";
import { LinkButton } from "@/components/ui/link-button";

export const metadata: Metadata = { title: "Use cases" };

const CASES = [
  {
    icon: ShieldCheck,
    title: "Compliance & audit",
    body: "Reconstruct exactly what the system knew at any prior date. When a regulator or auditor asks 'what did you know, and when,' you answer with a replayable, cited record - not a guess.",
  },
  {
    icon: Landmark,
    title: "Financial & legal agents",
    body: "Decisions must cite the fact that was valid at decision time, not today's. Cogniflow serves the as-of truth and the provenance behind it, so every answer is defensible after the fact.",
  },
  {
    icon: LifeBuoy,
    title: "Support & operations knowledge",
    body: "Policies, prices, and configs change. Answer 'what was the refund policy in March?' correctly - the version that was live then, not the current one that would mislead.",
  },
  {
    icon: History,
    title: "Agent memory that doesn't rewrite history",
    body: "When a fact changes, most memory silently overwrites the past. Cogniflow supersedes with both timestamps, so an agent can still reason about what it believed before.",
  },
  {
    icon: Lock,
    title: "Regulated, in-VPC deployments",
    body: "Run the whole platform in your own environment with local models - your documents and your embeddings never leave your network. Self-hostable by design.",
  },
  {
    icon: Building2,
    title: "Enterprise knowledge that must be trusted",
    body: "Any answer that could be contested needs provenance and a timeline. Cogniflow makes 'is it still true, and how sure are we' answerable for every fact it serves.",
  },
];

export default function UseCasesPage() {
  return (
    <div className="mx-auto max-w-6xl px-5 py-12">
      <Reveal>
        <p className="eyebrow mb-3">Use cases</p>
        <h1 className="text-hero mb-3 !text-[clamp(2rem,4vw,3rem)]">
          Where &ldquo;what did we believe, and when&rdquo; is the whole job.
        </h1>
        <p className="text-subhead mb-10 max-w-[64ch]">
          Cogniflow earns its place wherever an answer must be defensible after the fact - 
          regulated, audited, or contested domains where the current answer isn&rsquo;t enough
          and you must prove what was known at a past moment.
        </p>
      </Reveal>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {CASES.map((c, i) => {
          const Icon = c.icon;
          return (
            <Reveal key={c.title} delay={i * 0.05}>
              <div className="h-full rounded-2xl border border-border bg-card p-6 elev">
                <div className="mb-4 flex size-11 items-center justify-center rounded-xl border border-brand/30 bg-brand/10 text-brand">
                  <Icon className="size-5" />
                </div>
                <h3 className="text-headline mb-2">{c.title}</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">{c.body}</p>
              </div>
            </Reveal>
          );
        })}
      </div>

      <Reveal>
        <div className="section-box mt-10 flex flex-col items-start gap-5 p-8 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-headline">See it on your own documents.</h2>
            <p className="mt-1 text-sm text-muted-foreground">Upload a PDF and ask a past-date question in the playground.</p>
          </div>
          <LinkButton href="/playground" size="lg" className="h-12 shrink-0 px-6 font-semibold">
            Open the playground <ArrowRight className="size-4" />
          </LinkButton>
        </div>
      </Reveal>
    </div>
  );
}
