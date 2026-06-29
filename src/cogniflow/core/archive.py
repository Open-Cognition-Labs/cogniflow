"""Partition / archive for unbounded growth (T2).

Append-only-forever (the point of an audit ledger) means the graph grows without
bound. The strategy:

- Hot path scopes to ``group_id`` (the backend driver is per-group), so queries never
  scan all history.
- Cold archive moves old, invalidated edges to cheaper storage - but **recoverably**.

The load-bearing constraint: archiving must not break replay. A system-time replay to
a past S needs the edges live at S, some of which may be archived, so the replay path
must UNION hot + cold when S falls in the archived range (slower, but correct). The
un-knowing invariant still holds over archived data because the pure replay functions
are oblivious to where a belief was stored.

This module provides the seam (an ``ArchiveStore`` Protocol + an in-memory reference)
and archive-aware replay helpers. A production cold store (object storage / a cold DB
table) implements the same Protocol; see PROJECT_STATUS for the scale plan.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from .audit import bitemporal_query, system_time_replay
from .types import Belief


@runtime_checkable
class ArchiveStore(Protocol):
    """Cold storage for archived (recoverable) beliefs."""

    def archive(self, beliefs: Sequence[Belief]) -> None: ...

    def load(self, group_id: str | None = None) -> list[Belief]: ...


class InMemoryArchive:
    """Reference ArchiveStore (tests / small deployments). Swap for object storage or a
    cold DB table behind the same Protocol at scale."""

    def __init__(self) -> None:
        self._beliefs: list[Belief] = []

    def archive(self, beliefs: Sequence[Belief]) -> None:
        self._beliefs.extend(beliefs)

    def load(self, group_id: str | None = None) -> list[Belief]:
        if group_id is None:
            return list(self._beliefs)
        return [b for b in self._beliefs if b.metadata.get("group_id") == group_id]


def system_time_replay_archived(
    hot: Sequence[Belief], archive: ArchiveStore, system_time: datetime, group_id: str | None = None
) -> list[Belief]:
    """Replay over hot + cold. Recoverability is non-negotiable: archived edges still
    participate, so a replay to a past S is correct even after archiving."""
    return system_time_replay([*hot, *archive.load(group_id)], system_time)


def bitemporal_query_archived(
    hot: Sequence[Belief],
    archive: ArchiveStore,
    system_time: datetime,
    event_time: datetime,
    group_id: str | None = None,
) -> list[Belief]:
    return bitemporal_query([*hot, *archive.load(group_id)], system_time, event_time)
