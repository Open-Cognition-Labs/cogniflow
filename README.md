# Cogniflow

**Temporal, self-falsifying belief substrate for agentic RAG.** The combination of a
bi-temporal knowledge graph (à la Graphiti) with an agentic retrieval loop (à la
LlamaIndex), welded by a closed feedback loop: retrieve → check validity → falsify
superseded beliefs → persist the verdict → reshape the next retrieval.

This is **ChronoRAG** (temporal) × **PALIMPSEST** (self-falsifying) as a library.

> **Status: Phase 3 (the policy layer - integration becomes a framework).**
> The four policy families (Retrieval / Validity / Falsification / Writeback) are now
> pluggable: registered by name, selected by config, injected uniformly, and
> conformance-tested. A contributor registers a policy and has it verified against a
> family contract. Selection is **fail-loud** - a missing or misnamed policy raises at
> wiring time; the postprocessor no longer silently defaults. Two reference policies per
> family ship (e.g. validity `strict` / `grace_window`, retrieval `default` / `recency`,
> falsification `none` / read-time `interval_overlap`, writeback `never` / `always`).
> The two falsifications stay distinct: write-time ingestion supersession is untouched;
> `interval_overlap` is a read-time, side-effect-free assessor (no LLM). Dead-letters are
> now a first-class signal (count + distinct event + honest freshness).
> Deferred: replay/audit API (Phase 4), LLM-driven `verify_fact` (Phase 5), advanced
> rerank (Phase 5), multi-backend (Phase 6).

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

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
