"""Policy registry: config selection (acceptance #1) and fail-loud (acceptance #2).

CI-safe: stdlib + core only, no infra.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cogniflow.core.types import Belief
from cogniflow.registry import (
    FAMILIES,
    PolicyNotFoundError,
    available_policies,
    build_policies,
    create_policy,
)


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def test_every_family_has_at_least_two_reference_policies() -> None:
    for family in FAMILIES:
        names = available_policies(family)
        assert len(names) >= 2, (family, names)


def test_create_unknown_policy_fails_loud() -> None:
    with pytest.raises(PolicyNotFoundError):
        create_policy("validity", "does_not_exist")


def test_create_unknown_family_fails_loud() -> None:
    with pytest.raises(KeyError):
        create_policy("not_a_family", "strict")


def test_build_policies_uses_named_defaults() -> None:
    policies = build_policies()  # no config -> the named defaults
    assert set(policies) == set(FAMILIES)
    assert type(policies["validity"]).__name__ == "DefaultValidityPolicy"
    assert type(policies["writeback"]).__name__ == "NeverWritebackPolicy"


def test_config_selects_policy_and_behavior_changes_no_code_edit() -> None:
    # Acceptance #1: swap validity strict -> grace_window via config alone.
    superseded = Belief(
        id="b",
        statement="x",
        created_at=_dt(2019),
        valid_at=_dt(2019),
        invalid_at=_dt(2022),
        expired_at=_dt(2022),
    )
    as_of = _dt(2022)  # exactly at invalid_at: strict excludes, grace still includes

    strict = build_policies({"validity": "strict"})["validity"]
    grace = build_policies(
        {"validity": "grace_window"}, {"validity": {"grace_days": 400}}
    )["validity"]

    assert strict.is_valid(superseded, as_of) is False
    assert grace.is_valid(superseded, as_of) is True
