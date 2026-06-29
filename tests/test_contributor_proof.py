"""T5 - THE contributor proof.

A new policy added the way an external contributor would: in a file outside `core/`,
using ONLY the public API (`register_policy`, `create_policy`, `build_policies`, the
conformance suite). If this passes with zero changes to core, the open-source promise is
real - a stranger can extend cogniflow from docs + conformance alone. If core had to
change, an extension point leaked.

This module IS the contribution (it lives in tests/, touches no core file). The same
code is shipped as `examples/contrib_policy_example.py` for the docs.
"""

from __future__ import annotations

from datetime import datetime

from cogniflow import available_policies, build_policies, create_policy, register_policy
from cogniflow.conformance import assert_policy_conforms
from cogniflow.core.types import Belief

# --- the "third-party" contribution (public API only) ------------------------


@register_policy("validity", "closed_interval")
class ClosedIntervalValidity:
    """A contributor's validity policy: invalid_at is INCLUSIVE (closed interval
    [valid_at, invalid_at]), unlike the built-in half-open `strict`. Different
    semantics, same universal contract."""

    def is_valid(
        self, belief: Belief, as_of: datetime | None, include_expired: bool = False
    ) -> bool:
        if as_of is not None:
            if belief.valid_at is not None and as_of < belief.valid_at:
                return False
            if belief.invalid_at is not None and as_of > belief.invalid_at:  # inclusive end
                return False
            return True
        if include_expired:
            return True
        return belief.is_live


# --- the proof ---------------------------------------------------------------


def test_external_policy_registers_and_is_selectable_by_config() -> None:
    assert "closed_interval" in available_policies("validity")
    built = build_policies({"validity": "closed_interval"})["validity"]
    assert isinstance(built, ClosedIntervalValidity)
    assert isinstance(create_policy("validity", "closed_interval"), ClosedIntervalValidity)


def test_external_policy_passes_conformance_zero_core_changes() -> None:
    # Certified by the SAME suite a core policy uses - no weakened check.
    assert_policy_conforms("validity", create_policy("validity", "closed_interval"))


def test_closed_interval_semantics_differ_from_strict() -> None:
    # at as_of == invalid_at: strict (half-open) excludes; closed_interval includes.
    from datetime import timezone

    def w(y: int) -> datetime:
        return datetime(y, 1, 1, tzinfo=timezone.utc)

    belief = Belief(id="b", statement="x", created_at=w(2019), valid_at=w(2019), invalid_at=w(2022))
    strict = create_policy("validity", "strict")
    closed = create_policy("validity", "closed_interval")
    assert strict.is_valid(belief, w(2022)) is False
    assert closed.is_valid(belief, w(2022)) is True
