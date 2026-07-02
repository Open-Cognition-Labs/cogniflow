# Why a valid-time filter can't do system-time replay

*The canonical explainer for Cogniflow (draft - publish with the launch). All claims scoped;
the runnable proof is `docker compose up && bash scripts/demo.sh` from the repo.*

## The two time axes

Every fact in a changing world has two independent histories:

- **Valid time (event time):** when the fact was true in the world.
  *"Acme's HQ was Boston from 2019 to 2022, then Denver."*
- **Transaction time (system time):** when your system learned it.
  *"We ingested the Boston filing in 2019 and the Denver press release in 2022."*

Most "temporal RAG" work - time-aware retrieval, timestamp filters, validity metadata - lives
entirely on the first axis. That is genuinely useful: it answers *"what was true in 2020?"*
This piece is about the question it structurally cannot answer.

## The question a valid-time filter cannot answer

> "What did the system **believe** in 2021, before the 2022 correction arrived?"

Suppose you store validity intervals and even maintain them on correction: when the Denver
fact arrives, you close Boston's interval (`valid: 2019 -> 2022`). Now replay 2021 with a
valid-time filter (`valid_at <= 2021 < invalid_at`):

- Boston fails the filter or shows as *already ended in 2022* - but in 2021 **you did not yet
  know it would end in 2022**. The knowledge of the correction has leaked backward into the
  past belief state.
- There is no record of *when Denver arrived*, so nothing stops it from appearing in a replay
  of a time before you learned it.

The failure isn't a bug in the filter - it's a missing axis. One timestamp column cannot
represent both "when true" and "when learned," and correction updates destroy the evidence of
what you believed before them.

## The un-knowing invariant

System-time replay needs two disciplines:

1. **Record transaction time independently** - `created_at` (learned) and `expired_at`
   (retracted) per fact, alongside `valid_at`/`invalid_at`.
2. **Un-know on replay** - replaying to system-time S must (a) exclude every fact learned
   after S (`created_at <= S`), and (b) strip every invalidation that was *learned* after S,
   so a fact you believed live at S reads as live and un-superseded, exactly as you believed
   it - not with its current, later-learned end date.

(2) is the part implementations get wrong, so we gave it a name - **the un-knowing
invariant** - and machine-enforced it: a pure deterministic test plus a live test against a
real graph store run in CI (a FalkorDB service container, no model key needed). If replay
ever leaks a later correction into the past, CI goes red.

## What this buys you

- **Auditability:** "show me what the system knew when it made that decision" becomes a
  query, not an archaeology project.
- **Defensible answers:** every answer carries the facts it stood on, their validity, their
  provenance, and - because generation is post-hoc checked against those facts - a
  faithfulness verdict.
- **Honest corrections:** superseding a fact stamps `superseded_by` at write time; the old
  belief remains replayable, the new one carries its lineage.

## What I am NOT claiming

- Not "the first temporal RAG" - valid-time filtering exists in several systems, and
  bi-temporal modeling is decades old in databases (SQL:2011, Snodgrass). The claim is
  narrower: honest system-time replay with the un-knowing invariant, shipped as self-hostable
  RAG infrastructure with the invariant enforced in CI.
- Not better recall - retrieval quality is inherited from the embedder you configure, and the
  benchmark shows ties on standard questions by design.
- Not solved extraction - prose fact-extraction is LLM-bounded and labeled per fact
  (`valid_at_source`); structured input is the deterministic path.

## Try the proof

```bash
git clone <repo> && cd cogniflow
docker compose up -d --build
bash scripts/demo.sh # now=Denver · 2020=Boston · replay(2021)=Boston, Denver un-known
```

The third line is the whole argument.
