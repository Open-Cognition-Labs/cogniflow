# Project status - 1.0 readiness

The staged build closed the inventive risk; the 1.0 hardening pass closed operational and
contributor risk and disposed of every deferred debt - **paid** or **formally accepted
with a reason**. Nothing rots silently into 1.0.

## Deferred-debt ledger - dispositions

| ID | Debt | Disposition |
|---|---|---|
| **T1** | Multi-backend - did the core abstraction hold? | **PAID.** Neo4j backend (config `backend_driver="neo4j"`) passes the *same* heartbeat, both-stamps, replay un-knowing, and provenance assertions as FalkorDB, with no weakened check and no core special-casing (`tests/integration/test_neo4j_parity.py`). The only backend-specific code is the driver choice and a datetime param/parse shim (Neo4j stores native temporals, FalkorDB ISO strings); both honor the same contract. |
| **T2** | Unbounded append-only growth. | **PAID (seam) + documented scale plan.** Hot path scopes to `group_id`. `cogniflow.core.archive` provides `ArchiveStore` + archive-aware replay that unions hot + cold, with a test proving replay over archived history is still correct and the un-knowing invariant holds. A production cold store (object storage / cold table) implements the same Protocol; that build is post-1.0 engineering, the correctness seam is in and tested. |
| **T3** | Non-OpenAI provider verified end to end. | **SATISFIED.** The entire build runs on **MiniMax-M3 via NVIDIA's endpoint - not OpenAI** - through the full pipeline (extraction, contradiction, verify_fact). Swap procedure: set `COGNIFLOW_LLM_API_KEY/BASE_URL/MODEL` to any OpenAI-compatible endpoint (or a local server); embeddings already use a local deterministic embedder, so no embedding vendor is required. For a fully air-gapped deployment, point the base_url at a local model server. |
| **Q-DUR** | In-process queue; "queued" didn't survive restart. | **PAID.** `WriteBackQueue(journal=...)` with a pluggable `QueueJournal` and a `JsonFileJournal` reference; `recover()` re-enqueues unacknowledged observations at startup; entries clear on success/dead-letter. Default remains in-process (documented); a production deployment swaps in a Redis-stream journal behind the same Protocol. Test: `tests/test_durability_and_archive.py`. |
| **SUP** | Provenance back-link was a reconstructed heuristic. | **PAID.** `superseded_by` (+ `superseded_by_episode`) is stamped on the superseded edge at write time; `provenance_trace` reads the stored back-link and only falls back to the temporal-join reconstruction for legacy data. The ambiguous-boundary lie is eliminated for new writes. |
| **EVAL** | verify_fact measured on 4 cases at 0.5 bars. | **RESOLVED BY MEASUREMENT.** Corpus grown 8 -> 60 labeled cases (`cogniflow.eval_corpus`: six fact-type families, 30 pos / 30 neg, fictional entities, dates in metadata only; template-authored + hand-reviewed, so per-family results are the finer signal). **Measured (2026-07-02, MiniMax-M3, n=60): precision 1.00, recall 0.57, accuracy 0.78, indeterminate 18/60** - the n=8 "0.50" was real, not noise: the model's verify recall sits near ~0.57 because it hedges (indeterminate) rather than mis-flags; when it DOES flag a supersession it has been right every time measured. Regression bounds set FROM the measurement (method: point estimate - 1 binomial SE, rounded to 0.05): recall >= 0.50, precision >= 0.85. The measured value, not the bound, is the published capability. **Related: the faithfulness checker ('lexical') measured on the labeled claim set - hallucination-detection recall 1.00, precision 1.00 on n=20 (`tests/test_eval_corpus.py`, runs in default CI; deterministic). Honest scope: n=20, template-authored; the checker is strict-lexical (salience + coverage) and paraphrase beyond token overlap can false-flag - grow the claim set alongside the corpus.** |
| **TRIG** | Autonomous verify-call rate unmeasured. | **DECISION, not silence: ReAct foundation formally accepted.** No function-calling model is configured (MiniMax-M3 emits no native tool calls), so trigger-rate is not auto-measured; the agent path is ReAct and its re-query reliability is the documented limit. We measure verify's *detection* reliability (EVAL) and keep the FunctionAgent swap ready for the day a function-calling model is configured. **When an agent integration test flakes, first check whether the tool fired at all** (a missing tool-call is TRIG signal, not infra noise) before attributing it to endpoint load. |
| **CI-INT** | CI ran unit only. | **PAID.** `.github/workflows/integration.yml` spins up FalkorDB + Neo4j service containers and runs the integration suite; LLM-dependent tests run when the `COGNIFLOW_LLM_*` repo secrets are set, otherwise skip cleanly. Contributor PRs are now checkable against integration. |
| **T5** | The contributor proof. | **PAID.** A new validity policy added entirely from the public API in a file outside `core/`, certified by the same conformance suite (`tests/test_contributor_proof.py`, `examples/contrib_policy_example.py`). Zero core changes. |

## What 1.0 is NOT (non-goals)

- **No UI in core.** A replay UI is a separate, optional, post-1.0 sibling package.
- **No managed/hosted offering.** Self-hostable is the competitive position, not a gap.
- **Not the source-connection / identity-resolution layer.** Cogniflow is the memory +
  audit ledger; connecting and normalizing upstream sources is out of scope.
- **Not a general-purpose RAG framework.** It is the temporal + self-falsifying +
  auditable layer over LlamaIndex, not a competitor to it.

## Positioning (for the README / launch)

Pitch as **"the auditable, self-hostable belief ledger for agents"** - where the
differentiators are system-time replay (the un-knowing invariant), pluggable
falsification, and on-prem self-hosting. Do **not** pitch as "temporal agent memory":
that is a crowded race against the substrate this is built on.

## After 1.0

Ship behind the green multi-backend, integration-gated CI; get one real external
contributor through the `EXTENDING.md` surface; grow the eval corpus. What remains is shipping and positioning, not invention.
