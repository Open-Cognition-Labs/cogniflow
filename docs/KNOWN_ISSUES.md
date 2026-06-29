# Known issues

## G3 - FalkorDriver ignores the date `search_filter` (confirmed)

**Verdict (empirical, 2026-06-28):** Graphiti's FalkorDB driver does **not** apply the
bi-temporal date filters in `SearchFilters` (`valid_at` / `invalid_at` / `created_at` /
`expired_at`). A raw `graphiti.search(..., search_filter=as_of(2020))` over two facts
(Boston valid_at=2019, Denver valid_at=2022) returned **both** edges, including the
future-valid Denver fact that the filter should have excluded.

**Risk:** false negatives. A fact that is valid at T but ranked outside a naive `top_k`
window would never be seen, and a `top_k`-sized in-process filter could not recover it.

**Mitigation (in place):** `GraphitiFalkorDBBackend.read()` over-fetches a wider candidate
set (`max(top_k * 10, 50)`), applies the single shared `ValidityPolicy` in-process
(`cogniflow.core.policies.filter_valid`), then truncates to `top_k`. Point-in-time
correctness therefore does not depend on the DB-side filter.

**Follow-up (deferred):** push the temporal predicate into the FalkorDB Cypher query (or
switch the date filter on at the driver level) so the database does the work and the
over-fetch factor can shrink. Tracked for the backend-hardening phase.

## P2 - ReAct re-query reliability is LLM-driven (tracked constraint)

The configured LLM (MiniMax-M3 via the NVIDIA OpenAI-compatible endpoint) emits **no
native tool calls**: `llm.get_tool_calls_from_response(...)` returns `[]`. Confirmed in
Phase 1b. The agent is therefore a `ReActAgent`, which drives any chat LLM via a text
Thought/Action/Observation loop and parses the tool call from text.

**Consequence:** the autonomous re-query / critique half of the thesis rides on the
model's ReAct-format adherence, not on a structured tool-calling contract. It is
best-effort and only as reliable as the model. The single-call heartbeat is robust; a
multi-step re-query loop is uncharacterized.

**Trigger to revisit:** configure a function-calling model and switch to `FunctionAgent`
**before** the re-query/critique loop becomes load-bearing (Phase 5 `verify_fact`). At
that point, add a characterization run measuring re-query reliability.

**Breadcrumb for the model swap:** `OpenAILike` on the async path returns empty
`choices` (-> `IndexError`) when `max_tokens` is unset for this reasoning model;
`make_llm` sets `max_tokens=2048`. Revisit when swapping models.

## D2 - the write-back queue is in-process (no durability)

`WriteBackQueue` holds pending observations in per-`group_id` `asyncio.Queue`s. They live
only in memory: **queued-but-unprocessed observations do not survive a process restart**,
so an `EnqueueAck(status="queued")` does not yet imply durability. `drain()` is correct
within a process - it waits for each item's full retry sequence to finish (`task_done` is
called only after `_process` returns, after the successful retry or dead-letter), verified
by `test_drain_waits_for_successful_retry`.

**Follow-up (deferred):** back the queue with a durable log (e.g. Redis stream / a table)
so "queued" survives restarts and dead-letters are recoverable. Tracked for the
backend-hardening phase.
