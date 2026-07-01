import type { Metadata } from "next";
import { Check, X } from "lucide-react";
import fw from "@/data/benchmark_frameworks.json";
import { displayName } from "@/lib/site";
import { Reveal } from "@/components/site/reveal";
import { FrameworkChart, type SysDatum } from "@/components/landing/framework-chart";
import { LandscapeCompare } from "@/components/landing/landscape-compare";

export const metadata: Metadata = { title: "Benchmark" };

type Row = { q: string; expect: string; answer: string; hit: boolean };
type Panel = { n: number; score: number; rows: Row[] };
type Sys = { name: string; kind: string; standard: Panel; as_of: Panel };

const systems = fw.systems as unknown as Sys[];
const n = systems[0]?.as_of.n ?? 4;
const asofData: SysDatum[] = systems.map((s) => ({ name: displayName(s.name), score: s.as_of.score, n }));
const stdData: SysDatum[] = systems.map((s) => ({ name: displayName(s.name), score: s.standard.score, n }));
// Provenance stamp: makes "reproducible" verifiable, not asserted (freshness + integrity hash).
const prov = fw as unknown as { captured_at: string; content_hash?: string; reproduce?: string };

export default function BenchmarkPage() {
  return (
    <div className="mx-auto max-w-6xl px-5 py-12">
      <Reveal>
        <p className="eyebrow mb-3">Real benchmark — every number from a live run</p>
        <h1 className="text-hero mb-3 !text-[clamp(2rem,4vw,3rem)]">
          The same question, asked about the past.
        </h1>
        <p className="text-subhead mb-8 max-w-[68ch]">
          Every system runs on the same fictional corpus with the same model &mdash; only the
          memory layer differs. On current facts they tie; that&rsquo;s table stakes. The
          difference is <b>as-of</b> questions: what was true at a past date. Only Cogniflow
          answers them correctly.
        </p>
      </Reveal>

      {/* AS-OF: the headline chart */}
      <Reveal>
        <div className="ring-glow rounded-2xl border border-brand/25 bg-card p-6 elev sm:p-8">
          <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
            As-of questions — the difference
            <span className="rounded-full border border-win/30 bg-win/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-win">
              Measured
            </span>
          </div>
          <p className="mb-5 text-xs text-muted-foreground">Score out of {n} on past-date questions.</p>
          <FrameworkChart data={asofData} n={n} />
        </div>
      </Reveal>

      {/* current facts + summary */}
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Reveal>
          <div className="rounded-2xl border border-border bg-card p-6 elev">
            <div className="mb-1 text-sm font-semibold">Current-fact questions</div>
            <p className="mb-5 text-xs text-muted-foreground">Stable facts &mdash; everyone can do this.</p>
            <FrameworkChart data={stdData} n={n} />
          </div>
        </Reveal>
        <Reveal delay={0.05}>
          <div className="overflow-hidden rounded-2xl border border-border bg-card elev">
            <table className="w-full text-left text-sm">
              <thead className="bg-secondary/60 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-5 py-3 font-semibold">System</th>
                  <th className="px-5 py-3 font-semibold">Current</th>
                  <th className="px-5 py-3 font-semibold">As-of</th>
                </tr>
              </thead>
              <tbody>
                {systems.map((s) => {
                  const cf = s.name.startsWith("Cogniflow");
                  return (
                    <tr key={s.name} className="border-t border-border">
                      <td className={`px-5 py-3 ${cf ? "font-semibold text-brand" : "text-foreground"}`}>
                        {displayName(s.name)}
                        <span className="ml-2 text-xs font-normal text-muted-foreground">{s.kind}</span>
                      </td>
                      <td className="px-5 py-3">{s.standard.score}/{s.standard.n}</td>
                      <td className={`px-5 py-3 font-semibold ${s.as_of.score >= n ? "text-brand" : s.as_of.score === 0 ? "text-danger" : "text-warn"}`}>
                        {s.as_of.score}/{s.as_of.n}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Reveal>
      </div>

      {/* drill-down: the actual answers */}
      <div className="mt-12">
        <Reveal>
          <h2 className="text-section mb-2">The actual answers</h2>
          <p className="mb-5 text-sm text-muted-foreground">
            No cherry-picking &mdash; every system&rsquo;s real output on the past-date questions.
          </p>
        </Reveal>
        <div className="space-y-3">
          {systems.map((s) => (
            <details key={s.name} className="group rounded-xl border border-border bg-card elev">
              <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-4 text-sm">
                <span className={s.name.startsWith("Cogniflow") ? "font-semibold text-brand" : "font-medium"}>
                  {displayName(s.name)}
                </span>
                <span className="text-xs text-muted-foreground">{s.kind}</span>
                <span className={`ml-auto text-xs font-semibold ${s.as_of.score >= n ? "text-brand" : "text-muted-foreground"}`}>
                  as-of {s.as_of.score}/{s.as_of.n}
                </span>
              </summary>
              <div className="space-y-3 border-t border-border px-5 py-4">
                {s.as_of.rows.map((r, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm">
                    {r.hit ? (
                      <Check className="mt-0.5 size-4 shrink-0 text-brand" />
                    ) : (
                      <X className="mt-0.5 size-4 shrink-0 text-danger" />
                    )}
                    <div>
                      <div className="text-muted-foreground">
                        {r.q} <span className="text-foreground">→ expected {r.expect}</span>
                      </div>
                      <div className="mt-0.5">{r.answer}</div>
                    </div>
                  </div>
                ))}
              </div>
            </details>
          ))}
        </div>
      </div>

      {/* capability landscape */}
      <div className="mt-12">
        <Reveal>
          <h2 className="text-section mb-2 flex flex-wrap items-center gap-2">
            How Cogniflow compares to the temporal-RAG field
            <span className="rounded-full border border-warn/40 bg-warn/10 px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide text-warn">
              Assessment · not measured
            </span>
          </h2>
          <p className="mb-5 max-w-[68ch] text-sm text-muted-foreground">
            A capability comparison &mdash; not a measured run. Most temporal-RAG systems retrieve
            the right facts for a given time. A <b className="text-foreground">bitemporal</b>{" "}
            platform also separates when a fact was true from when it was learned, replays past
            beliefs, tracks falsification when facts are corrected, and audits provenance.
          </p>
          <LandscapeCompare />
        </Reveal>
      </div>

      {/* methodology */}
      <div className="section-box mt-12 p-7">
        <h2 className="text-headline mb-3">Methodology — why you can trust these numbers</h2>
        <ul className="space-y-2 text-sm text-muted-foreground">
          <li>• <b className="text-foreground">Fictional corpus</b>: invented companies and cities, with dates only in metadata — so no model can answer as-of questions from training (on famous entities a large model scores well from memory; that would be a fake win).</li>
          <li>• <b className="text-foreground">The same model</b> for every system — the only difference is the memory and retrieval layer.</li>
          <li>• <b className="text-foreground">Strict as-of scoring</b>: correct only if the answer names the right past fact and not the superseded one (a hedge that lists both is not an answer).</li>
          <li>• <b className="text-foreground">Reproducible &amp; verifiable</b>: one command re-runs every system on your own machine, and the published numbers carry an integrity hash you can recompute from the served data — not an asserted claim.</li>
        </ul>
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-border bg-secondary/30 px-4 py-3 font-mono text-[11px] text-muted-foreground">
          <span>measured {String(prov.captured_at).slice(0, 10)}</span>
          <span>reproduce: <span className="text-foreground">{prov.reproduce ?? "python demo/benchmark_frameworks.py"}</span></span>
          {prov.content_hash && <span>integrity: {prov.content_hash.slice(0, 23)}…</span>}
        </div>
      </div>
    </div>
  );
}
