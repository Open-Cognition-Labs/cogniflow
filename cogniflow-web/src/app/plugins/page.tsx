"use client";

import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowDownUp, Cpu, Database, Layers, Loader2, Plug } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Reveal } from "@/components/site/reveal";

type Plugins = {
  embedders: string[];
  rerankers: string[];
  generators: string[];
  backends: string[];
  defaults: Record<string, string>;
};

export default function PluginsPage() {
  const [sid, setSid] = useState<string | null>(null);
  const [plugins, setPlugins] = useState<Plugins | null>(null);
  const [down, setDown] = useState(false);
  const [embedder, setEmbedder] = useState("bge-m3");
  const [reranker, setReranker] = useState("off");
  const [saving, setSaving] = useState(false);

  const [custom, setCustom] = useState(false);
  const [cBase, setCBase] = useState("http://localhost:11434/v1");
  const [cModel, setCModel] = useState("");
  const [cKey, setCKey] = useState("");

  // generation model (AI model plugin)
  const [generator, setGenerator] = useState("managed");
  const [gCustom, setGCustom] = useState(false);
  const [gBase, setGBase] = useState("http://localhost:11434/v1");
  const [gModel, setGModel] = useState("");
  const [gKey, setGKey] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const p = await api.plugins();
        setPlugins(p);
        setEmbedder(p.defaults.embedder ?? "bge-m3");
        setReranker(p.defaults.reranker ?? "off");
      } catch {
        setDown(true);
      }
      try {
        const s = localStorage.getItem("cf_session") || (await api.newSession());
        localStorage.setItem("cf_session", s);
        setSid(s);
      } catch {
        setDown(true);
      }
    })();
  }, []);

  const save = useCallback(async () => {
    if (!sid) return;
    setSaving(true);
    try {
      await api.setConfig(sid, {
        embedder: custom ? "openai" : embedder,
        embedder_base_url: custom ? cBase : undefined,
        embedder_model: custom ? cModel || undefined : undefined,
        embedder_api_key: custom ? cKey || undefined : undefined,
        reranker,
        generator: gCustom ? "openai" : generator,
        generator_base_url: gCustom ? gBase : undefined,
        generator_model: gCustom ? gModel || undefined : undefined,
        generator_api_key: gCustom ? gKey || undefined : undefined,
      });
      toast.success("Plugin configuration saved for your session.");
    } catch (e) {
      toast.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }, [sid, embedder, reranker, custom, cBase, cModel, cKey, generator, gCustom, gBase, gModel, gKey]);

  return (
    <div className="mx-auto max-w-5xl px-5 py-12">
      <Reveal>
        <p className="eyebrow mb-3">Plugins</p>
        <h1 className="text-hero mb-3 !text-[clamp(2rem,4vw,3rem)]">Every layer is a plug.</h1>
        <p className="text-subhead mb-8 max-w-[62ch]">
          The infrastructure is ours; the providers are yours. Embedder, reranker, generation
          model, and graph backend are each config-selected and fail-loud - pick one,
          bring a custom endpoint, or point at a local model. Nothing is hard-wired.
        </p>
      </Reveal>

      {down && (
        <div className="mb-8 flex items-start gap-3 rounded-xl border border-warn/40 bg-warn/10 p-4 text-sm">
          <AlertTriangle className="mt-0.5 size-5 shrink-0 text-warn" />
          <div>
            <div className="font-semibold">Backend not reachable</div>
            <p className="mt-1 text-muted-foreground">
              Start it to configure plugins live: <code className="rounded bg-secondary px-1.5 py-0.5">python cogniflow-api/main.py</code>
            </p>
          </div>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Reveal>
          <Layer icon={<Layers className="size-4" />} title="Embedder" desc="Turns text into vectors for semantic recall." live>
            <Chips options={plugins?.embedders ?? ["hash", "bge-m3", "nvidia-e5"]} value={embedder} onChange={(v) => { setEmbedder(v); setCustom(false); }} disabled={custom} />
            <button onClick={() => setCustom((v) => !v)} className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-brand hover:underline">
              <Plug className="size-3.5" /> {custom ? "Use a built-in embedder" : "Add custom / local provider"}
            </button>
            {custom && (
              <div className="mt-3 space-y-2 rounded-lg border border-border bg-secondary/40 p-3">
                <p className="text-xs text-muted-foreground">Any OpenAI-compatible endpoint (local or hosted).</p>
                <Input placeholder="base URL (http://localhost:11434/v1)" value={cBase} onChange={(e) => setCBase(e.target.value)} className="h-8" />
                <Input placeholder="model id" value={cModel} onChange={(e) => setCModel(e.target.value)} className="h-8" />
                <Input placeholder="API key (blank for local)" value={cKey} onChange={(e) => setCKey(e.target.value)} className="h-8" type="password" />
              </div>
            )}
          </Layer>
        </Reveal>

        <Reveal delay={0.05}>
          <Layer icon={<ArrowDownUp className="size-4" />} title="Reranker" desc="Optional cross-encoder. Off by default, on by evidence." live>
            <Chips options={plugins?.rerankers ?? ["off", "bge-reranker-v2-m3", "nvidia-rerank"]} value={reranker} onChange={setReranker} />
          </Layer>
        </Reveal>

        <Reveal delay={0.1}>
          <Layer icon={<Cpu className="size-4" />} title="Generation model" desc="Answers from the served context. Model-agnostic - swap it live." live>
            <LabeledChips
              options={[
                { label: "Platform default", value: "managed" },
                { label: "OpenAI-compatible", value: "openai" },
              ]}
              value={generator}
              onChange={(v) => { setGenerator(v); setGCustom(false); }}
              disabled={gCustom}
            />
            <button onClick={() => setGCustom((v) => !v)} className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-brand hover:underline">
              <Plug className="size-3.5" /> {gCustom ? "Use a managed model" : "Add custom / local model"}
            </button>
            {gCustom && (
              <div className="mt-3 space-y-2 rounded-lg border border-border bg-secondary/40 p-3">
                <p className="text-xs text-muted-foreground">Any OpenAI-compatible chat endpoint (hosted or local - vLLM, Ollama, LM Studio).</p>
                <Input placeholder="base URL (http://localhost:11434/v1)" value={gBase} onChange={(e) => setGBase(e.target.value)} className="h-8" />
                <Input placeholder="model id (e.g. llama3.1:8b)" value={gModel} onChange={(e) => setGModel(e.target.value)} className="h-8" />
                <Input placeholder="API key (blank for local)" value={gKey} onChange={(e) => setGKey(e.target.value)} className="h-8" type="password" />
              </div>
            )}
          </Layer>
        </Reveal>

        <Reveal delay={0.15}>
          <Layer icon={<Database className="size-4" />} title="Graph backend" desc="The bi-temporal store.">
            <Tags options={plugins?.backends ?? ["falkordb", "neo4j"]} />
            <p className="mt-3 text-xs text-muted-foreground">Same driver abstraction; set via <code className="rounded bg-secondary px-1 py-0.5">COGNIFLOW_BACKEND_DRIVER</code>.</p>
          </Layer>
        </Reveal>
      </div>

      <Reveal>
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <button onClick={save} disabled={saving || down} className="rounded-md bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground disabled:opacity-40">
            {saving ? <Loader2 className="size-4 animate-spin" /> : "Save plugin configuration"}
          </button>
          <span className="text-xs text-muted-foreground">Applies to your playground session. Fail-loud: a missing key or unknown name raises - never a silent fallback.</span>
        </div>
      </Reveal>
    </div>
  );
}

function Layer({ icon, title, desc, live, children }: { icon: React.ReactNode; title: string; desc: string; live?: boolean; children: React.ReactNode }) {
  return (
    <div className="h-full rounded-xl border border-border bg-card p-5 elev">
      <div className="mb-1 flex items-center gap-2 text-sm font-semibold">
        <span className="text-brand">{icon}</span> {title}
        {live && <span className="ml-auto rounded-full border border-brand/30 bg-brand/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-brand">live</span>}
      </div>
      <p className="mb-3 text-xs text-muted-foreground">{desc}</p>
      {children}
    </div>
  );
}

// Display labels keep the provider out of the UI - the infrastructure is ours, the endpoint is a
// plug. Values sent to the backend are unchanged.
const PRESET_LABELS: Record<string, string> = {
  hash: "hash (dev)",
  "bge-m3": "bge-m3",
  "nvidia-e5": "e5-large",
  "bge-reranker-v2-m3": "bge-reranker-v2",
  "nvidia-rerank": "cross-encoder",
};

function Chips({ options, value, onChange, disabled }: { options: string[]; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button
          key={o}
          disabled={disabled}
          onClick={() => onChange(o)}
          className={`rounded-full border px-3 py-1 text-sm transition-colors disabled:opacity-40 ${
            value === o ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background text-foreground hover:bg-accent"
          }`}
        >
          {PRESET_LABELS[o] ?? o}
        </button>
      ))}
    </div>
  );
}

function LabeledChips({
  options,
  value,
  onChange,
  disabled,
}: {
  options: { label: string; value: string }[];
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button
          key={o.value}
          disabled={disabled}
          onClick={() => onChange(o.value)}
          className={`rounded-full border px-3 py-1 text-sm transition-colors disabled:opacity-40 ${
            value === o.value ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background text-foreground hover:bg-accent"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Tags({ options }: { options: string[] }) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => (
        <span key={o} className="rounded-full border border-border bg-secondary/50 px-3 py-1 text-sm text-muted-foreground">{o}</span>
      ))}
    </div>
  );
}
