<div align="center">

# Cogniflow

### Prove what your AI knew - and when.

**The bi-temporal RAG platform.** Any document in → a cited, temporally-correct answer out - 
plus the one thing a plain RAG cannot do: **replay what the system believed at any past
moment**, without leaking later corrections into the past.

[![ci](https://github.com/Nagendhra-web/cogniflow/actions/workflows/ci.yml/badge.svg)](https://github.com/Nagendhra-web/cogniflow/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

[60-second demo](#-60-second-demo-from-nothing) ·
[How it works](#-architecture) ·
[API](#-api-curl--against-the-secure-by-default-server) ·
[Honest limitations](#-honest-limitations)

</div>

---

## Why

Every fact in Cogniflow lives on **two independent time axes** - *when it was true in the
world* (event time) and *when the system learned it* (system time). That second axis is what
the rest of the RAG field doesn't have, and it's what makes answers **defensible**, not just
plausible.

Take one fact that changed: Acme Corp's HQ was **Boston** (2019 filing), then **Denver**
(2022 filing).

| Question | Plain / vector RAG | Valid-time ("temporal") RAG | **Cogniflow** |
|---|---|---|---|
| Where is Acme HQ **now**? | ✅ Denver | ✅ Denver | ✅ Denver |
| Where was it **in 2020**? | ❌ | ✅ Boston | ✅ Boston |
| What did we **believe in 2021**, before the 2022 filing? | ❌ | ❌ | ✅ **Boston** (Denver un-known) |
| Show the timeline + what superseded what | ❌ | partial | ✅ provenance + audit |

The third row is **system-time replay**. It requires an independent record of *when each fact
was learned* - and the discipline never to let a later correction leak into a past belief
(the **un-knowing invariant**, enforced in CI). No mainstream RAG stack ships this.

## What you get

- **Bi-temporal knowledge graph** - four timestamps per fact (`valid_at`/`invalid_at`,
  `created_at`/`expired_at`), stored in FalkorDB or Neo4j.
- **As-of retrieval** - ask any question *as of* any instant; context is validity-filtered
  before ranking.
- **System-time replay & audit** - reconstruct what the system believed at any past moment;
  a live web scrubber makes it visible.
- **Supersession with provenance** - a correcting fact expires the old one and stamps a
  `superseded_by` back-link at write time; every answer carries its citations.
- **Cited, grounded generation** - answers built only from the served, as-of-filtered facts,
  with per-fact confidence labels.
- **Everything is a plug** - embedder, reranker, generation model, and graph backend are
  config-selected and fail-loud; bring hosted APIs or fully local models.
- **Secure by default** - bearer-token auth, token-scoped sessions, rate limits, upload caps
  (baseline security for trusted environments - see [SECURITY.md](SECURITY.md)).
- **Self-hostable end to end** - your documents, your models, your infrastructure; nothing
  leaves your network.

## ⚡ 60-second demo (from nothing)

Prereqs: Docker. No `.env`, no API keys - the hero scenario is **key-free**.

```bash
git clone https://github.com/Nagendhra-web/cogniflow && cd cogniflow
docker compose up -d --build # FalkorDB + API + web, secure-by-default (auth ON)
bash scripts/demo.sh # waits for the API, seeds Acme, asserts the four questions
```

`scripts/demo.sh` prints (and asserts):

```
Q1 now -> Denver
Q2 as of 2020 -> Boston
Q3 replay(2021) -> Boston << the 2022 Denver correction is un-known
Q4 timeline -> Boston (2019 report) superseded by Denver (2022 press release)
```

Then open the **live scrubber** at <http://localhost:3000/playground> and drag the
system-time slider across 2022 - the answer flips Boston↔Denver in front of you:

![System-time replay: scrubbing past the 2022 correction flips the belief Boston to Denver](docs/media/replay-scrubber.gif)

> **Deployment honesty:** `docker compose up` stands up the whole stack for a **local /
> trusted environment**. For multi-replica, `COGNIFLOW_SHARED_STATE=1` moves session
> ownership/config and rate limits into Redis (the FalkorDB server) and `RedisJournal` makes
> the write-back queue durable and shared - proven by a two-replica test
> (`docker compose -f docker-compose.yml -f docker-compose.replicas.yml up -d --build` then
> `bash scripts/two_replica_proof.sh`). A `/metrics` endpoint gives the ops floor. That makes
> the shell **production-deployable** - still **not "enterprise"**: RBAC, access-audit
> logging, GDPR deletion, and certified isolation remain out of scope (see
> [SECURITY.md](SECURITY.md)).

## 🏗 Architecture

```
                          ┌─────────────────────────────────────────────┐
   PDF / MD / text ─────▶│ INGEST documents.py │
   (+ the date true) │ parse → structure-preserving chunk → Episode│
                          └───────────────┬─────────────────────────────┘
                                          ▼
                          ┌─────────────────────────────────────────────┐
                          │ WRITE (LLM extract + contradiction resolve)│
                          │ stamps valid_at/invalid_at (EVENT time) │
                          │ created_at/expired_at (SYSTEM time) │
                          │ contradiction → expire old + superseded_by │
                          └───────────────┬─────────────────────────────┘
                                          ▼
                          ┌─────────────────────────────────────────────┐
                          │ STORE FalkorDB (per-group graph) | Neo4j │
                          └──────┬───────────────────────────┬──────────┘
             relevance path │ │ audit path (direct temporal scan)
                                 ▼ ▼
        ┌──────────────────────────────────┐ ┌──────────────────────────────────────┐
        │ RETRIEVE serve_context │ │ REPLAY core/audit.py │
        │ as-of validity-filter → rank │ │ event_time_query(T) valid_at ≤ T │
        │ → grounded generation → cited │ │ system_time_replay(S) created_at ≤ S │
        │ answer + provenance │ │ + un-know post-S corrections │
        └──────────────────────────────────┘ │ → /api/audit/* + the web scrubber │
                                                └────────────────────────────────────────┘
```

**The core is dependency-free.** `cogniflow.core` imports only the standard library; heavy
dependencies (`graphiti-core`, `falkordb`, `llama-index-core`) live behind optional extras in
*backends* and *bridges*.

### The bitemporal model, in four lines

- **Event time** `[valid_at, invalid_at)` - when the fact was true in the world → "as of 2020."
- **System time** `[created_at, expired_at)` - when the system learned/retracted it → "what
  did we believe at S," and the un-knowing replay.
- A correction **supersedes**: the old fact gets `invalid_at` (event) *and* `expired_at`
  (system) plus a `superseded_by` back-link, stamped at write time.
- Replay to S drops everything learned after S - **including the knowledge that a fact was
  later corrected**. That's the invariant.

## 📄 Use it on your own documents (local - your data never leaves)

```bash
# 1. real generation + retrieval need providers (the seeded hero does not). Put keys in .env:
cp .env.example .env # set COGNIFLOW_LLM_API_KEY and, for semantic retrieval, an embedder

# 2. ingest a document with the date its facts were true, then ask at different as-of dates
TOKEN=cogniflow-demo-token
curl -H "Authorization: Bearer $TOKEN" -F session_id=mine -F reference_time=2019-01-01 \
     -F file=@your_report.pdf http://localhost:8000/api/ingest
```

**Retrieval quality needs a real embedder.** Cogniflow boots on the key-free `hash` embedder
so the engine runs dependency-free - but hash is **meaning-blind** (lexical, not semantic) and
it **warns loudly** at startup and in every response until you configure one:

- **key-free, needs torch** - `pip install -e ".[embeddings]"`, then `COGNIFLOW_EMBEDDER=bge-m3-local`
- **dependency-light, needs a key** - `COGNIFLOW_EMBEDDER=bge-m3` + `COGNIFLOW_EMBEDDER_API_KEY=…`

A real embedder fixes **retrieval** (which facts come back). It does not lift the prose
**extraction** floor (bounded by the LLM, and labeled per fact via `valid_at_source`).
See [docs/EMBEDDERS.md](docs/EMBEDDERS.md).

## 🔌 API (curl) - against the secure-by-default server

Every route but `/api/health` needs the bearer token (`COGNIFLOW_API_TOKENS`; the compose
provisions `cogniflow-demo-token`). A session is scoped to the token that created it.

```bash
TOKEN=cogniflow-demo-token
API=http://localhost:8000
H="Authorization: Bearer $TOKEN"

# seed the demo (key-free), then the four questions:
curl -H "$H" -X POST "$API/api/demo/seed"
curl -H "$H" "$API/api/audit/current?session_id=demo_acme" # -> Denver (now)
curl -H "$H" "$API/api/audit/event?session_id=demo_acme&as_of=2020-06-01" # -> Boston (event time)
curl -H "$H" "$API/api/audit/replay?session_id=demo_acme&system_time=2021-06-01" # -> Boston (system-time replay)
curl -H "$H" "$API/api/audit/timeline/demo-belief-boston?session_id=demo_acme" # -> provenance + supersession

# temporally-correct CONTEXT for your own model (facts, not a generated answer):
curl -H "$H" -H 'Content-Type: application/json' -X POST "$API/api/context" \
     -d '{"session_id":"mine","query":"Where is Acme headquartered?","as_of":"2020-06-01"}'
```

Omit the token → `401`. Use another token against a session you don't own → `403`.

## ✅ The invariant we enforce

The headline property is the **un-knowing invariant**: replaying to a system-time *before* a
correction returns what was believed then, and does **not** leak the later invalidation
backward. Enforced two ways:

- **Pure** - [`tests/test_audit_replay.py`](tests/test_audit_replay.py) /
  [`tests/test_validity_policy.py`](tests/test_validity_policy.py): the reconstruction and
  as-of semantics as deterministic functions (no infra).
- **Live** - [`tests/integration/test_replay_seeded.py`](tests/integration/test_replay_seeded.py):
  the same invariant end-to-end against a real **FalkorDB** service with **no LLM key**, in
  the `replay-invariant` job of [`ci.yml`](.github/workflows/ci.yml). If replay ever leaks a
  later correction into the past, CI goes red.

```
replay(2021) -> Boston (invalid_at un-known; the 2022 move not yet learned)
replay(2023) -> Denver (the correction is now known)
```

## ⚠ Honest limitations

- **Baseline security, not enterprise.** Bearer auth + scoped sessions + rate limits + upload
  caps - safe in a *trusted environment*. RBAC, access-audit logging, GDPR deletion, SOC2,
  and certified isolation are not here. See [SECURITY.md](SECURITY.md).
- **Not production HA.** In-memory session state + in-process queue break multi-replica; the
  scale re-architecture is on the roadmap.
- **Contradiction detection is an LLM call** - reliable on structured input, best-effort on
  prose. `verify_fact`'s measured recall floor is tracked, un-massaged, in
  [PROJECT_STATUS.md](PROJECT_STATUS.md).
- **Generation grounding is prompt-instruction only** (a post-hoc faithfulness check is the
  next major roadmap item).
- Full defect ledger: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

## 🛠 Development

```bash
pip install -e ".[dev]" # dependency-free core + dev tools
ruff check .
pytest # contracts + conformance; integration tests self-skip without infra
```

Every number this project publishes comes from a live run - benchmarks carry a content hash
and a reproduce command. Extend it without touching core:
[CONTRIBUTING.md](CONTRIBUTING.md) · [docs/EXTENDING.md](docs/EXTENDING.md) ·
[PROJECT_STATUS.md](PROJECT_STATUS.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
