"""Stable core types - the data the substrate moves around.

These dataclasses are the public contract surface. Their field sets are frozen by
``tests/test_contracts_stable.py``; adding/removing a field is a deliberate,
breaking change. Standard library only.

The bi-temporal model mirrors the design analysis: a belief carries an *event-time*
interval (``valid_at`` .. ``invalid_at``) describing when it was true in the world,
and a *system-time* pair (``created_at`` / ``expired_at``) describing when the
substrate believed it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    """Timezone-aware UTC now. All timestamps in cogniflow are UTC."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Belief:
    """A single fact with bi-temporal validity - the unit of truth.

    ``valid_at`` / ``invalid_at`` = event-time interval (true in the world).
    ``created_at`` / ``expired_at`` = system-time interval (believed by the substrate).
    A live, currently-true belief has ``expired_at is None`` and
    ``invalid_at is None``.
    """

    id: str
    statement: str
    created_at: datetime
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    expired_at: datetime | None = None
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    confidence: float | None = None
    provenance: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_live(self) -> bool:
        """True if the substrate has not marked this belief superseded."""
        return self.expired_at is None

    def is_valid_at(self, t: datetime) -> bool:
        """Event-time validity test: was this fact true at instant ``t``?"""
        if self.valid_at is not None and t < self.valid_at:
            return False
        if self.invalid_at is not None and t >= self.invalid_at:
            return False
        return True


@dataclass(frozen=True, slots=True)
class Episode:
    """A raw source unit handed to ``Substrate.write`` for ingestion."""

    id: str
    content: str
    reference_time: datetime
    source: str = "text"
    source_description: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """A point-in-time query against the substrate."""

    text: str
    as_of: datetime | None = None
    top_k: int = 5
    include_expired: bool = False
    filters: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ScoredBelief:
    """A belief paired with a retrieval score."""

    belief: Belief
    score: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """The result of ``Substrate.read`` - beliefs plus the resolved as-of."""

    query: RetrievalQuery
    results: Sequence[ScoredBelief] = ()
    as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class FalsificationVerdict:
    """The outcome of ``Substrate.falsify`` for one target belief.

    ``indeterminate`` distinguishes "I cannot tell" from a confident
    ``superseded=False``. A policy that lacks the information to adjudicate (e.g. an
    interval rule given a belief with no ``valid_at``) must set ``indeterminate=True``,
    so a downstream verify loop never reads a silent ``False`` as "verified clean".
    """

    target_id: str
    superseded: bool
    invalid_at: datetime | None = None
    superseded_by: str | None = None
    rationale: str = ""
    indeterminate: bool = False


@dataclass(frozen=True, slots=True)
class WriteReceipt:
    """The outcome of ``Substrate.write`` for one episode."""

    episode_id: str
    created_belief_ids: tuple[str, ...] = ()
    invalidated_belief_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProvenanceTrace:
    """The "why" behind a belief: what asserted it, and what superseded it.

    ``asserted_by`` are the episode ids that introduced the belief. If the belief was
    superseded, ``superseded_by_belief`` / ``superseded_by_episode`` name the fact and
    the ingestion that ended it; ``invalid_at`` (event-time) and ``expired_at``
    (system-time) are when it stopped being true and when the system learned that.
    """

    belief_id: str
    asserted_by: tuple[str, ...] = ()
    superseded_by_belief: str | None = None
    superseded_by_episode: str | None = None
    invalid_at: datetime | None = None
    expired_at: datetime | None = None
