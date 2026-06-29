# Extending Cogniflow

One page, one worked example per extension point, plus the **exact command** that
certifies a contribution. Everything here uses only the public API - no `core/` edits.

## 1. A policy (validity / retrieval / falsification / writeback)

```python
from datetime import datetime
from cogniflow import register_policy
from cogniflow.core.types import Belief

@register_policy("validity", "closed_interval")
class ClosedIntervalValidity:
    def is_valid(self, belief: Belief, as_of: datetime | None, include_expired: bool = False) -> bool:
        if as_of is not None:
            if belief.valid_at is not None and as_of < belief.valid_at:
                return False
            if belief.invalid_at is not None and as_of > belief.invalid_at:  # inclusive end
                return False
            return True
        return include_expired or belief.is_live
```

Certify it:

```python
from cogniflow import create_policy
from cogniflow.conformance import assert_policy_conforms
assert_policy_conforms("validity", create_policy("validity", "closed_interval"))
```

Select it by config (no code change at the call site):
`build_policies({"validity": "closed_interval"})`. A working copy lives in
[`examples/contrib_policy_example.py`](../examples/contrib_policy_example.py) and the proof
that it needs zero core changes is `tests/test_contributor_proof.py`.

**Family notes:** validity stays boolean; ranking/decay belongs to retrieval;
falsification is read-only (a verdict, never a write) and may be `indeterminate`;
writeback is a pure boolean of the result. An LLM falsification policy is exempt from the
determinism tier but must still pass the invariants (see `cogniflow.verification`).

## 2. A substrate backend

Implement `cogniflow.core.contracts.AsyncSubstrate` (`write` / `read` / `falsify`).

```python
from cogniflow.conformance import run_conformance_async
results = await run_conformance_async(MyBackend(...))
assert all(r.passed for r in results)
```

Optionally implement `cogniflow.core.audit.AuditLedger` for replay; it must satisfy the
un-knowing invariant (a replay to S must not show an invalidation learned after S). The
reference backend is `GraphitiFalkorDBBackend`; Neo4j parity is `tests/integration/
test_neo4j_parity.py` - the same assertions, no weakened check.

## 3. LlamaIndex retriever / postprocessor / tool

Subclass the bridge bases in `cogniflow.bridges.llamaindex` (`TemporalGraphRetriever`,
`TemporalValidityPostprocessor`) or build a `FunctionTool` like
`make_verify_fact_tool`. Override the `_a*` (async) methods. The postprocessor must
receive the substrate's validity instance (one instance, not one class) - injection is
required, there is no silent default.

## 4. Replay exporter / eval scenario

Use `cogniflow.eval.score_falsification(policy, cases)` to score a contradiction set;
report precision/recall (recall is the headline for an audit ledger). Add cases to grow
the corpus over time.

## 5. Archive store (scale)

Implement `cogniflow.core.archive.ArchiveStore` (`archive` / `load`). Replay must union
hot + cold (`bitemporal_query_archived`), so archiving never breaks history.

## The one rule

If a contribution forces a change inside `core/`, an extension point leaked - file an
issue. The whole architecture is validated by the fact that it should never happen.
