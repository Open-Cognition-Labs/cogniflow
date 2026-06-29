"""G1 + G3 unit tests (CI-safe, no infra).

G1: there is one event-time-correct definition of "valid at T". The canonical
Boston-superseded-by-Denver case must be visible at as_of=2020 and hidden at
as_of=2023, and the same `filter_valid` the backend uses must agree.

G3: `filter_valid` keeps a valid-at-T belief even when it sits beyond a naive
top_k window in the candidate list (the over-fetch + filter + truncate property).
"""

from __future__ import annotations

from datetime import datetime, timezone

from cogniflow.core.policies import DefaultValidityPolicy, filter_valid
from cogniflow.core.types import Belief


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _boston() -> Belief:
    # True 2019..2022, then superseded: expired_at is set (system-time not live).
    return Belief(
        id="boston",
        statement="Acme Corp is headquartered in Boston",
        created_at=_dt(2019),
        valid_at=_dt(2019),
        invalid_at=_dt(2022),
        expired_at=_dt(2022),
    )


def test_event_time_validity_ignores_liveness() -> None:
    policy = DefaultValidityPolicy()
    boston = _boston()
    # visible at 2020 even though it is no longer live (the heartbeat depends on this)
    assert policy.is_valid(boston, _dt(2020)) is True
    # not visible at 2023 (invalid_at=2022 <= 2023)
    assert policy.is_valid(boston, _dt(2023)) is False


def test_half_open_interval_at_boundary() -> None:
    policy = DefaultValidityPolicy()
    boston = _boston()
    # [valid_at, invalid_at): valid_at boundary included, invalid_at boundary excluded
    assert policy.is_valid(boston, _dt(2019)) is True
    assert policy.is_valid(boston, _dt(2022)) is False


def test_current_query_uses_liveness_not_event_time() -> None:
    policy = DefaultValidityPolicy()
    boston = _boston()
    # as_of=None: a superseded (expired) belief is hidden unless include_expired
    assert policy.is_valid(boston, None) is False
    assert policy.is_valid(boston, None, include_expired=True) is True


def test_filter_valid_recovers_fact_beyond_naive_top_k() -> None:
    # 30 future-valid (invalid at 2020) decoys, then the one valid-at-2020 fact.
    decoys = [
        Belief(
            id=f"decoy-{i}",
            statement=f"future fact {i}",
            created_at=_dt(2021),
            valid_at=_dt(2021),
        )
        for i in range(30)
    ]
    target = _boston()
    candidates = decoys + [target]

    kept = filter_valid(candidates, as_of=_dt(2020))
    top_k = 1
    # naive "fetch top_k then filter" would have taken decoys[:1] -> filtered to nothing
    assert filter_valid(candidates[:top_k], as_of=_dt(2020)) == []
    # over-fetch + filter + truncate keeps the real fact
    assert kept[:top_k] == [target]


def test_t5_regression_validity_agrees_after_generalization() -> None:
    # T5: validity is now "one registered policy among the family". The default
    # ("strict") built via the registry must still match the in-process
    # DefaultValidityPolicy used by the substrate read on the canonical case.
    from cogniflow.registry import create_policy

    registered = create_policy("validity", "strict")
    direct = DefaultValidityPolicy()
    boston = _boston()
    for as_of in (_dt(2019), _dt(2020), _dt(2022), _dt(2023)):
        assert registered.is_valid(boston, as_of) == direct.is_valid(boston, as_of)
    # the heartbeat case specifically
    assert registered.is_valid(boston, _dt(2020)) is True
    assert registered.is_valid(boston, _dt(2023)) is False
