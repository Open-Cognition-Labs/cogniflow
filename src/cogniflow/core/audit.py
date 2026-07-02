"""The audit / replay layer (L5): the dual-axis bi-temporal model as an explicit,
read-only surface.

Two orthogonal questions:

- event-time: "what was TRUE IN THE WORLD at T?" -> valid_at / invalid_at
- system-time: "what did the SYSTEM BELIEVE at S, and why?" -> created_at / expired_at

The centerpiece is the *un-knowing* invariant. Graphiti stamps ``invalid_at``
(event-time) and ``expired_at`` (system-time) together at the instant it resolves a
contradiction. So a superseded fact carries an ``invalid_at`` value *today*, but the
system did not possess that knowledge until ``expired_at``. A correct replay to
system-time S must therefore treat an invalidation learned after S as **un-known** -
from S's vantage the fact is live and un-superseded. Filtering only on ``expired_at``
while showing today's ``invalid_at`` leaks knowledge backward in time and turns the
ledger into a lie.

All functions here are pure and deterministic - no LLM, no I/O - so they can be
invariant-tested exhaustively. The backend's AuditLedger pushes the system-time
predicate to the database (replay is a scan, not a search) and then applies this
reconstruction to the bounded candidate set.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from .types import Belief, ProvenanceTrace


def known_at(belief: Belief, system_time: datetime) -> bool:
    """Did the system KNOW of this belief at S? (``created_at <= S``).

    A superseded belief is still *known* - the system remembers Boston was HQ
    2019..2022 even after it learned Boston ended. Knowledge is not forgetting. This
    is the predicate for bitemporal "as known at S, what was true at T" queries.
    """
    return belief.created_at <= system_time


def believed_at(belief: Belief, system_time: datetime) -> bool:
    """Was this belief the system's LIVE/current truth at S?

    Known by S (``created_at <= S``) and not yet retired as-known-by-S
    (``expired_at IS NULL`` OR ``expired_at > S``). This is the predicate for
    ``system_time_replay`` - "what did the system hold to be currently the case at S".
    A bitemporal query about a *past* T uses :func:`known_at` instead, because a
    retired fact still describes history.
    """
    if belief.created_at > system_time:
        return False
    return belief.expired_at is None or belief.expired_at > system_time


def reconstruct_as_of_system(belief: Belief, system_time: datetime) -> Belief:
    """Rebuild a belief's intervals as the system actually knew them at S.

    If the invalidation was learned after S (``expired_at > S``, or there is an
    ``invalid_at`` with no recorded learning time), un-know it: drop ``invalid_at``
    and ``expired_at`` for this replay, so the belief reads live and un-superseded
    from S's vantage. If the invalidation was already known by S, keep it.

    ASSUMPTION (G4a): this treats ``expired_at`` as the single learned-at timestamp,
    i.e. the only system-time learning after a belief's ``created_at`` is its
    invalidation. ``valid_at`` and the original ``invalid_at`` are assumed known at
    ``created_at``. A backend that *revises* ``valid_at``/``invalid_at`` after creation
    (not just stamps an invalidation) would need a per-stamp learned-at history to
    replay correctly; this reconstruction would silently show post-S revisions. The
    Graphiti backend stamps invalidation atomically and does not revise prior stamps,
    so the assumption holds there. Revisit if a backend violates it.
    """
    expired = belief.expired_at
    if expired is not None and expired <= system_time:
        return belief # the invalidation was already known at S - keep it
    if belief.invalid_at is None and belief.expired_at is None:
        return belief # nothing to un-know
    return dataclasses.replace(belief, invalid_at=None, expired_at=None)


def system_time_replay(beliefs: Sequence[Belief], system_time: datetime) -> list[Belief]:
    """Beliefs the system held at S, each with S-reconstructed intervals."""
    return [
        reconstruct_as_of_system(b, system_time)
        for b in beliefs
        if believed_at(b, system_time)
    ]


def event_time_query(
    beliefs: Sequence[Belief],
    as_of: datetime | None,
    include_expired: bool = False,
) -> list[Belief]:
    """What was true in the world at T, using current knowledge (stored intervals)."""
    out: list[Belief] = []
    for belief in beliefs:
        if as_of is not None:
            if belief.is_valid_at(as_of):
                out.append(belief)
        elif include_expired or belief.is_live:
            out.append(belief)
    return out


def bitemporal_query(
    beliefs: Sequence[Belief],
    system_time: datetime,
    event_time: datetime,
) -> list[Belief]:
    """The killer query: as KNOWN at system-time S, what was true at world-time T.

    Uses :func:`known_at` (not the live predicate): a fact superseded by S is still
    known at S and still describes history, so it must be eligible. Reconstruct each
    known belief as of S (un-knowing post-S invalidations), then filter by world
    validity at T using the S-reconstructed intervals.
    """
    out: list[Belief] = []
    for belief in beliefs:
        if known_at(belief, system_time):
            reconstructed = reconstruct_as_of_system(belief, system_time)
            if reconstructed.is_valid_at(event_time):
                out.append(reconstructed)
    return out


@runtime_checkable
class AuditLedger(Protocol):
    """An optional, read-only replay capability a backend opts into.

    Separate from ``AsyncSubstrate`` (basic substrate conformance does not require
    replay). Every method is side-effect-free: it answers, it never mutates the graph.
    """

    async def event_time_query(
        self, as_of: datetime, group_id: str | None = None
    ) -> list[Belief]: ...

    async def system_time_replay(
        self, system_time: datetime, group_id: str | None = None
    ) -> list[Belief]: ...

    async def bitemporal_query(
        self, system_time: datetime, event_time: datetime, group_id: str | None = None
    ) -> list[Belief]: ...

    async def provenance_trace(
        self, belief_id: str, group_id: str | None = None
    ) -> ProvenanceTrace: ...
