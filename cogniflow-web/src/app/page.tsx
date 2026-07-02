import Link from "next/link";
import { ArrowRight, Clock, Code, Network, Server, ShieldCheck } from "lucide-react";
import demo from "@/data/demo_data.json";
import fw from "@/data/benchmark_frameworks.json";
import { displayName, site } from "@/lib/site";
import { LinkButton } from "@/components/ui/link-button";
import { Reveal } from "@/components/site/reveal";
import { RagFlow } from "@/components/landing/rag-flow";
import { CapabilityClasses } from "@/components/landing/capability-classes";
import { FrameworkChart, type SysDatum } from "@/components/landing/framework-chart";

const clean = (s: string) => s.replace(/\*\*/g, "").trim();
const H = demo.as_of_headline;

type Sys = { name: string; kind: string; as_of: { n: number; score: number } };
const systems = fw.systems as unknown as Sys[];
const bn = systems[0]?.as_of.n ?? 4;
const asofData: SysDatum[] = systems.map((s) => ({ name: displayName(s.name), score: s.as_of.score, n: bn }));

const boundaries = [
  {
    t: "Provider-agnostic by design",
    d: "The LLM, embedder, reranker, and graph backend are plugins - bring a hosted API or a local model. Nothing is hard-wired to a vendor. The bi-temporal platform is the product.",
  },
  {
    t: "Structured input is deterministic",
    d: "Facts you assert get precise temporal validity. Facts extracted from raw prose are as good as the extraction model - each served fact is confidence-labeled, so nothing is laundered.",
  },
  {
    t: "Read-only audit surface",
    d: "The replay dashboard is a window onto the ledger, never a second product; the answer path never writes. What you see is what the system actually held.",
  },
];

export default function Home() {
  return (
    <>
      {/* HERO */}
      <section className="relative overflow-hidden">
        <div className="relative mx-auto max-w-6xl px-5 pb-16 pt-20 sm:pt-28">
          <Reveal>
            <p className="eyebrow mb-5">Bi-temporal RAG platform · self-hostable · open source</p>
          </Reveal>
          <Reveal delay={0.05}>
            <h1 className="text-hero max-w-[18ch]">
              The <span className="text-gradient">auditable, self-hostable</span> belief ledger
              for agents.
            </h1>
          </Reveal>
          <Reveal delay={0.1}>
            <p className="text-subhead mt-6 max-w-[62ch]">
              A complete RAG platform with a memory that remembers <em>when</em>. Upload any
              document, ask what your system believed at any past moment - and prove it.
              Temporally-correct context and cited answers, in your own environment, with any model.
            </p>
          </Reveal>
          <Reveal delay={0.15}>
            <div className="mt-9 flex flex-wrap gap-3">
              <LinkButton href="/playground" size="lg" className="h-12 px-6 text-[15px] font-semibold">
                Try the playground <ArrowRight className="size-4" />
              </LinkButton>
              <LinkButton href="/docs" size="lg" variant="outline" className="h-12 px-6 text-[15px]">
                Deploy it
              </LinkButton>
            </div>
          </Reveal>

          <Reveal delay={0.2}>
            <div className="ring-glow mesh-panel mt-14 max-w-3xl rounded-xl p-6">
              <div className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
                <Clock className="size-3.5 text-brand" />
                Real captured run · {H.query}
              </div>
              <dl className="space-y-3 text-[15px]">
                <Row k="Cogniflow · as of 2015" v={clean(H.past_2015.answer)} good />
                <Row k="Cogniflow · now" v={clean(H.now.answer)} good />
                <Row k="Plain RAG · as of 2015" v="Can't answer it at all - no temporal axis." bad />
              </dl>
            </div>
          </Reveal>
        </div>
      </section>

      {/* HOW IT WORKS - the animated RAG infrastructure */}
      <section className="mx-auto max-w-6xl px-5 py-10">
        <div className="section-box p-7 sm:p-10">
          <Reveal>
            <p className="eyebrow mb-4">The infrastructure</p>
            <h2 className="text-section max-w-[24ch]">One pipeline, from any document to a cited, temporally-correct answer</h2>
            <p className="text-subhead mt-4 max-w-[62ch]">
              Every stage is ours and every stage is pluggable. The bi-temporal knowledge graph at
              the center is what lets the platform answer &ldquo;as of when.&rdquo;
            </p>
          </Reveal>
          <div className="mt-8">
            <RagFlow />
          </div>
        </div>
      </section>

      {/* CAPABILITY CLASSES: Plain vs Temporal vs Bitemporal */}
      <Section eyebrow="What sets it apart" title="Plain RAG. Temporal RAG. Bitemporal RAG.">
        <p className="text-subhead max-w-[64ch]">
          Recall is table stakes - every RAG answers &ldquo;what&rsquo;s true now.&rdquo;
          A temporal RAG can answer &ldquo;what was true then.&rdquo; Only a <b>bitemporal</b>
          {" "}platform also answers <b>what the system knew</b>, when a fact changed, and can
          replay a belief that was corrected later. That last class is Cogniflow.
        </p>
        <div className="mt-8">
          <CapabilityClasses />
        </div>
      </Section>

      {/* BENCHMARK - real names, lead with the as-of difference */}
      <Section eyebrow="Real benchmark - every number from a live run" title="Where it isn't close">
        <p className="text-subhead max-w-[64ch]">
          Same corpus, same model, same embeddings across every system - only the memory
          differs. On current facts, everyone ties. On <b>as-of</b> questions (what was true at a
          past date), only Cogniflow answers correctly.
        </p>
        <div className="mt-8 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
          <div className="rounded-xl border border-border bg-card p-6 elev">
            <div className="mb-1 text-sm font-semibold">As-of questions - score out of {bn}</div>
            <p className="mb-4 text-xs text-muted-foreground">The past, answered correctly.</p>
            <FrameworkChart data={asofData} n={bn} />
          </div>
          <div className="flex flex-col justify-center gap-3">
            <div className="rounded-lg border border-border bg-card p-4 elev">
              <div className="text-xs text-muted-foreground">Current-fact questions</div>
              <div className="mt-1 text-sm text-foreground">Everyone ties - recall is table stakes.</div>
            </div>
            <div className="ring-glow rounded-lg border border-brand/30 bg-brand/[0.05] p-4">
              <div className="text-xs text-muted-foreground">As-of questions</div>
              <div className="mt-1 text-sm">
                <span className="font-semibold text-brand">Cogniflow {systems.find((s) => s.name.startsWith("Cogniflow"))?.as_of.score}/{bn}</span>
                <span className="text-muted-foreground"> · every other system 0/{bn}</span>
              </div>
            </div>
            <Link href="/benchmark" className="inline-flex items-center gap-1.5 text-sm font-medium text-brand hover:underline">
              Full benchmark, real names &amp; the actual answers <ArrowRight className="size-4" />
            </Link>
          </div>
        </div>
      </Section>

      {/* BOUNDARIES */}
      <Section eyebrow="Honesty is the platform" title="Built to be trusted">
        <div className="mt-6 grid gap-4 md:grid-cols-3">
          {boundaries.map((b) => (
            <div key={b.t} className="rounded-xl border border-border bg-card p-6 elev">
              <h3 className="text-headline mb-2">{b.t}</h3>
              <p className="text-sm text-muted-foreground">{b.d}</p>
            </div>
          ))}
        </div>
      </Section>

      {/* CTA BAND */}
      <section className="mx-auto max-w-6xl px-5 py-10">
        <div className="section-box overflow-hidden">
          <div className="mesh-panel !border-0 px-5 py-16 text-center sm:py-20">
            <Reveal>
              <h2 className="text-section mx-auto max-w-[22ch]">
                Run the whole platform in your own environment.
              </h2>
              <div className="mt-8 flex flex-wrap justify-center gap-3">
                <LinkButton href="/docs" size="lg" className="h-12 px-6 font-semibold">
                  Deploy Cogniflow <ArrowRight className="size-4" />
                </LinkButton>
                <LinkButton href={site.repo} external size="lg" variant="outline" className="h-12 px-6">
                  <Code className="size-4" /> Read the code
                </LinkButton>
              </div>
              <div className="mt-10 flex flex-wrap justify-center gap-x-8 gap-y-3 text-sm text-muted-foreground">
                <Feature icon={<Clock className="size-4 text-brand" />} t="As-of replay" />
                <Feature icon={<ShieldCheck className="size-4 text-brand" />} t="Auditable provenance" />
                <Feature icon={<Network className="size-4 text-brand" />} t="Any model, pluggable" />
                <Feature icon={<Server className="size-4 text-brand" />} t="Self-hostable" />
              </div>
            </Reveal>
          </div>
        </div>
      </section>
    </>
  );
}

function Section({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <section className="mx-auto max-w-6xl px-5 py-10">
      <div className="section-box p-7 sm:p-10">
        <Reveal>
          <p className="eyebrow mb-4">{eyebrow}</p>
          <h2 className="text-section max-w-[24ch]">{title}</h2>
        </Reveal>
        <div className="mt-6">{children}</div>
      </div>
    </section>
  );
}

function Row({ k, v, good, bad }: { k: string; v: string; good?: boolean; bad?: boolean }) {
  return (
    <div className="flex flex-col gap-1 sm:flex-row sm:items-baseline sm:gap-4">
      <dt className="w-40 shrink-0 text-xs text-muted-foreground">{k}</dt>
      <dd className={bad ? "text-danger" : good ? "text-brand" : "text-foreground"}>{v}</dd>
    </div>
  );
}

function Feature({ icon, t }: { icon: React.ReactNode; t: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      {icon} {t}
    </span>
  );
}
