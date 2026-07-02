"""Behavioral conformance suites for the four policy families.

The contract a third-party policy must pass before it is trusted. These are
family-universal: they hold for every reference implementation and for any
contributed policy (e.g. a grace_window validity policy still satisfies the validity
suite, because the suite only asserts the universal guarantees, not strict-specific
boundaries).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..core.types import Belief, RetrievalQuery, RetrievalResult, ScoredBelief
from .suite import CheckResult


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _checker() -> tuple[list[CheckResult], Any]:
    results: list[CheckResult] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        results.append(CheckResult(name=name, passed=bool(cond), detail=detail))

    return results, check


def _live_belief() -> Belief:
    return Belief(id="live", statement="x", created_at=_dt(2019), valid_at=_dt(2019))


def _expired_belief() -> Belief:
    return Belief(
        id="exp",
        statement="x",
        created_at=_dt(2019),
        valid_at=_dt(2019),
        invalid_at=_dt(2022),
        expired_at=_dt(2022),
    )


def check_validity_policy(policy: Any) -> list[CheckResult]:
    results, check = _checker()
    live = _live_belief()
    expired = _expired_belief()

    check("is_valid returns bool", isinstance(policy.is_valid(live, _dt(2020)), bool))
    check(
        "deterministic",
        policy.is_valid(expired, _dt(2020)) == policy.is_valid(expired, _dt(2020)),
    )
    check(
        "valid_at boundary is inclusive",
        policy.is_valid(live, _dt(2019)) is True,
        "as_of == valid_at must be valid (half-open lower bound)",
    )
    check(
        "before valid_at is invalid",
        policy.is_valid(live, _dt(2018)) is False,
    )
    check(
        "as_of=None hides a superseded belief",
        policy.is_valid(expired, None) is False,
    )
    check(
        "as_of=None + include_expired shows it",
        policy.is_valid(expired, None, True) is True,
    )
    return results


def check_retrieval_policy(policy: Any) -> list[CheckResult]:
    results, check = _checker()
    beliefs = [
        Belief(id=f"b{i}", statement="x", created_at=_dt(2019), valid_at=_dt(2019 + i))
        for i in range(4)
    ]
    query = RetrievalQuery(text="q", as_of=_dt(2025), top_k=10)

    check("resolve_as_of pure", policy.resolve_as_of(query) == policy.resolve_as_of(query))

    ranked = list(policy.rank(query, beliefs))
    check("rank returns ScoredBelief", all(isinstance(s, ScoredBelief) for s in ranked))
    check("rank preserves count (no drop/invent)", len(ranked) == len(beliefs))
    in_ids = {b.id for b in beliefs}
    out_ids = {s.belief.id for s in ranked}
    check("rank preserves the exact id set", out_ids == in_ids)
    check("rank has no duplicates", len({s.belief.id for s in ranked}) == len(ranked))
    return results


def check_falsification_policy(policy: Any) -> list[CheckResult]:
    results, check = _checker()
    target = Belief(
        id="t", statement="x", created_at=_dt(2019), valid_at=_dt(2019), invalid_at=_dt(2022)
    )
    later = Belief(id="c", statement="x", created_at=_dt(2022), valid_at=_dt(2021))
    candidates = [target, later]

    verdict = policy.assess(target, candidates)
    # All-policy invariants (the future LLM policy must pass these too):
    check("verdict targets the asked belief", verdict.target_id == target.id)
    check("superseded is bool", isinstance(verdict.superseded, bool))
    check("indeterminate is bool", isinstance(verdict.indeterminate, bool))
    # read-only: frozen beliefs cannot be mutated; assert inputs unchanged (no write-time)
    check("does not mutate target", target.invalid_at == _dt(2022) and target.expired_at is None)
    return results


def check_falsification_determinism(policy: Any) -> list[CheckResult]:
    """Determinism is asserted only of policies that CLAIM it (B2 two-tier).

    The LLM-driven falsification policy is not deterministic and is exempt
    from this suite; it must still pass ``check_falsification_policy`` (the invariants).
    """
    results, check = _checker()
    target = Belief(
        id="t", statement="x", created_at=_dt(2019), valid_at=_dt(2019), invalid_at=_dt(2022)
    )
    later = Belief(id="c", statement="x", created_at=_dt(2022), valid_at=_dt(2021))
    candidates = [target, later]
    check("deterministic", policy.assess(target, candidates) == policy.assess(target, candidates))
    return results


def check_writeback_policy(policy: Any) -> list[CheckResult]:
    results, check = _checker()
    empty = RetrievalResult(query=RetrievalQuery(text="q"), results=(), as_of=None)
    nonempty = RetrievalResult(
        query=RetrievalQuery(text="q"),
        results=(ScoredBelief(belief=_live_belief()),),
        as_of=None,
    )
    check("should_persist returns bool", isinstance(policy.should_persist(empty), bool))
    check(
        "deterministic",
        policy.should_persist(nonempty) == policy.should_persist(nonempty),
    )
    return results


_SUITES = {
    "validity": check_validity_policy,
    "retrieval": check_retrieval_policy,
    "falsification": check_falsification_policy,
    "writeback": check_writeback_policy,
}


def run_policy_conformance(family: str, policy: Any) -> list[CheckResult]:
    if family not in _SUITES:
        raise KeyError(f"no conformance suite for family {family!r}")
    return _SUITES[family](policy)


def assert_policy_conforms(family: str, policy: Any) -> None:
    failures = [r for r in run_policy_conformance(family, policy) if not r.passed]
    if failures:
        lines = "\n".join(f" - {r.name}: {r.detail}" for r in failures)
        raise AssertionError(f"{family} policy failed conformance:\n{lines}")
