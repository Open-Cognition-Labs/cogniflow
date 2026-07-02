"""Dual-axis cache correctness (CI-safe, fake ledger).

The trap: caching current-knowledge event-time answers like the frozen past serves a
stale answer after a write. This proves the split - a write changes the
current-knowledge read while a past system-time replay stays served-from-cache.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from cogniflow.core.audit import reconstruct_as_of_system
from cogniflow.core.cache import CachingAuditLedger
from cogniflow.core.types import Belief


def _w(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


class _FakeLedger:
    """Mutable knowledge set; counts calls so we can see cache hits vs misses."""

    def __init__(self) -> None:
        self.beliefs: list[Belief] = []
        self.event_calls = 0
        self.system_calls = 0

    async def event_time_query(self, as_of, group_id=None):
        self.event_calls += 1
        return [b for b in self.beliefs if b.is_valid_at(as_of)]

    async def system_time_replay(self, system_time, group_id=None):
        self.system_calls += 1
        return [
            reconstruct_as_of_system(b, system_time)
            for b in self.beliefs
            if b.created_at <= system_time
        ]

    async def bitemporal_query(self, system_time, event_time, group_id=None): # pragma: no cover
        return []

    async def provenance_trace(self, belief_id, group_id=None): # pragma: no cover
        return None


def test_dual_axis_cache_trap() -> None:
    async def run() -> None:
        fake = _FakeLedger()
        fake.beliefs.append(
            Belief(id="boston", statement="HQ Boston", created_at=_w(2019), valid_at=_w(2019))
        )
        cache = CachingAuditLedger(fake)

        # current-knowledge event-time, cached
        first = [b.id for b in await cache.event_time_query(_w(2020), "g")]
        assert first == ["boston"]
        await cache.event_time_query(_w(2020), "g") # served from cache
        assert fake.event_calls == 1

        # a past system-time replay, cached (frozen)
        await cache.system_time_replay(_w(2019, ), "g")
        assert fake.system_calls == 1

        # a write arrives: Boston ends 2022, Denver from 2022. Knowledge changed.
        fake.beliefs[0] = Belief(
            id="boston", statement="HQ Boston", created_at=_w(2019),
            valid_at=_w(2019), invalid_at=_w(2022), expired_at=_w(2022),
        )
        fake.beliefs.append(
            Belief(id="denver", statement="HQ Denver", created_at=_w(2022), valid_at=_w(2022))
        )
        cache.note_write("g")

        # current-knowledge read MUST reflect the write (live axis invalidated)
        after = {b.id for b in await cache.event_time_query(_w(2023), "g")}
        assert "denver" in after and "boston" not in after
        assert fake.event_calls == 2 # re-computed, not stale

        # the past system-time replay MUST stay frozen (served from cache, untouched)
        await cache.system_time_replay(_w(2019), "g")
        assert fake.system_calls == 1 # still 1: not recomputed despite the write

    asyncio.run(run())
