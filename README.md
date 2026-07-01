# Cogniflow

**Bi-temporal, self-falsifying belief substrate for agentic RAG.** The combination of a
bi-temporal knowledge graph (à la Graphiti) with an agentic retrieval loop (à la
LlamaIndex), welded by a closed feedback loop: retrieve → check validity → falsify
superseded beliefs → persist the verdict → reshape the next retrieval.

This is **ChronoRAG** (temporal) × **PALIMPSEST** (self-falsifying) as a library.

> **Status: Phase 6 - hardened for scale and contributors (1.0-ready).**
> The auditable, self-hostable belief ledger for agents. Both original promises are cashed:
> **(1) multi-backend** - a Neo4j backend passes the *same* heartbeat / both-stamps / replay
> un-knowing / provenance assertions as FalkorDB with no weakened check and no core
> special-casing (the Phase-0 abstraction held); **(2) the contributor proof** - a new policy
> added entirely from the public API, outside `core/`, certified by the same conformance
> suite. The deferred-debt ledger is fully disposed (see `PROJECT_STATUS.md`): durable queue
> journal, write-time `superseded_by`, archive seam with correct replay over archived history,
> a CI integration lane over real backends, and a grown verify_fact eval with **recall** as
> the headline. Non-OpenAI is real: the whole pipeline runs on MiniMax-M3 via NVIDIA.
> Extend it from [CONTRIBUTING.md](CONTRIBUTING.md) + [docs/EXTENDING.md](docs/EXTENDING.md)
> without touching core. Non-goals (stay honest): no UI in core, no hosted offering,
> self-hostable is the moat.

> **Product layer - Slice A (OKF in -> temporally-correct answer out, headless).**
> Cogniflow ingests Google's [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog)
> bundles (`cogniflow.okf`, built to the spec's weak conformance, derived `valid_at`
> labeled, no core changes) and answers through a straight temporal-RAG loop
> (`cogniflow.pipelines.temporal_rag_answer`). The controlled head-to-head
> (`demo/okf_head_to_head.py`, same LLM/corpus/pipeline, only the memory layer differs):
> on an OKF bundle whose `weekly_active_users` metric is redefined March->June, **plain
> RAG returns the stale 7-day definition; Cogniflow returns the current 28-day one and
> replays the 7-day one for `as_of=March`.** The win is temporal correctness, not recall.

> **Product layer - Slice A.2 (the second front door: any document in).** Beyond OKF,
> Cogniflow ingests plain text, markdown, and **PDFs** (`cogniflow.documents`) through the
> *same* Episode/`write` path - parse -> structure-preserving chunks -> Episodes, no core
> changes. The parser is pluggable (`DocumentParser`): pypdf is the default behind the
> `[documents]` extra, MinerU is the documented production adapter behind `[mineru]`;
> heavy deps are never core. **ColPali / image-indexing is deliberately out** - you cannot
> attach a validity interval to a page-image embedding, and the temporal layer needs facts
> (see [docs/DOCUMENT_INGESTION.md](docs/DOCUMENT_INGESTION.md)). Cross-version
> supersession is free: re-ingesting an updated document stamps the old fact with both
> `invalid_at` and `expired_at`. The PDF head-to-head (`demo/doc_head_to_head.py`, two
> report versions, HQ Boston->Denver) shows the structural win: plain RAG has **no as-of
> axis** and cannot answer "as of 2020" at all; Cogniflow returns the current fact for now
> and replays the old one for the past. Document fact-extraction is honest about its limit
> - reliable for concrete statements, weak for abstract prose; structured input (OKF's
> `fact` key) remains the deterministic path.

> **Product layer - Slice A.3 (the context-serving API: any model can call it).** Cogniflow
> is now a standalone **context engine** (`cogniflow.context.serve_context`): query in,
> temporally-correct *context* out - **facts, not a generated answer** - for any model to
> put in its own prompt. The `as_of` axis is a first-class parameter (the differentiator,
> exposed). The honesty labels survive to the output: each served fact carries its
> `valid_at`/`invalid_at`, provenance, and a `valid_at_source` confidence
> (`authoritative`/`derived`/`none`, plus the raw label) - persisted on the edge at write
> and round-tripped to the serving boundary, proven end to end by a live test. Two
> read-only, self-hostable surfaces (`cogniflow.serving`): an **MCP server** (`[mcp]`
> extra) as the primary "any agent calls it" path, and **HTTP/REST** (`[serve]` extra)
> underneath - both run in the caller's environment, so data never leaves. The extraction
> floor ships in every response's `notes`. See [docs/CONTEXT_API.md](docs/CONTEXT_API.md).
> (The human/compliance audit dashboard is the separate Slice B.)

> **Product layer - Slice B (the audit/replay dashboard: the moat made visible).** A
> **read-only** window onto the belief ledger for a human (`cogniflow.serving.create_audit_app`,
> `[serve]` extra, self-hostable): current beliefs, the **event-time** axis (what was true at
> T - scrub April->7-day, July->28-day), the **system-time replay** scrubber (what the system
> *knew* at S), and provenance traces - over the four `AuditLedger` methods, no write verb
> exposed. **The centerpiece is the un-knowing made visible:** scrubbed to before a
> supersession, a fact reads believed-then and un-superseded, never with its current
> `invalid_at` - the engine un-knows and the UI renders only what it returns, so present
> knowledge cannot leak backward (asserted by the hardest test in the slice). Provenance
> resolves the episode UUID to the human-readable document name from stored linkage
> (G1) - an unresolvable UUID is shown as a UUID, never guessed - and each fact shows its
> `valid_at_source` confidence. This is the one screen no plain RAG can build, because it is
> driven by system-time replay nobody else has. See
> [docs/AUDIT_DASHBOARD.md](docs/AUDIT_DASHBOARD.md).

> **Embedder plug - config-selected, fail-loud, bring-your-own.** The embedder is a
> pluggable layer (`cogniflow.backends.embedders`): `embedder: "hash" | "bge-m3" |
> "nvidia-e5"` by **config, not code**. The key-free **hash embedder stays the default**
> (correctness tests don't depend on embeddings and stay deterministic); a real NVIDIA-API
> embedder (default `baai/bge-m3`, the self-hosted production target) is opt-in via
> `COGNIFLOW_EMBEDDER_API_KEY`. Two load-bearing guards: it **fails loud** - a missing key,
> unknown name, or license-excluded model (`nvidia/nv-embed-v1`) raises at startup and
> **never silently falls back to meaning-blind hash retrieval** - and the **dimension travels
> with the embedder** and is validated against the store, hard-crashing on mismatch rather
> than corrupting the vector space. See [docs/EMBEDDERS.md](docs/EMBEDDERS.md).

> **Product layer - Generation (closing the RAG loop: context -> cited answer).** Cogniflow
> now answers end to end (`cogniflow.generation.generate_answer`): documents in ->
> temporally-correct, provenance-cited answer out - a full RAG, with the temporal correctness
> and provenance plain RAG lacks. It is **thin and optional, built on the context API**: a
> caller picks **context out** (bring your own model) or **answer out** (we generate); without
> a generator only the context surface exists, so the model-agnostic core survives. **The
> centerpiece - temporal correctness survives generation (proven live):** Tesla HQ moved Palo
> Alto -> Austin and the generation model's *training* knows Austin, yet asked "as of 2018"
> the answer is **Palo Alto** (from the as-of context), because the LLM is constrained to
> answer only from the served context and ignore its training. The answer carries the
> `valid_at_source` confidence (so it doesn't launder the prose-extraction floor into
> confident prose) and the provenance it was built from (audit-traceable). The generation LLM
> is a **model-agnostic, fail-loud plug** (`cogniflow.generators`, NVIDIA/OpenAI/local), and
> both surfaces run over MCP + HTTP, self-hostable. See [docs/GENERATION.md](docs/GENERATION.md).

> **Launch layer - Slice C (the in-browser head-to-head demo + the measured reranker).** A
> self-contained static page ([demo/static_demo/index.html](demo/static_demo/index.html), a
> **real captured run**, zero setup) that makes the differentiator undeniable: it **leads with
> the as-of axis** (plain RAG cannot answer "Where is Tesla HQ *as of 2015*?" at all; Cogniflow
> answers Palo Alto), shows the **cited answer with `valid_at_source` confidence**, and reports
> the **reranker measured on a deliberately confusable corpus**. The reranker is a
> config-selected, fail-loud retrieval-stage plug (default self-hostable `bge-reranker-v2-m3`;
> `nvidia-rerank` measured here), **off by default** and justified on evidence: on entity-named
> queries BGE-M3 already tops out (retriever sets the ceiling), but on hard *indirect* queries
> the reranker lifted top-1 7/8->8/8 (MRR +0.10), so it earns its place as an opt-in quality
> tier. Reproduce it: `python demo/capture_demo.py`. See [docs/DEMO.md](docs/DEMO.md). (The
> fifteen-second-stranger and in-browser visual checks are human steps before launch.)

> **Launch layer - Slice D (the landing page: positioning, framed for a stranger).** A
> self-contained static page ([demo/static_demo/landing.html](demo/static_demo/landing.html),
> generated from real runs by `build_landing.py`) that positions Cogniflow as **the auditable,
> self-hostable belief ledger for agents** and leads with the as-of axis. It positions **by
> contrast** - the auditable/self-hostable axis the recall-optimized clouds vacated, not a
> recall fight - with an **honest capability matrix** whose visible *tie row* on retrieval is
> what makes the win rows believed. The **two-panel benchmark is real and reproducible**
> (`python demo/benchmark.py`): standard questions **plain RAG 4/4 = Cogniflow 4/4** (honest
> tie), as-of questions **plain RAG 0/4, Cogniflow 4/4**. Crucially the benchmark corpus is
> **fictional on purpose** - on famous real entities a large LLM answers as-of questions from
> its *training* (measured: it scored 4/4), so the temporal advantage only shows on data the
> model has never seen (i.e. your private data), which is where it's benchmarked. No "first
> temporal RAG" claim; the extraction floor and inherited retrieval are stated plainly. The
> fifteen-second-stranger comprehension check is the one human step that remains.

## Design rule

The **core is dependency-free**. `cogniflow.core` imports nothing but the standard
library. Heavy dependencies (`graphiti-core`, `llama-index-core`, `falkordb`) are pulled
in only by *backends* and *bridges*, and only when their optional extras are installed.
This is what keeps the contracts stable and the architecture pluggable.

## The spine

```
            ┌──────────────────────── core (stdlib only) ───────────────────────┐
            │  types.py     Belief · Episode · RetrievalQuery · ScoredBelief ·   │
            │               RetrievalResult · FalsificationVerdict · WriteReceipt│
            │  contracts.py Substrate / AsyncSubstrate   (write · read · falsify)│
            │  policies.py  RetrievalPolicy · ValidityPolicy ·                   │
            │               FalsificationPolicy · WritebackPolicy   (4 policies) │
            └───────────────┬───────────────────────────────────┬───────────────┘
                            │ implemented by                     │ adapted by
                            ▼                                     ▼
                   backends/ (Substrate impls)           bridges/ (framework glue)
                   - noop.py        ← Phase 0            - contracts.py (neutral)
                   - graphiti.py    ← Phase 1 (deferred) - llamaindex/   ← deferred
                            │
                            ▼
                   conformance/ (the test harness any backend must pass)
```

### The three substrate operations
- **write(episode)** → `WriteReceipt` — ingest a source episode into beliefs.
- **read(query)** → `RetrievalResult` — retrieve beliefs valid as-of a point in time.
- **falsify(target, against=…)** → `FalsificationVerdict` — decide if a belief is superseded.

### The four policy interfaces (the seams from the design analysis)
| Policy | Seam | Question it answers |
|---|---|---|
| `RetrievalPolicy` | read | how to resolve as-of and rank candidates |
| `ValidityPolicy` | invalidate | is this belief valid at time *t*? |
| `FalsificationPolicy` | falsify | is this belief superseded, and by what? |
| `WritebackPolicy` | write-back | should a retrieval outcome become a new belief? |

## Install (dev)

```bash
pip install -e ".[dev]"
```

## Prove the skeleton

```bash
ruff check .
pytest
```

Phase-0 proof: the contracts are stable (field-surface is frozen by tests), a no-op
backend passes the conformance stub, and CI is green across Python 3.10–3.12.

## The invariant we enforce

The headline property is the **un-knowing invariant**: replaying to a system-time *before* a
correction returns what was believed then, and does **not** leak the later invalidation
backward. That is the one thing a plain (or valid-time-only) RAG cannot do.

It is enforced two ways, both green on **every pull request**:

- **Pure** — [`tests/test_audit_replay.py`](tests/test_audit_replay.py) and
  [`tests/test_validity_policy.py`](tests/test_validity_policy.py) assert the reconstruction and
  as-of semantics as deterministic functions (no infra).
- **Live** — [`tests/integration/test_replay_seeded.py`](tests/integration/test_replay_seeded.py)
  asserts the same invariant end-to-end against a real **FalkorDB** service, with **no LLM key**
  (structured seed, backdated `created_at`). Wired in the `replay-invariant` job of
  [`.github/workflows/ci.yml`](.github/workflows/ci.yml). If replay ever leaks a later
  correction into the past, CI goes red.

```
replay(2021) -> Acme HQ = Boston   (invalid_at un-known; the 2022 move not yet learned)
replay(2023) -> Acme HQ = Denver   (the correction is now known)
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
