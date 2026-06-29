"""The four policy interfaces — the pluggable decision points of the substrate.

Each maps to one seam from the design analysis:

  RetrievalPolicy     -> read seam        (resolve as-of, rank candidates)
  ValidityPolicy      -> invalidate seam  (is a belief valid at time t?)
  FalsificationPolicy -> falsify seam     (is a belief superseded, and by what?)
  WritebackPolicy     -> write-back seam  (should an outcome become a new belief?)

Phase 0 ships the *interfaces* plus trivial default implementations so a backend can
be wired end to end. Real policies (LLM-driven contradiction, temporal decay ranking,
selective write-back) are deferred. Standard library only.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from ..registry import register_policy
from .types import Belief, FalsificationVerdict, RetrievalQuery, RetrievalResult, ScoredBelief

_MIN_AS_OF = datetime(1, 1, 1, tzinfo=timezone.utc)


@runtime_checkable
class RetrievalPolicy(Protocol):
    """How a query is turned into ranked candidates."""

    def resolve_as_of(self, query: RetrievalQuery) -> datetime | None: ...

    def rank(self, query: RetrievalQuery, beliefs: Sequence[Belief]) -> Sequence[ScoredBelief]: ...


@runtime_checkable
class ValidityPolicy(Protocol):
    """Whether a belief counts as valid at a given point in time.

    There is exactly ONE definition of "valid at T" in cogniflow (this contract,
    realized by :class:`DefaultValidityPolicy`). Both the substrate read path and
    the agent-layer postprocessor call it. A second copy is a defect.
    """

    def is_valid(
        self, belief: Belief, as_of: datetime | None, include_expired: bool = False
    ) -> bool: ...


@runtime_checkable
class FalsificationPolicy(Protocol):
    """Whether a target belief is superseded by any candidate."""

    def assess(self, target: Belief, candidates: Sequence[Belief]) -> FalsificationVerdict: ...


@runtime_checkable
class WritebackPolicy(Protocol):
    """Whether a retrieval outcome should be persisted back as a new belief."""

    def should_persist(self, result: RetrievalResult) -> bool: ...


# --- reference implementations (registered; the default per family is named) -----


@register_policy("retrieval", "default")
class DefaultRetrievalPolicy:
    """Passes as-of through; assigns no scores (preserves input order)."""

    def resolve_as_of(self, query: RetrievalQuery) -> datetime | None:
        return query.as_of

    def rank(self, query: RetrievalQuery, beliefs: Sequence[Belief]) -> Sequence[ScoredBelief]:
        return [ScoredBelief(belief=b, score=None) for b in beliefs]


@register_policy("retrieval", "recency")
class RecencyRetrievalPolicy:
    """Ranks valid candidates by recency: more-recent ``valid_at`` scores higher.

    Ranking/decay lives here (not in ValidityPolicy, which stays boolean). Total order
    over the input; never drops or invents candidates.
    """

    def resolve_as_of(self, query: RetrievalQuery) -> datetime | None:
        return query.as_of

    def rank(self, query: RetrievalQuery, beliefs: Sequence[Belief]) -> Sequence[ScoredBelief]:
        ordered = sorted(beliefs, key=lambda b: b.valid_at or _MIN_AS_OF, reverse=True)
        n = len(ordered)
        return [ScoredBelief(belief=b, score=float(n - i)) for i, b in enumerate(ordered)]


@register_policy("validity", "strict")
class DefaultValidityPolicy:
    """The single, event-time-correct definition of "valid at T".

    Event-time and system-time are never ANDed:

    - ``as_of`` set  -> point-in-time *replay*: return ``is_valid_at(as_of)`` only.
      ``expired_at`` (system-time liveness) is irrelevant; a fact that was true at
      T must be visible at T even if it has since been superseded.
    - ``as_of`` is ``None`` -> "current" query: valid iff the belief is still live
      (``expired_at is None``), unless ``include_expired`` is set.
    """

    def is_valid(
        self, belief: Belief, as_of: datetime | None, include_expired: bool = False
    ) -> bool:
        if as_of is not None:
            return belief.is_valid_at(as_of)
        if include_expired:
            return True
        return belief.is_live


@register_policy("validity", "grace_window")
class GraceWindowValidityPolicy:
    """Like ``strict``, but a fact stays visible for ``grace_days`` past ``invalid_at``.

    Still boolean and still event-time; only the upper bound is widened. The lower
    bound (``valid_at`` inclusive) and the as_of=None liveness rule are unchanged.
    """

    def __init__(self, grace_days: int = 365) -> None:
        self.grace = timedelta(days=grace_days)

    def is_valid(
        self, belief: Belief, as_of: datetime | None, include_expired: bool = False
    ) -> bool:
        if as_of is not None:
            if belief.valid_at is not None and as_of < belief.valid_at:
                return False
            if belief.invalid_at is not None and as_of >= belief.invalid_at + self.grace:
                return False
            return True
        if include_expired:
            return True
        return belief.is_live


def filter_valid(
    beliefs: Sequence[Belief],
    as_of: datetime | None,
    include_expired: bool = False,
    policy: ValidityPolicy | None = None,
) -> list[Belief]:
    """Keep only beliefs valid under the single shared :class:`ValidityPolicy`.

    The one place validity filtering happens; both the substrate read and the agent
    postprocessor call this, so there is never a second copy of the rule.
    """
    policy = policy or DefaultValidityPolicy()
    return [b for b in beliefs if policy.is_valid(b, as_of, include_expired)]


@register_policy("falsification", "none")
class NoFalsificationPolicy:
    """Never supersedes anything."""

    def assess(self, target: Belief, candidates: Sequence[Belief]) -> FalsificationVerdict:
        return FalsificationVerdict(
            target_id=target.id,
            superseded=False,
            rationale="NoFalsificationPolicy: no read-time falsification",
        )


@register_policy("falsification", "interval_overlap")
class IntervalOverlapFalsificationPolicy:
    """Read-time, side-effect-free supersession assessment (no LLM).

    A target is superseded if a candidate with a later ``valid_at`` overlaps the
    target's event-time interval. Mirrors the interval rule Graphiti applies during
    ingestion, but as a pure read-time verdict: it NEVER writes to the graph and does
    NOT fight write-time supersession. The returned ``invalid_at`` is the earliest
    such candidate's ``valid_at``.
    """

    def assess(self, target: Belief, candidates: Sequence[Belief]) -> FalsificationVerdict:
        target_start = target.valid_at
        if target_start is None:
            return FalsificationVerdict(
                target_id=target.id, superseded=False, rationale="target has no valid_at"
            )
        target_end = target.invalid_at  # event-time end (None = open)
        best: Belief | None = None
        for candidate in candidates:
            if candidate.id == target.id or candidate.valid_at is None:
                continue
            if candidate.valid_at <= target_start:
                continue  # not later
            if target_end is not None and candidate.valid_at >= target_end:
                continue  # target already ended before the candidate begins -> no overlap
            if best is None or candidate.valid_at < best.valid_at:
                best = candidate
        if best is None:
            return FalsificationVerdict(
                target_id=target.id,
                superseded=False,
                rationale="no later overlapping candidate",
            )
        return FalsificationVerdict(
            target_id=target.id,
            superseded=True,
            invalid_at=best.valid_at,
            superseded_by=best.id,
            rationale="interval_overlap: superseded by a later overlapping fact",
        )


@register_policy("writeback", "never")
class NeverWritebackPolicy:
    """Never persists retrieval outcomes."""

    def should_persist(self, result: RetrievalResult) -> bool:
        return False


@register_policy("writeback", "always")
class AlwaysWritebackPolicy:
    """Persists any non-empty retrieval outcome (the simplest active policy)."""

    def should_persist(self, result: RetrievalResult) -> bool:
        return len(result.results) > 0
