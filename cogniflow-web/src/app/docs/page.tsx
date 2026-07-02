import type { Metadata } from "next";
import { Reveal } from "@/components/site/reveal";

export const metadata: Metadata = { title: "Docs" };

const TOC = [
  ["overview", "Overview"],
  ["quickstart", "Quickstart"],
  ["deploy", "Deploy (self-host)"],
  ["using", "Using the platform"],
  ["architecture", "Architecture"],
  ["plugins", "Plugins"],
  ["api", "API reference"],
] as const;

function Code({ children }: { children: string }) {
  return (
    <pre className="mt-3 overflow-x-auto rounded-xl border border-border bg-[#0f1116] p-4 text-[13px] leading-relaxed text-[#e6e9f0]">
      <code>{children}</code>
    </pre>
  );
}

function Doc({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-24 border-t border-border py-10 first:border-0 first:pt-0">
      <Reveal>
        <h2 className="text-section mb-4">{title}</h2>
        <div className="max-w-[70ch] space-y-3 text-[15px] leading-relaxed text-muted-foreground [&_b]:text-foreground [&_code]:rounded [&_code]:bg-secondary [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:text-[13px] [&_code]:text-foreground">
          {children}
        </div>
      </Reveal>
    </section>
  );
}

export default function DocsPage() {
  return (
    <div className="mx-auto max-w-6xl px-5 py-12">
      <p className="eyebrow mb-3">Docs</p>
      <h1 className="text-hero mb-3 !text-[clamp(2rem,4vw,3rem)]">Deploy it, use it, understand it.</h1>
      <p className="text-subhead mb-10 max-w-[62ch]">
        Everything to run Cogniflow in your own environment and answer temporally-correct,
        cited questions over your documents.
      </p>

      <div className="grid gap-10 lg:grid-cols-[200px_1fr]">
        <nav className="hidden lg:block">
          <div className="sticky top-24 space-y-1 text-sm">
            {TOC.map(([id, label]) => (
              <a key={id} href={`#${id}`} className="block rounded-md px-3 py-1.5 text-muted-foreground hover:bg-accent hover:text-foreground">
                {label}
              </a>
            ))}
          </div>
        </nav>

        <div className="min-w-0">
          <Doc id="overview" title="Overview">
            <p>
              Cogniflow is a <b>bi-temporal RAG platform</b>: a complete pipeline from any document
              to a cited, temporally-correct answer, with a memory that records not just what is
              true, but <b>when</b> it was true and when the system learned it. It answers
              &ldquo;as of&rdquo; any past date, replays what it knew at any moment, and traces
              every claim back to its source.
            </p>
            <p>Three surfaces ship in the box:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>the <b>platform API</b> (ingest, context, answer, audit/replay),</li>
              <li>the <b>playground</b> (upload documents, ask with an as-of slider),</li>
              <li>the <b>audit dashboard</b> (current beliefs, timelines, system-time replay).</li>
            </ul>
          </Doc>

          <Doc id="quickstart" title="Quickstart">
            <p>The fastest path from a clone to a temporally-correct answer.</p>
            <Code>{`# 1. Python engine + platform API
python -m venv .venv && . .venv/Scripts/activate # (Unix: source .venv/bin/activate)
pip install -e ".[all,serve]"

# 2. Start the graph store (Docker)
docker run -d --name cogniflow-db -p 6379:6379 falkordb/falkordb:latest

# 3. Configure the model + a REAL embedder (.env at repo root)
# Retrieval defaults to the key-free 'hash' embedder, which is MEANING-BLIND (lexical only).
# Pick a real embedder so first-run retrieval is semantic - choose by your constraint:
# key-free, needs torch: COGNIFLOW_EMBEDDER=bge-m3-local (pip install -e ".[embeddings]")
# dependency-light, key: COGNIFLOW_EMBEDDER=bge-m3 (needs COGNIFLOW_EMBEDDER_API_KEY)
COGNIFLOW_LLM_API_KEY=... # generation model provider key
COGNIFLOW_LLM_BASE_URL=... # provider base URL
COGNIFLOW_LLM_MODEL=... # model id
COGNIFLOW_EMBEDDER=bge-m3 # semantic retrieval (or 'bge-m3-local' for the key-free path)
COGNIFLOW_EMBEDDER_API_KEY=... # required for bge-m3 (hosted); omit for bge-m3-local

# 4. Run the platform API + the web app
python cogniflow-api/main.py # http://localhost:8000
pnpm -C cogniflow-web dev # http://localhost:3000`}</Code>
            <p>Open the playground, upload a PDF, and ask a question with the <b>as-of</b> date set to the past.</p>
            <p className="mt-3 rounded-lg border border-brand/20 bg-brand/[0.04] p-3 text-sm">
              A real embedder fixes <b>retrieval</b> (which facts come back). It does not change{" "}
              <b>extraction</b> (how well facts are pulled from prose) - that is bounded by the
              generation model and stays honestly labeled per fact via <code>valid_at_source</code>.
              The hash embedder remains the key-free boot default, but it is never silent: the API
              health check and every response warn when retrieval is non-semantic.
            </p>
          </Doc>

          <Doc id="deploy" title="Deploy (self-host)">
            <p>
              Cogniflow runs entirely in your environment - your infrastructure, your
              models, your data never leaves. Three components: the <b>graph store</b>, the
              <b> platform API</b>, and the <b>web app</b>.
            </p>
            <p><b>Graph store.</b> Any FalkorDB or Neo4j endpoint. For production, run it as a managed service or a persistent container with a volume:</p>
            <Code>{`docker run -d --name cogniflow-db -p 6379:6379 \\
  -v cogniflow-data:/data falkordb/falkordb:latest`}</Code>
            <p><b>Platform API.</b> Serve with any ASGI server; restrict CORS to your web origin:</p>
            <Code>{`COGNIFLOW_CORS_ORIGINS=https://app.yourco.com \\
  python -m uvicorn cogniflow-api.main:app --host 0.0.0.0 --port 8000 --workers 4`}</Code>
            <p><b>Web app.</b> Build once and serve the static output; point it at your API:</p>
            <Code>{`NEXT_PUBLIC_API_URL=https://api.yourco.com pnpm -C cogniflow-web build
pnpm -C cogniflow-web start # or deploy the build output to your host`}</Code>
            <p>
              For an air-gapped / in-VPC deployment, set the model, embedder, and reranker
              plugins to <b>local endpoints</b> (Ollama, vLLM, or a self-hosted embedder) so no
              request leaves your network.
            </p>
            <p className="mt-3 rounded-lg border border-warn/30 bg-warn/[0.06] p-3 text-sm">
              <b>Security posture.</b> The API has <b>baseline security</b> - bearer-token
              auth, token-scoped session access, rate limits, and upload caps (set{" "}
              <code>COGNIFLOW_API_TOKENS</code>; see <code>SECURITY.md</code>). It is safe in a{" "}
              <b>trusted environment</b>, <b>not</b> enterprise-ready: RBAC, access-audit logging,
              GDPR deletion, and hardened multi-tenant isolation are not included yet. Terminate
              TLS in front of it and keep it behind a network boundary.
            </p>
          </Doc>

          <Doc id="using" title="Using the platform">
            <p>
              <b>Ingest.</b> Upload a PDF, markdown, or text document with the date its facts
              were true. Cogniflow parses, chunks, embeds, and writes each fact into the bi-temporal
              store; re-ingesting an updated document supersedes the old fact (both stamps).
            </p>
            <p>
              <b>Ask.</b> Query with an <b>as-of</b> instant. The platform filters context to
              what was true (and known) then, generates an answer grounded only in that context,
              and returns it with per-fact confidence and provenance.
            </p>
            <p>
              <b>Audit.</b> Inspect current beliefs, a fact&rsquo;s full timeline, and
              system-time replay - what the system knew at any past moment, correctly
              un-knowing anything learned later.
            </p>
          </Doc>

          <Doc id="architecture" title="Architecture">
            <p>One pipeline, every stage pluggable:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li><b>Ingest</b> - parse + structure-preserving chunk + embed.</li>
              <li><b>Bi-temporal knowledge graph</b> - facts stored <b>bi-temporally</b>: event time (when true) and system time (when learned).</li>
              <li><b>As-of retrieval</b> - validity-filter context to a point in time before ranking.</li>
              <li><b>Rerank</b> - optional cross-encoder, off by default.</li>
              <li><b>Grounded generation</b> - answer only from retrieved facts.</li>
              <li><b>Cited answer</b> - every claim traces to a fact, every fact to a document.</li>
            </ul>
            <p>
              The core contracts are dependency-free; storage, models, and retrieval are adapters
              behind stable interfaces. The bi-temporal model is what makes &ldquo;what did we
              know at time S&rdquo; answerable - and answerable <b>correctly</b> (facts
              learned after S are un-known in the replay).
            </p>
          </Doc>

          <Doc id="plugins" title="Plugins">
            <p>
              Every provider is a plugin, selected by config - nothing is hard-wired. Swap
              the embedder, reranker, generation model, or graph backend without touching code.
              Selection is <b>fail-loud</b>: a missing key or unknown name raises at startup
              rather than silently falling back.
            </p>
            <Code>{`COGNIFLOW_EMBEDDER=bge-m3 # or hash (key-free), or a custom endpoint
COGNIFLOW_GENERATOR=... # any OpenAI-compatible provider
COGNIFLOW_RERANKER_API_KEY=... # optional reranker (off by default)
COGNIFLOW_BACKEND_DRIVER=falkordb # or neo4j`}</Code>
            <p>Manage them live for your session on the <a href="/plugins" className="text-brand hover:underline">Plugins</a> page.</p>
          </Doc>

          <Doc id="api" title="API reference">
            <p>The platform API (default <code>http://localhost:8000</code>). Ingestion is the only write path; serve and audit are read-only.</p>
            <div className="mt-3 overflow-hidden rounded-xl border border-border">
              <table className="w-full text-left text-sm">
                <thead className="bg-secondary/60 text-xs uppercase tracking-wide text-muted-foreground">
                  <tr><th className="px-4 py-2.5">Method</th><th className="px-4 py-2.5">Path</th><th className="px-4 py-2.5">Purpose</th></tr>
                </thead>
                <tbody className="[&_td]:px-4 [&_td]:py-2.5 [&_tr]:border-t [&_tr]:border-border">
                  <tr><td>POST</td><td><code>/api/ingest</code></td><td>upload a document (PDF/md/text)</td></tr>
                  <tr><td>POST</td><td><code>/api/ingest-text</code></td><td>add a fact with a valid-from date</td></tr>
                  <tr><td>POST</td><td><code>/api/context</code></td><td>temporally-correct context for a query + as_of</td></tr>
                  <tr><td>POST</td><td><code>/api/answer</code></td><td>cited answer + confidence</td></tr>
                  <tr><td>GET</td><td><code>/api/audit/replay</code></td><td>what the system knew at a past instant</td></tr>
                  <tr><td>GET</td><td><code>/api/plugins</code></td><td>available embedders / rerankers / models</td></tr>
                </tbody>
              </table>
            </div>
          </Doc>
        </div>
      </div>
    </div>
  );
}
