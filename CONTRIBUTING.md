# Contributing to Cogniflow

Cogniflow is built so you can extend it **without touching `core/`**. Every capability
is a registered plugin certified by a conformance suite. If you can make the suite pass
from your own module, your contribution is done - and if you ever *have* to edit `core/`
to add a plugin, that is a bug in our extension points, not in your code: please open an
issue, you have found a leak.

## The contract is the conformance suite

The public contracts live in `cogniflow.core` and are SemVer'd. A contribution is
"correct" when it passes the matching conformance suite - the same suite the built-in
implementations pass. We never weaken a check to accept a contribution or a backend; if a
check blocks you, the fix is in the code or the contract, never the check.

## Where to plug in

See [docs/EXTENDING.md](docs/EXTENDING.md) for one worked example per extension point and
the exact command that certifies it. The extension points:

| Surface | Register / subclass | Conformance |
|---|---|---|
| Validity / Retrieval / Falsification / Writeback policy | `@register_policy(family, name)` | `assert_policy_conforms(family, policy)` |
| Substrate backend | implement `AsyncSubstrate` | `run_conformance_async(backend)` |
| Audit ledger | implement `AuditLedger` | replay invariants (see EXTENDING) |
| Retriever / Postprocessor / Tool (LlamaIndex) | subclass the bridge base | bridge tests |
| Replay exporter / Eval scenario | `cogniflow.eval` harness | precision/recall report |

## Workflow

1. Fork, branch, and add your plugin **in its own module** (or your own package).
2. Run `ruff check .` and `pytest` (unit). For backend/integration work, run the
   integration suite against a real backend (`docker run -p 6379:6379 falkordb/falkordb`)
 - the CI integration lane does the same.
3. If you change a **core contract**, open an RFC first (see
   [docs/RFC_TEMPLATE.md](docs/RFC_TEMPLATE.md)) - breaking a contract breaks every plugin.
4. Open a PR. Unit CI must be green; integration CI runs over real backends.

## Labels

- `good-first-issue` - a new reference policy or eval scenario (low blast radius).
- `help-wanted: research` - the falsification-policy surface (better contradiction
  detection, recall improvements). This is where the open research is.

## Standards

- Deterministic code is deterministic and invariant-tested; LLM-driven code is bounded
  (timeout + fallback + indeterminate), observable, and **measured** (eval), never
  asserted by one green run.
- Provenance always. Replay correctness over archived history is non-negotiable.
- No em dashes in commit/PR text; no AI-attribution co-authors.
