# Project status - 1.0 readiness

The phased build (0-5) closed the inventive risk; Phase 6 closes operational and
contributor risk and disposes of every deferred debt - **paid** or **formally accepted
with a reason**. Nothing rots silently into 1.0.

## Deferred-debt ledger - dispositions

| ID | Debt | Disposition |
|---|---|---|
| **T1** | Multi-backend - did the Phase-0 abstraction hold? | **PAID.** Neo4j backend (config `backend_driver="neo4j"`) passes the *same* heartbeat, both-stamps, replay un-knowing, and provenance assertions as FalkorDB, with no weakened check and no core special-casing (`tests/integration/test_neo4j_parity.py`). The only backend-specific code is the driver choice and a datetime param/parse shim (Neo4j stores native temporals, FalkorDB ISO strings); both honor the same contract. |
| **T2** | Unbounded append-only growth. | **PAID (seam) + documented scale plan.** Hot path scopes to `group_id`. `cogniflow.core.archive` provides `ArchiveStore` + archive-aware replay that unions hot + cold, with a test proving replay over archived history is still correct and the un-knowing invariant holds. A production cold store (object storage / cold table) implements the same Protocol; that build is post-1.0 engineering, the correctness seam is in and tested. |
| **T3** | Non-OpenAI provider verified end to end. | **SATISFIED.** The entire build runs on **MiniMax-M3 via NVIDIA's endpoint - not OpenAI** - through the full pipeline (extraction, contradiction, verify_fact). Swap procedure: set `COGNIFLOW_LLM_API_KEY/BASE_URL/MODEL` to any OpenAI-compatible endpoint (or a local server); embeddings already use a local deterministic embedder, so no embedding vendor is required. For a fully air-gapped deployment, point the base_url at a local model server. |
| **Q-DUR** | In-process queue; "queued" didn't survive restart. | **PAID.** `WriteBackQueue(journal=...)` with a pluggable `QueueJournal` and a `JsonFileJournal` reference; `recover()` re-enqueues unacknowledged observations at startup; entries clear on success/dead-letter. Default remains in-process (documented); a production deployment swaps in a Redis-stream journal behind the same Protocol. Test: `tests/test_durability_and_archive.py`. |
| **SUP** | Provenance back-link was a reconstructed heuristic. | **PAID.** `superseded_by` (+ `superseded_by_episode`) is stamped on the superseded edge at write time; `provenance_trace` reads the stored back-link and only falls back to the temporal-join reconstruction for legacy data. The ambiguous-boundary lie is eliminated for new writes. |
| **EVAL** | verify_fact measured on 4 cases at 0.5 bars. | **CHARACTERIZED (and growing).** Corpus grown to 8 labeled cases; **recall is the tracked headline** (a missed contradiction is the dangerous error for an audit ledger) at >= 0.6, precision >= 0.5. "Characterized" is a moving bar - grow the corpus over time (`tests/integration/test_verify_reliability.py`, `cogniflow.eval`). |
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
contributor through the `EXTENDING.md` surface; grow the eval corpus. There is no Phase 7
- what remains is shipping and positioning, not invention.
