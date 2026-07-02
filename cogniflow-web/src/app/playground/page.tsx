"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Clock,
  Database,
  FileCheck2,
  FileText,
  Info,
  Loader2,
  RotateCcw,
  SendHorizontal,
  ShieldCheck,
  TriangleAlert,
  Upload,
} from "lucide-react";
import { toast } from "sonner";
import {
  api,
  confidenceBadgeClass,
  type AnswerResponse,
  type ContextResponse,
  type Health,
  type ServedFact,
} from "@/lib/api";
import { mockAnswer, mockContext, type MockFact } from "@/lib/mock";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { AcmeReplay } from "@/components/playground/acme-replay";

type Doc = { name: string; created: number; superseded: number };
const fmt = (d: string | null) => (d ? d.slice(0, 10) : " - ");

const DEMO = [
  { t: "acme_report_2011", d: "Acme Robotics is headquartered in Calderport.", when: "2011-01-01" },
  { t: "acme_report_2020", d: "Acme Robotics is headquartered in Newhaven.", when: "2020-01-01" },
  { t: "acme_ceo_2014", d: "The CEO of Acme Robotics is Dana Voss.", when: "2014-01-01" },
  { t: "acme_ceo_2021", d: "The CEO of Acme Robotics is Marcus Lund.", when: "2021-01-01" },
];

export default function Playground() {
  const [sid, setSid] = useState<string | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthErr, setHealthErr] = useState(false);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const [query, setQuery] = useState("Where is Acme Robotics headquartered?");
  const [useAsOf, setUseAsOf] = useState(true);
  const [asOf, setAsOf] = useState("2015-01-01");
  const [answer, setAnswer] = useState<AnswerResponse | null>(null);
  const [facts, setFacts] = useState<ServedFact[]>([]);

  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [docDate, setDocDate] = useState("");
  const mock = useRef<MockFact[]>([]);

  useEffect(() => {
    (async () => {
      try {
        setHealth(await api.health());
      } catch {
        setHealthErr(true);
      }
      try {
        const s = localStorage.getItem("cf_session") || (await api.newSession());
        localStorage.setItem("cf_session", s);
        setSid(s);
      } catch {
        setHealthErr(true);
        setSid("browser"); // browser demo mode - handlers use the in-browser engine
      }
    })();
  }, []);

  const asOfValue = useAsOf ? new Date(asOf).toISOString() : null;
  const down = healthErr || (health && !health.falkordb);

  const loadDemo = useCallback(async () => {
    if (!sid) return;
    if (down) {
      DEMO.forEach((x, i) => mock.current.push({ id: `${x.t}-${i}`, statement: x.d, valid_from: x.when, title: x.t }));
      setDocs((d) => [...DEMO.map((x) => ({ name: x.t, created: 1, superseded: 0 })), ...d]);
      toast.success("Demo loaded (browser mode) - set the as-of date to 2013 vs now.");
      return;
    }
    setBusy("demo");
    try {
      const added: Doc[] = [];
      for (const x of DEMO) {
        const r = await api.ingestText(sid, x.d, x.t, x.when);
        added.push({ name: x.t, created: r.facts_created, superseded: r.facts_superseded });
      }
      setDocs((d) => [...added, ...d]);
      toast.success("Demo corpus loaded - set the as-of date to 2013 vs now.");
    } catch (e) {
      toast.error(`Ingest failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }, [sid, down]);

  const onFile = useCallback(
    async (f: File) => {
      if (!sid) return;
      if (down) {
        toast.info("Browser demo mode: paste a fact or load the demo. Start the API to ingest PDFs.");
        return;
      }
      setBusy("upload");
      try {
        const r = await api.ingestFile(sid, f, docDate ? new Date(docDate).toISOString() : undefined);
        setDocs((d) => [{ name: r.document, created: r.facts_created, superseded: r.facts_superseded }, ...d]);
        toast.success(`${r.document}: ${r.facts_created} facts from ${r.chunks} chunks`);
      } catch (e) {
        toast.error(`Upload failed: ${(e as Error).message}`);
      } finally {
        setBusy(null);
      }
    },
    [sid, docDate, down],
  );

  const addText = useCallback(async () => {
    if (!sid || !text.trim()) return;
    if (down) {
      mock.current.push({ id: `${title || "note"}-${mock.current.length}`, statement: text, valid_from: docDate || "2000-01-01", title: title || "note" });
      setDocs((d) => [{ name: title || "note", created: 1, superseded: 0 }, ...d]);
      setText("");
      setTitle("");
      toast.success("Added (browser mode)");
      return;
    }
    setBusy("text");
    try {
      const r = await api.ingestText(sid, text, title || "note", docDate ? new Date(docDate).toISOString() : undefined);
      setDocs((d) => [{ name: r.document, created: r.facts_created, superseded: r.facts_superseded }, ...d]);
      setText("");
      setTitle("");
      toast.success(`Added ${r.facts_created} fact(s)`);
    } catch (e) {
      toast.error(`Ingest failed: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  }, [sid, text, title, docDate, down]);

  const ask = useCallback(
    async (mode: "answer" | "context") => {
      if (!sid || !query.trim()) return;
      setBusy(mode);
      setAnswer(null);
      if (down) {
        setTimeout(() => {
          if (mode === "answer") {
            const r = mockAnswer(mock.current, query, asOfValue);
            setAnswer(r);
            setFacts(r.facts);
          } else {
            setFacts(mockContext(mock.current, query, asOfValue).facts);
          }
          setBusy(null);
        }, 600);
        return;
      }
      try {
        if (mode === "answer") {
          const r = await api.answer(sid, query, asOfValue);
          setAnswer(r);
          setFacts(r.facts);
        } else {
          const r: ContextResponse = await api.context(sid, query, asOfValue);
          setFacts(r.facts);
        }
      } catch (e) {
        toast.error(`${mode} failed: ${(e as Error).message}`);
      } finally {
        setBusy(null);
      }
    },
    [sid, query, asOfValue, down],
  );

  const reset = useCallback(async () => {
    if (!sid) return;
    mock.current = [];
    if (!down) await api.reset(sid).catch(() => {});
    setDocs([]);
    setFacts([]);
    setAnswer(null);
    toast.success("Session reset");
  }, [sid, down]);

  return (
    <div className="mx-auto max-w-6xl px-5 py-12">
      <p className="eyebrow mb-3">Playground</p>
      <h1 className="text-hero mb-3 !text-[clamp(2rem,4vw,3rem)]">Ask &ldquo;as of when?&rdquo;</h1>
      <p className="text-subhead mb-8 max-w-[62ch]">
        Watch the system&rsquo;s belief change with time in the seeded scenario below - then
        bring your own documents.
      </p>

      <AcmeReplay />

      <h2 className="text-section mb-2">Bring your own documents</h2>
      <p className="text-subhead mb-8 max-w-[62ch]">
        Drop in a PDF (or paste text) with the date each fact was true, then ask - and move
        the <b>as-of</b> date to watch the answer change. Real ingestion, real bi-temporal store.
      </p>

      {down && (
        <div className="mb-8 flex items-start gap-3 rounded-xl border border-brand/30 bg-brand/[0.06] p-4 text-sm">
          <Info className="mt-0.5 size-5 shrink-0 text-brand" />
          <div>
            <div className="font-semibold text-foreground">Browser demo mode</div>
            <p className="mt-1 text-muted-foreground">
              Running in your browser - load the demo (or paste facts) and move the as-of
              slider to see it work. To ingest your own PDFs, start the platform API:{" "}
              <code className="rounded bg-secondary px-1.5 py-0.5">python cogniflow-api/main.py</code>.
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        {/* CORPUS */}
        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-card p-5 elev">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <Database className="size-4 text-brand" /> Corpus
            </div>
            <label className="mb-3 block cursor-pointer rounded-lg border border-dashed border-border bg-secondary/40 p-6 text-center transition-colors hover:border-brand/60 hover:bg-secondary">
              {busy === "upload" ? (
                <Loader2 className="mx-auto mb-2 size-6 animate-spin text-brand" />
              ) : (
                <Upload className="mx-auto mb-2 size-6 text-brand" />
              )}
              <div className="text-sm font-medium">Upload a PDF</div>
              <div className="text-xs text-muted-foreground">or markdown / text</div>
              <input
                type="file"
                accept=".pdf,.md,.markdown,.txt,text/*"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
              />
            </label>
            <div className="mb-2 text-xs text-muted-foreground">Or paste a fact / snippet</div>
            <Input placeholder="title (e.g. policy_2020)" value={title} onChange={(e) => setTitle(e.target.value)} className="mb-2" />
            <Textarea placeholder="e.g. Acme Robotics is headquartered in Newhaven." value={text} onChange={(e) => setText(e.target.value)} rows={3} className="mb-2" />
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Valid from</span>
              <Input type="date" value={docDate} onChange={(e) => setDocDate(e.target.value)} className="h-8 w-auto" />
            </div>
            <div className="flex gap-2">
              <button onClick={addText} disabled={!!busy || !text.trim()} className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground disabled:opacity-40">
                {busy === "text" ? <Loader2 className="size-4 animate-spin" /> : "Add fact"}
              </button>
              <button onClick={loadDemo} disabled={!!busy} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-40">
                {busy === "demo" ? <Loader2 className="size-4 animate-spin" /> : "Load demo"}
              </button>
            </div>
          </div>

          <div className="rounded-xl border border-border bg-card p-5 elev">
            <div className="mb-3 flex items-center justify-between text-sm font-semibold">
              <span>Ingested ({docs.length})</span>
              {docs.length > 0 && (
                <button onClick={reset} className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-danger">
                  <RotateCcw className="size-3.5" /> reset
                </button>
              )}
            </div>
            {docs.length === 0 ? (
              <p className="text-xs text-muted-foreground">Nothing yet. Upload a PDF or load the demo.</p>
            ) : (
              <ul className="space-y-2">
                {docs.map((d, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm">
                    <FileText className="size-4 shrink-0 text-muted-foreground" />
                    <span className="truncate">{d.name}</span>
                    <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                      +{d.created}
                      {d.superseded > 0 && <span className="text-warn"> · {d.superseded} superseded</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* ASK + ANSWER */}
        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-card p-5 elev">
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Ask a question about your docs…" className="mb-3 h-11 text-[15px]" />
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex overflow-hidden rounded-lg border border-border">
                <button onClick={() => setUseAsOf(false)} className={`px-3 py-1.5 text-sm ${!useAsOf ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}>Now</button>
                <button onClick={() => setUseAsOf(true)} className={`px-3 py-1.5 text-sm ${useAsOf ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent"}`}>As of</button>
              </div>
              {useAsOf && <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className="h-9 w-auto" />}
              <div className="ml-auto flex gap-2">
                <button onClick={() => ask("context")} disabled={!!busy} className="rounded-md border border-border px-4 py-2 text-sm hover:bg-accent disabled:opacity-40">
                  {busy === "context" ? <Loader2 className="size-4 animate-spin" /> : "Context"}
                </button>
                <button onClick={() => ask("answer")} disabled={!!busy} className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-40">
                  {busy === "answer" ? <Loader2 className="size-4 animate-spin" /> : <><SendHorizontal className="size-4" /> Answer</>}
                </button>
              </div>
            </div>
            <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Clock className="size-3.5 text-brand" />
              {useAsOf ? `Answering as of ${asOf} - the truth at that moment.` : "Answering as of now."}
            </p>
          </div>

          <AnimatePresence>
            {answer && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="ring-glow rounded-xl border border-brand/25 bg-card p-5"
              >
                <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                  <FileCheck2 className="size-3.5 text-brand" /> Cited answer
                </div>
                <p className="text-[15px] leading-relaxed">{answer.answer}</p>
                {Object.keys(answer.confidence).length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {Object.entries(answer.confidence).map(([k, v]) => (
                      <Badge key={k} variant="outline" className={confidenceBadgeClass(k)}>{k} ×{v}</Badge>
                    ))}
                  </div>
                )}
                {/* F2: the post-hoc faithfulness verdict - checked, not just asked */}
                {answer.faithfulness && answer.faithfulness.status === "grounded" && (
                  <div className="mt-3 inline-flex items-center gap-1.5 rounded-full border border-win/30 bg-win/10 px-2.5 py-1 text-xs font-medium text-win">
                    <ShieldCheck className="size-3.5" /> grounded - every claim checked against the served facts
                  </div>
                )}
                {answer.faithfulness && answer.faithfulness.status === "unsupported_claims" && (
                  <div className="mt-3 rounded-lg border border-warn/40 bg-warn/10 p-3 text-xs">
                    <div className="flex items-center gap-1.5 font-semibold text-warn">
                      <TriangleAlert className="size-3.5" />
                      {answer.faithfulness.unsupported_claims.length} claim(s) not supported by the served facts
                    </div>
                    <ul className="mt-1.5 space-y-1 text-muted-foreground">
                      {answer.faithfulness.unsupported_claims.map((c, i) => (
                        <li key={i} className="line-through decoration-warn/60">{c}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>

          <div className="rounded-xl border border-border bg-card p-5 elev">
            <div className="mb-3 text-sm font-semibold">
              {answer ? "Facts it stood on" : "Retrieved context"} ({facts.length})
            </div>
            {facts.length === 0 ? (
              <p className="text-sm text-muted-foreground">Ask a question to see the temporally-correct facts and their provenance.</p>
            ) : (
              <ul className="space-y-3">
                {facts.map((f) => <FactCard key={f.belief_id} f={f} />)}
              </ul>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}

function FactCard({ f }: { f: ServedFact }) {
  return (
    <li className="rounded-lg border border-border p-3">
      <div className={`text-sm ${f.invalid_at ? "text-muted-foreground line-through" : "text-foreground"}`}>{f.statement}</div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline" className={confidenceBadgeClass(f.valid_at_source)}>{f.valid_at_source}</Badge>
        <span>valid {fmt(f.valid_at)} → {f.invalid_at ? fmt(f.invalid_at) : "present"}</span>
        {f.provenance.length > 0 && <span>· source: {f.provenance.join(", ")}</span>}
      </div>
    </li>
  );
}
