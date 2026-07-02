# The context-serving API 

Cogniflow as a standalone **context engine**: query in, temporally-correct *context* out,
callable by any model. **The output is context, not an answer** - Cogniflow serves
validated, provenance-carrying facts; the consuming model generates the answer.

## Context API vs Audit API (two surfaces, one engine)

| | **Context API (this, A.3)** | **Audit API ** |
|---|---|---|
| Consumer | a model / agent | a human / compliance reader |
| Access | query-driven ("context for this") | inspection-driven ("show the timeline") |
| Output | structured context (facts + metadata) | the ledger (timelines, replay, traces) |
| Shape | model-neutral, machine-consumable | human-readable, visual |

## The contract (G1) - honesty labels are structural, not bolted on

`serve_context(substrate, query, *, as_of=None, top_k=5, include_expired=False, filters=None)`
returns a `ContextResponse`. Each `ServedFact` carries:

| field | meaning |
|---|---|
| `statement` | the fact text |
| `valid_at` / `invalid_at` | the event-time validity interval |
| `valid_at_source` | **confidence**: `authoritative` / `derived` / `none` |
| `valid_at_source_raw` | the producer's original label (nothing hidden) |
| `provenance` | the episode(s) that asserted the fact |
| `superseded_by` | the belief that replaced it, if any |
| `score` | per-fact relevance |

`ContextResponse` adds `query`, the resolved `as_of`, and `notes` (the limits, surfaced).
`to_dict()` yields machine-consumable JSON the caller formats into *its own* prompt - the
output is never pre-formatted for one model's style.

### `valid_at_source` normalization
The producer's raw label is normalized into a 3-way confidence signal (raw is also carried):

| raw (from ingestion) | normalized | why |
|---|---|---|
| `provided` | `authoritative` | the caller explicitly asserted the reference time |
| `okf:timestamp` | `derived` | OKF declares a timestamp but has no validity model |
| `document:mtime` | `derived` | inferred from file metadata |
| `none` / absent | `none` | no validity signal |

A consumer should weight a `derived` stamp differently from an `authoritative` one. This is
the load-bearing promise: the label that was honest at ingestion (A.2) is honest at output.

## The as-of axis is first-class (T2)
`as_of` is an API parameter, not a hidden mode. The same query at two `as_of` values returns
different context - temporally-correct context is the thing no other context API serves.

## Serving surfaces (T4) - MCP first, HTTP underneath

Both are **read-only** and **self-hostable** (they run in the caller's environment, so data
never leaves), each behind an optional extra so the core carries no web/agent framework.

**MCP** (`pip install 'cogniflow-rag[mcp]'`) - the primary "any model calls it" path:
```python
from cogniflow.serving import build_mcp_server
server = build_mcp_server(substrate) # exposes a read-only get_context tool
server.run() # stdio; any MCP client (Claude Desktop, Cursor, ...)
```

**HTTP/REST** (`pip install 'cogniflow-rag[serve]'`) - for non-MCP consumers:
```python
from cogniflow.serving import create_app
app = create_app(substrate) # POST /context -> the G1 contract as JSON
# cogniflow.serving.http.run(substrate) # uvicorn on 127.0.0.1 (loopback by default)
```

Write-back is **not** on this surface - the read API never writes (the `record_observation`
seam is exposed separately, by its own decision).

## Limits, surfaced at the edge (T5) - not hidden in a footnote

- **Extraction floor.** Facts from structured input (OKF `fact` keys) carry authoritative
  time; facts extracted from prose are only as reliable as the extraction model, and may
  carry a derived or no validity stamp. Measured here: concrete factual statements extract
  reliably; abstract definitional prose may extract nothing. This note ships in every
  `ContextResponse.notes`, and each fact's `valid_at_source` carries the per-fact signal.
- **Derived temporality.** A `derived` stamp was inferred, not asserted - treat it as such.

A context engine that hides its floor invites the exact misplaced trust the honesty labels
exist to prevent.

## What this is not
- Not a generator - it serves context, the model answers.
- Not the audit/replay dashboard - that is module (human consumer, the ledger as output).
- Not a write surface - read-only by construction.
