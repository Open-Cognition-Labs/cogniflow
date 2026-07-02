# Launch post drafts (per venue) - milestone

*Drafts only. Publish after: repo public, CI badge green on a real PR, claims audit re-run on
the public HEAD. Every post funnels to the same 60-second proof.*

---

## Show HN (skeptic-first, technical)

**Title:** Show HN: Cogniflow - a RAG that can prove what it believed before a correction

**Body:**

RAG systems overwrite their past. When a fact gets corrected, the old belief is gone or,
worse, the correction leaks backward: ask "what did we know in 2021?" and you get an answer
contaminated by things learned in 2022. For anything audit-shaped (compliance, incident
review, "why did the agent do that?"), that is the whole problem.

Cogniflow stores every fact on two axes - when it was true (valid time) and when the system
learned it (transaction time) - and ships **system-time replay with an un-knowing
invariant**: replaying to 2021 returns the belief state of 2021, with later corrections
correctly un-known. The invariant is enforced in CI against a live graph store (a FalkorDB
service container, deterministic seed, no model key), so it is a tested property, not a
prompt.

Prior art, so nobody has to dig: valid-time filtering exists (several temporal-RAG projects),
and bi-temporal modeling is decades old in databases. What I could not find shipped anywhere
is the *second axis* done honestly in RAG infrastructure - replay that un-knows. That narrow
thing is the project.

Also in the box: as-of retrieval, write-time supersession with provenance, a post-hoc
faithfulness check (answers are verified claim-by-claim against the served facts - a planted
hallucination or a training-knowledge leak past the as-of context gets flagged, measured
checker, numbers published), bearer-token API, one-command compose stack.

What I am NOT claiming: not the first temporal RAG; not better recall (retrieval is inherited
from whatever embedder you configure - the benchmark shows honest ties on standard
questions); prose extraction is LLM-bounded and labeled per fact.

Try it (key-free, ~60 seconds): `docker compose up -d --build && bash scripts/demo.sh` -
it seeds a Boston->Denver correction and asserts: now=Denver, as-of-2020=Boston,
replay(2021)=Boston with Denver un-known.

Three questions I would genuinely like answers to:
1. If you run RAG in a regulated environment, is belief replay something you need, or do
   audit teams accept "we re-ran the query today"?
2. Is there prior art on the un-knowing property in a RAG context I have missed?
3. The GDPR right-to-erasure conflicts structurally with an append-only belief ledger -
   crypto-shredding vs tombstoning: which would your org actually accept?

---

## r/Rag · r/LocalLLaMA (practitioner, demo-first)

**Title:** I built a self-hostable RAG that can replay what it believed before a correction
(bi-temporal, runs fully local)

**Body:**

Quick demo, no keys needed:

```
git clone <repo> && cd cogniflow
docker compose up -d --build
bash scripts/demo.sh
```

It seeds "Acme HQ = Boston (2019 filing)" then "Denver (2022 press release)" and asserts four
answers: now -> Denver; as of 2020 -> Boston; **what did the system believe in 2021 ->
Boston, with the Denver correction un-known**; full timeline with provenance. Then there's a
web scrubber where you drag a system-time slider and watch the belief flip.

The point: every RAG can answer "what's true now." Valid-time filters can answer "what was
true in 2020." Neither can answer "what did we *believe* before the correction" - that needs
a second time axis (when each fact was learned) and the discipline to not leak later
corrections into replays. That's the one thing this does that your current stack doesn't.

Fully local: FalkorDB + FastAPI + Next.js via compose, LLM/embedder/reranker are plugs
(hosted or local - Ollama/vLLM work), your data never leaves. Honest limits in the README
(prose extraction is LLM-bounded; retrieval quality is your embedder; baseline security, not
enterprise). Answers are post-hoc checked against the retrieved facts, so a hallucinated or
training-leaked claim gets flagged in the response.

Would love to know: what breaks when you run it on your docs?

---

## Graphiti / LlamaIndex communities (credit-prominent, warmest audience)

**Title:** Built on graphiti-core: system-time replay with an enforced un-knowing invariant

**Body:**

Cogniflow is built on **graphiti-core's bi-temporal edges** (and speaks LlamaIndex on the
agent side) - this community's work is the reason the second time axis exists at all, so
posting it here first.

What I added on top: a replay layer that takes the `created_at`/`expired_at` stamps seriously
- `system_time_replay(S)` returns the belief state at S with post-S invalidations
**un-known** (a fact you believed live at S reads as live, not with its later-learned end
date). That invariant is enforced in CI against live FalkorDB with a deterministic seed. Plus
write-time `superseded_by` stamping, an audit API + web scrubber, a post-hoc faithfulness
check on generation, and a one-command compose stack.

Two things I'd value this community's eyes on:
1. The FalkorDriver date `search_filter` no-op (documented in the repo's KNOWN_ISSUES): we
   work around it with over-fetch + in-process filtering; a driver-level fix would retire the
   stopgap and I'd rather contribute it upstream than fork.
2. Whether the un-knowing reconstruction's single-learned-at assumption (expired_at as the
   sole post-creation system event) matches graphiti's stamping guarantees everywhere.

Demo: `docker compose up -d --build && bash scripts/demo.sh`.

---

## Launch-week posture (T4, carried)

- Answer every substantive comment honestly; link KNOWN_ISSUES before a skeptic finds it.
- Strangers' dry runs are free QA: triage what breaks, log demand to the F6 backlog.
- Promise nothing in comments; demand goes to the backlog.
