# The audit/replay dashboard - the moat made visible

A **read-only** window onto the belief ledger for a **human** (a compliance/audit reader who
cannot call a coroutine): what is true now, the life of any fact, what the system believed at
any past moment (correctly un-known), and why. Every landscape tool renders the graph *as it
is now*; none render a belief *timeline*. The replay scrubber is the one screen no plain RAG
can build, because nobody else has system-time replay underneath.

## Distinct from the context API (A.3)

| | **Audit dashboard (this, B)** | **Context API (A.3)** |
|---|---|---|
| Consumer | a human / compliance reader | a model / agent |
| Driven by | inspection ("show the timeline") | a query ("context for this") |
| Output | the ledger (timelines, replay, traces) | context (facts) for generation |
| Shape | human-readable, visual | model-neutral, machine-consumable |

Same engine, different surface. The dashboard never serves context-for-generation; the
context API never renders the ledger. Both are read-only and self-hostable.

## Two temporal axes (do not conflate them)

Cogniflow is **bi-temporal**, so "replay" is two different questions:

- **Event-time axis** - *what was TRUE as of T* (`/audit/event?as_of=T`, over
  `event_time_query`). This is the recognizable demo: scrub to April -> the 7-day definition,
  scrub to July -> the 28-day. It changes with the *content* timeline.
- **System-time axis** - *what the system KNEW as of S* (`/audit/replay?system_time=S`, over
  `system_time_replay`). This is the centerpiece, and it carries the un-knowing invariant.

A live store learns most facts "now", so the system-time axis is only interesting once facts
have distinct learned-at times; the invariant itself is asserted deterministically (see below).

## The centerpiece: the un-knowing invariant, in the UI

> Scrubbed to a past moment S, a fact superseded **after** S must read **believed-then and
> un-superseded** - *not* with its current `invalid_at`.

If the UI showed the current `invalid_at` while scrubbed to the past, it would leak present
knowledge backward in time - the looks-right/is-right trap, now in pixels. The engine un-knows
correctly (`system_time_replay` -> `reconstruct_as_of_system`); this layer's job is to render
**only what the engine returns** and never recompute intervals client-side. The dashboard JS
prints the API's `invalid_at` verbatim, so it cannot re-leak.

The invariant is asserted in `tests/test_audit_api.py::test_centerpiece_replay_un_knows_the_future`:
a fact whose supersession was *learned* in June 2022 is fetched three ways -
its timeline shows the stored `invalid_at` (ground truth), replay at S=2021 shows it with
`invalid_at = null` (un-known), and replay at S=2023 drops it from the live set (no longer the
current truth, correctly). Controlled beliefs are used because the system-time axis is
degenerate on freshly-ingested live data - the same reason the engine's milestone tests do.

## Provenance resolution (G1) - correct, never plausible

A fact's provenance is the episode that asserted it. Two cases, both honest:

- **Documents** (the `add_episode` path) store a Graphiti **episode UUID** with a backing
  `Episodic` node; `resolve_episodes` maps UUID -> the stored episode name (e.g.
  `acme_report_v2#chunk0`). A wrong name in an audit trail is worse than a UUID, so resolution
  is from **stored linkage only** - an unresolvable UUID is shown as the UUID, never guessed
  (`resolved: false`).
- **OKF triples** (the `add_triplet` path) store the **concept id** directly as the episode
  reference, so the display is already human-readable without a lookup.

## Endpoints (all read-only; no write verb is exposed -> 405)

| endpoint | method | meaning |
|---|---|---|
| `/audit/current` | event_time_query(now) | what the system believes now |
| `/audit/event?as_of=T` | event_time_query(T) | what was TRUE at T |
| `/audit/replay?system_time=S` | system_time_replay(S) | what the system KNEW at S (un-knowing) |
| `/audit/bitemporal?system_time=S&event_time=T` | bitemporal_query | as known at S, what was true at T |
| `/audit/timeline/{id}` | get_belief + provenance_trace | a fact's life + its trace (true intervals) |
| `/audit/provenance/{id}` | provenance_trace | source + what superseded it, names resolved |
| `/` | - | the dependency-free dashboard |

The served belief carries the `valid_at_source` confidence label (authoritative / derived /
none) so the human sees how much to trust each temporal stamp - the honesty label that
survived to A.3's machine output, now visible to a person.

## Run it (self-hostable, loopback by default)

```python
from cogniflow.serving import create_audit_app # FastAPI app over an AuditLedger
app = create_audit_app(backend)
# or: cogniflow.serving.audit.run(backend) # uvicorn on 127.0.0.1:8078
```

Behind the `[serve]` extra. Read-only and local: the ledger never leaves the reader's
environment.

## Out of scope (permanently)
No write/edit/agent controls anywhere. Read-only is the design, not a limitation - it is what
keeps the surface small and what makes it trustworthy as an audit record.
