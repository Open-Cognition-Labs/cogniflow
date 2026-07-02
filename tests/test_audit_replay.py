"""Audit / replay - the deterministic centerpiece (CI-safe, no infra).

The un-knowing invariant is the one place in the project where "looks right" and "is
right" diverge most, so it gets the most adversarial tests. All pure functions; no LLM,
no DB. Also covers B1 (indeterminate verdict) and B2 (two-tier falsification
conformance).
"""

from __future__ import annotations

from datetime import datetime, timezone

from cogniflow.conformance import check_falsification_determinism, run_policy_conformance
from cogniflow.core.audit import (
    bitemporal_query,
    event_time_query,
    reconstruct_as_of_system,
    system_time_replay,
)
from cogniflow.core.types import Belief, FalsificationVerdict
from cogniflow.registry import create_policy


def _w(year: int) -> datetime: # world (event) time
    return datetime(year, 1, 1, tzinfo=timezone.utc)


# System-time line (when the system learned things): t0 < S_BEFORE < E < S_AFTER.
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
E = datetime(2026, 6, 1, tzinfo=timezone.utc) # Denver ingested == Boston superseded (atomic)
S_BEFORE = datetime(2026, 3, 1, tzinfo=timezone.utc)
S_AFTER = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _boston() -> Belief:
    # true in the world 2019..2022; the system learned it ended only at E.
    return Belief(
        id="boston",
        statement="HQ Boston",
        created_at=T0,
        valid_at=_w(2019),
        invalid_at=_w(2022),
        expired_at=E,
    )


def _denver() -> Belief:
    return Belief(id="denver", statement="HQ Denver", created_at=E, valid_at=_w(2022))


def _facts() -> list[Belief]:
    return [_boston(), _denver()]


# --- the un-knowing invariant ------------------------------------------------


def test_reconstruct_unknows_post_S_invalidation() -> None:
    before = reconstruct_as_of_system(_boston(), S_BEFORE)
    assert before.invalid_at is None, "invalidation learned after S must be un-known"
    assert before.expired_at is None


def test_reconstruct_keeps_invalidation_known_by_S() -> None:
    after = reconstruct_as_of_system(_boston(), S_AFTER)
    assert after.invalid_at == _w(2022), "invalidation known by S must be kept"
    assert after.expired_at == E


def test_centerpiece_replay_before_E_shows_boston_live_not_already_ended() -> None:
    # Replay to S<E asking world-time 2023 must return Boston AS LIVE/UN-SUPERSEDED,
    # never "Boston, already known to have ended in 2022". This is the lie this stage
    # exists to prevent.
    result = bitemporal_query(_facts(), S_BEFORE, _w(2023))
    assert [b.id for b in result] == ["boston"]
    assert result[0].invalid_at is None # knowledge of the end is NOT leaked backward


# --- the (S, T) quadrant grid ------------------------------------------------


def test_bitemporal_quadrants() -> None:
    grid = {
        (S_BEFORE, 2020): ["boston"],
        (S_BEFORE, 2023): ["boston"], # un-known end -> still believed valid at 2023
        (S_AFTER, 2020): ["boston"], # now we know Boston was HQ in 2020
        (S_AFTER, 2023): ["denver"], # now we know Boston ended; Denver is current
    }
    for (s, t), expected in grid.items():
        assert [b.id for b in bitemporal_query(_facts(), s, _w(t))] == expected, (s, t)


def test_system_time_replay_live_set() -> None:
    # "what did the system hold to be current at S" (live set)
    assert [b.id for b in system_time_replay(_facts(), S_BEFORE)] == ["boston"]
    assert [b.id for b in system_time_replay(_facts(), S_AFTER)] == ["denver"]


def test_event_time_query_uses_current_knowledge() -> None:
    assert [b.id for b in event_time_query(_facts(), _w(2020))] == ["boston"]
    assert [b.id for b in event_time_query(_facts(), _w(2023))] == ["denver"]


# --- B1: indeterminate verdict ----------------------------------------------


def test_interval_overlap_indeterminate_when_target_has_no_valid_at() -> None:
    policy = create_policy("falsification", "interval_overlap")
    target = Belief(id="t", statement="x", created_at=T0, valid_at=None)
    later = Belief(id="c", statement="x", created_at=T0, valid_at=_w(2024))
    verdict = policy.assess(target, [target, later])
    assert verdict.superseded is False
    assert verdict.indeterminate is True # distinguishable from a confident "not superseded"


# --- B2: two-tier falsification conformance ----------------------------------


class _NonDeterministicFalsification:
    """A policy that is NOT deterministic; it must still pass the all-policy invariants
    (it just is not subject to the determinism tier)."""

    _flip = False

    def assess(self, target: Belief, candidates) -> FalsificationVerdict:
        type(self)._flip = not type(self)._flip
        return FalsificationVerdict(target_id=target.id, superseded=type(self)._flip)


def test_two_tier_nondeterministic_policy_passes_invariants_not_determinism() -> None:
    policy = _NonDeterministicFalsification()
    # invariants (all policies, incl. the future LLM one) must pass:
    assert all(r.passed for r in run_policy_conformance("falsification", policy))
    # determinism tier is allowed to fail for a non-deterministic policy:
    assert any(not r.passed for r in check_falsification_determinism(policy))


def test_deterministic_falsification_passes_both_tiers() -> None:
    policy = create_policy("falsification", "interval_overlap")
    assert all(r.passed for r in run_policy_conformance("falsification", policy))
    assert all(r.passed for r in check_falsification_determinism(policy))
