<div align="center">

<img src="docs/media/logo.png" alt="RAGBrain" width="300">


# RAGBrain

**The bi-temporal RAG platform. Prove what your AI knew, and when.**

Any document in, a cited and temporally-correct answer out, plus the capability the rest of
the field lacks: replay what the system believed at any past moment, without leaking later
corrections into the past.

[![ci](https://github.com/Nagendhra-Madishetti/ragbrain/actions/workflows/ci.yml/badge.svg)](https://github.com/Nagendhra-Madishetti/ragbrain/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

[Quick start](#quick-start) ·
[Architecture](#architecture) ·
[Benchmarks](#benchmarks) ·
[API](#api) ·
[Documentation](#documentation)

</div>

---

## Why RAGBrain

Every fact is stored on two independent time axes: when it was true in the world (event
time) and when the system learned it (system time). The second axis is what makes answers
defensible rather than merely plausible.

Consider one fact that changed: Acme Corp's HQ was Boston (2019 filing), then Denver
(2022 filing).

| Question | Vector RAG | Valid-time RAG | RAGBrain |
|---|---|---|---|
| Where is Acme HQ now? | ✅ Denver | ✅ Denver | ✅ Denver |
| Where was it in 2020? | ❌ | ✅ Boston | ✅ Boston |
| What did we believe in 2021, before the 2022 filing? | ❌ | ❌ | ✅ **Boston, Denver un-known** |
| Show the timeline and what superseded what | ❌ | ⚠️ partial | ✅ full provenance and audit |

The third row is system-time replay. It requires an independent record of when each fact was
learned, and the discipline never to let a later correction leak into a past belief state:
the un-knowing invariant, enforced in CI against a live graph store.

## Capabilities

- **Bi-temporal knowledge graph.** Four timestamps per fact (`valid_at`, `invalid_at`,
  `created_at`, `expired_at`) in FalkorDB or Neo4j.
- **As-of retrieval.** Ask any question as of any instant; context is validity-filtered
  before ranking.
- **System-time replay and audit.** Reconstruct what the system believed at any past moment;
  a live web scrubber makes it visible.
- **Supersession with provenance.** A correcting fact expires the old one and stamps a
  `superseded_by` back-link at write time; every answer carries citations.
- **Checked generation.** Answers are verified claim-by-claim against the served facts after
  generation; unsupported claims are flagged, never silently shipped.
- **Pluggable everything.** Embedder, reranker, generation model, and graph backend are
  config-selected and fail loud; bring hosted APIs or fully local models.
- **Secure by default.** Bearer-token auth, token-scoped sessions, rate limits, upload caps.
- **Multi-replica ready.** Shared session state and a shared durable write-back journal,
  proven by a two-replica test; a metrics endpoint for operations.
- **Self-hostable end to end.** Your documents, your models, your infrastructure.

## Quick start

Prereqs: Docker. No API keys required for the demo.

```bash
git clone https://github.com/Nagendhra-Madishetti/ragbrain && cd ragbrain
docker compose up -d --build
bash scripts/demo.sh
```

The demo seeds the Acme scenario and asserts four answers:

```
now              -> Denver
as of 2020       -> Boston
replay(2021)     -> Boston   (the 2022 Denver correction is un-known)
timeline         -> Boston (2019 report) superseded by Denver (2022 press release)
```

Open the live scrubber at http://localhost:3000/playground and drag the system-time slider
across 2022; the answer flips in front of you:

![System-time replay: scrubbing past the 2022 correction flips the belief Boston to Denver](docs/media/replay-scrubber.gif)

### Install as a library

```bash
pip install ragbrain          # import ragbrain
pip install "ragbrain[all,serve]"   # backends + the platform API
```

## Architecture

<img width="1060" height="923" alt="RAGBrain architecture" src="docs/media/architecture.png" />
The core is dependency-free: `ragbrain.core` imports only the standard library. Storage,
models, and retrieval are adapters behind stable interfaces, selected by configuration.

### The bi-temporal model

- Event time `[valid_at, invalid_at)`: when the fact was true in the world. Answers
  "as of 2020".
- System time `[created_at, expired_at)`: when the system learned or retracted it. Answers
  "what did we believe at S" and powers the un-knowing replay.
- A correction supersedes: the old fact receives `invalid_at` (event) and `expired_at`
  (system) plus a `superseded_by` back-link, stamped at write time.
- Replay to S drops everything learned after S, including the knowledge that a fact was
  later corrected. That is the invariant, enforced two ways: as pure deterministic tests and
  live against a FalkorDB service in CI (`tests/integration/test_replay_seeded.py`).

## Benchmarks

All published numbers come from live, reproducible runs on a fictional corpus (invented
companies, dates only in metadata), so no model can answer from training. Results carry a
content hash and a reproduce command; scores are claims exactly the size of the measurement.

| Comparison | Chart |
|---|---|
| As-of questions vs LlamaIndex, LangChain, Haystack, and a temporal-graph ablation | ![As-of benchmark](docs/media/benchmark-asof.png) |
| Current-fact questions (the honest tie) | ![Standard benchmark](docs/media/benchmark-standard.png) |

Reproduce: `python demo/benchmark_frameworks.py`. Full per-question answers, methodology,
and the measured evaluation floors (verify recall, faithfulness checker precision and recall)
are in the web app's Benchmark page and [PROJECT_STATUS.md](PROJECT_STATUS.md).

## API

Every route except `/api/health` requires a bearer token (`RAGBRAIN_API_TOKENS`; the compose
stack provisions `ragbrain-demo-token`). A session is scoped to the token that created it.

```bash
TOKEN=ragbrain-demo-token
API=http://localhost:8000
H="Authorization: Bearer $TOKEN"

curl -H "$H" -X POST "$API/api/demo/seed"
curl -H "$H" "$API/api/audit/current?session_id=demo_acme"
curl -H "$H" "$API/api/audit/event?session_id=demo_acme&as_of=2020-06-01"
curl -H "$H" "$API/api/audit/replay?session_id=demo_acme&system_time=2021-06-01"
curl -H "$H" "$API/api/audit/timeline/demo-belief-boston?session_id=demo_acme"

curl -H "$H" -H 'Content-Type: application/json' -X POST "$API/api/context" \
     -d '{"session_id":"mine","query":"Where is Acme headquartered?","as_of":"2020-06-01"}'
```

Ingest your own documents (local; data never leaves your environment):

```bash
cp .env.example .env    # provider keys for generation and semantic retrieval
curl -H "$H" -F session_id=mine -F reference_time=2019-01-01 \
     -F file=@your_report.pdf "$API/api/ingest"
```

For semantic retrieval configure a real embedder: `RAGBRAIN_EMBEDDER=bge-m3-local`
(key-free, requires the `[embeddings]` extra) or `RAGBRAIN_EMBEDDER=bge-m3` with
`RAGBRAIN_EMBEDDER_API_KEY`. The key-free boot default (`hash`) is lexical and states so
loudly in every response until a real embedder is configured.

## Deployment

- Local and trusted environments: `docker compose up -d --build`.
- Multi-replica: `docker compose -f docker-compose.yml -f docker-compose.replicas.yml up -d`
  with `RAGBRAIN_SHARED_STATE=1`; verify with `bash scripts/two_replica_proof.sh`.
- Operations: an authenticated `/metrics` endpoint exposes per-replica counters.
- Security posture, scope, and the operator checklist: [SECURITY.md](SECURITY.md).
  Project status and measured evaluation floors: [PROJECT_STATUS.md](PROJECT_STATUS.md).
  Defect ledger: [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md).

## Documentation

| Topic | Where |
|---|---|
| Context-serving API | [docs/CONTEXT_API.md](docs/CONTEXT_API.md) |
| Audit and replay | [docs/AUDIT_DASHBOARD.md](docs/AUDIT_DASHBOARD.md) |
| Document ingestion | [docs/DOCUMENT_INGESTION.md](docs/DOCUMENT_INGESTION.md) |
| Embedders | [docs/EMBEDDERS.md](docs/EMBEDDERS.md) |
| Generation and faithfulness | [docs/GENERATION.md](docs/GENERATION.md) |
| Extending without touching core | [docs/EXTENDING.md](docs/EXTENDING.md), [CONTRIBUTING.md](CONTRIBUTING.md) |

## Development

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
