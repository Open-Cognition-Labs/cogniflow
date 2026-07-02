"""Write-back queue invariants (CI-safe: stdlib + a fake AsyncSubstrate, no infra).

Covers the deterministic half of milestone acceptance:
 - non-blocking enqueue (returns before ingestion completes)
 - sequential per group_id
 - idempotent under retry (no duplicate, via dedup-by-id) and retry-on-failure
 - bounded backpressure (reject-with-signal, never block/drop)
 - clean drain + freshness surface advances
 - observability emits on every transition (P3 trace-emission contract)
"""

from __future__ import annotations

import asyncio

from cogniflow import observability
from cogniflow.core.types import (
    Episode,
    FalsificationVerdict,
    RetrievalQuery,
    RetrievalResult,
    WriteReceipt,
)
from cogniflow.writeback import Observation, WriteBackQueue


class _FakeBackend:
    """Records written episodes, deduping by episode id (like Graphiti dedup)."""

    def __init__(self, *, fail_times: int = 0) -> None:
        self.episodes: dict[str, Episode] = {}
        self.order: list[str] = []
        self.write_count = 0
        self._fail_times = fail_times

    async def write(self, episode: Episode) -> WriteReceipt:
        self.write_count += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("transient ingestion error")
        self.order.append(episode.id)
        self.episodes[episode.id] = episode # dedup by stable id
        return WriteReceipt(episode_id=episode.id, created_belief_ids=(episode.id,))

    async def read(self, query: RetrievalQuery) -> RetrievalResult: # pragma: no cover
        return RetrievalResult(query=query, results=(), as_of=query.as_of)

    async def falsify(self, target, against=None) -> FalsificationVerdict: # pragma: no cover
        return FalsificationVerdict(target_id=str(target), superseded=False)


class _GatedBackend(_FakeBackend):
    """Write blocks on a gate the test controls - deterministic timing."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()

    async def write(self, episode: Episode) -> WriteReceipt:
        await self.gate.wait()
        return await super().write(episode)


def _obs(i: int, group: str = "g") -> Observation:
    return Observation(id=f"obs-{i}", group_id=group, statement=f"fact {i}")


def test_enqueue_is_non_blocking() -> None:
    async def run() -> None:
        backend = _GatedBackend()

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory)
        try:
            ack = queue.enqueue(_obs(1))
            assert ack.status == "queued"
            # write is gated open -> not ingested yet; freshness must still be None
            await asyncio.sleep(0) # let the worker start and block on the gate
            assert queue.last_ingested_at("g") is None
            backend.gate.set()
            await queue.drain()
            assert queue.last_ingested_at("g") is not None
        finally:
            await queue.aclose()

    asyncio.run(run())


def test_sequential_per_group() -> None:
    async def run() -> None:
        backend = _FakeBackend()

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory)
        try:
            for i in range(5):
                queue.enqueue(_obs(i))
            await queue.drain()
            assert backend.order == [f"obs-{i}" for i in range(5)]
        finally:
            await queue.aclose()

    asyncio.run(run())


def test_idempotent_under_duplicate() -> None:
    async def run() -> None:
        backend = _FakeBackend()

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory)
        try:
            queue.enqueue(_obs(1))
            queue.enqueue(_obs(1)) # same id -> dedup collapses to one stored fact
            await queue.drain()
            assert len(backend.episodes) == 1
            assert backend.write_count == 2 # both attempted, dedup made it harmless
        finally:
            await queue.aclose()

    asyncio.run(run())


def test_retry_on_failure_then_success() -> None:
    async def run() -> None:
        backend = _FakeBackend(fail_times=2) # fails twice, succeeds on attempt 3

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory, max_retries=3, retry_backoff_seconds=0.0)
        try:
            queue.enqueue(_obs(1))
            await queue.drain()
            assert len(backend.episodes) == 1
            assert backend.write_count == 3
        finally:
            await queue.aclose()

    asyncio.run(run())


def test_bounded_backpressure_rejects_with_signal() -> None:
    async def run() -> None:
        backend = _GatedBackend() # never opens -> worker stuck on first write

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory, max_pending_per_group=2)
        try:
            assert queue.enqueue(_obs(1)).status == "queued" # taken by worker, blocks
            await asyncio.sleep(0)
            assert queue.enqueue(_obs(2)).status == "queued" # fills queue (1/2)
            assert queue.enqueue(_obs(3)).status == "queued" # fills queue (2/2)
            rejected = queue.enqueue(_obs(4)) # saturated
            assert rejected.status == "rejected"
            assert rejected.reason == "saturated"
        finally:
            await queue.aclose()

    asyncio.run(run())


def test_observability_emits_on_every_transition() -> None:
    async def run() -> None:
        events: list[str] = []
        observability.clear_sinks()
        observability.add_sink(lambda name, payload: events.append(name))
        backend = _FakeBackend()

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory)
        try:
            queue.enqueue(_obs(1))
            await queue.drain()
        finally:
            await queue.aclose()
            observability.clear_sinks()

        assert "cogniflow.writeback.enqueue" in events
        assert "cogniflow.writeback.start" in events
        assert "cogniflow.writeback.success" in events
        assert "cogniflow.writeback.drain" in events

    asyncio.run(run())


def test_observability_emits_reject_on_saturation() -> None:
    async def run() -> None:
        events: list[str] = []
        observability.clear_sinks()
        observability.add_sink(lambda name, payload: events.append(name))
        backend = _GatedBackend()

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory, max_pending_per_group=1)
        try:
            queue.enqueue(_obs(1))
            await asyncio.sleep(0)
            queue.enqueue(_obs(2))
            queue.enqueue(_obs(3)) # saturated -> reject event
        finally:
            await queue.aclose()
            observability.clear_sinks()

        assert "cogniflow.writeback.reject" in events

    asyncio.run(run())


def test_dead_letters_are_observable() -> None:
    # D1: a retry-exhausted write must be a first-class signal, not silent loss.
    async def run() -> None:
        events: list[str] = []
        observability.clear_sinks()
        observability.add_sink(lambda name, payload: events.append(name))
        backend = _FakeBackend(fail_times=5) # always fails within max_retries

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory, max_retries=2, retry_backoff_seconds=0.0)
        try:
            queue.enqueue(_obs(1))
            await queue.drain()
        finally:
            await queue.aclose()
            observability.clear_sinks()

        assert queue.failed_count("g") == 1
        status = queue.freshness("g")
        assert status.degraded is True
        assert status.failed_count == 1
        assert status.last_ingested_at is None # never succeeded, and it says so honestly
        assert "cogniflow.writeback.dead_letter" in events # distinct event, not "fail"


def test_drain_waits_for_successful_retry() -> None:
    # D2: drain() must not return until the *successful retry* completes, not merely
    # the first attempt's task_done.
    async def run() -> None:
        backend = _FakeBackend(fail_times=1) # fails once, succeeds on retry

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory, max_retries=3, retry_backoff_seconds=0.05)
        try:
            queue.enqueue(_obs(1))
            await queue.drain()
            # if drain returned after attempt 1, this would be None / count 1
            assert queue.last_ingested_at("g") is not None
            assert backend.write_count == 2
            assert len(backend.episodes) == 1
        finally:
            await queue.aclose()

    asyncio.run(run())
