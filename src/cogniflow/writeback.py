"""The write-back queue: the production heart of the retrieve -> falsify -> persist
-> reshape loop.

The seam (``record_observation``) is trivial; this queue is where the difficulty
lives. Properties, each load-bearing:

- Sequential per ``group_id``: Graphiti ingestion depends on prior-episode context,
  so one serial worker per group.
- Concurrent across ``group_id``s: independent workers; one busy tenant never
  starves another.
- Non-blocking enqueue: ``enqueue`` returns an ack immediately; the agent turn never
  awaits ingestion.
- Bounded backpressure: a per-group bound; when full it rejects-with-signal (never
  drop-oldest, never block) and emits a saturation event.
- Idempotent under retry: each observation carries a stable id used as the episode
  id, so a retry is collapsed by the backend's dedup (no duplicate fact, no spurious
  contradiction). This is best-effort-via-dedup, asserted as an invariant.
- Clean drain: ``drain()`` waits until every queue is empty and idle.
- Freshness surface (T3): ``last_ingested_at(group_id)`` exposes the eventual-
  consistency bound (belief lag), made honest rather than hidden.
- Observability on every transition (P3): enqueue / start / success / retry / fail /
  reject / drain.

Depends only on the ``AsyncSubstrate`` contract and stdlib, so it is unit-testable
with a fake substrate and has no third-party imports.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .core.contracts import AsyncSubstrate
from .core.types import Episode, utc_now
from .observability import log_queue_event

# An async factory that returns a ready (set-up) backend for a group_id.
BackendFactory = Callable[[str], Awaitable[AsyncSubstrate]]


@dataclass(frozen=True, slots=True)
class Observation:
    """A fact the agent wants recorded. ``id`` is the idempotency key."""

    id: str
    group_id: str
    statement: str
    triple: dict[str, Any] | None = None
    reference_time: datetime | None = None


def _obs_to_dict(obs: Observation) -> dict[str, Any]:
    return {
        "id": obs.id,
        "group_id": obs.group_id,
        "statement": obs.statement,
        "triple": obs.triple,
        "reference_time": obs.reference_time.isoformat() if obs.reference_time else None,
    }


def _obs_from_dict(d: dict[str, Any]) -> Observation:
    rt = d.get("reference_time")
    return Observation(
        id=d["id"],
        group_id=d["group_id"],
        statement=d["statement"],
        triple=d.get("triple"),
        reference_time=datetime.fromisoformat(rt) if rt else None,
    )


@runtime_checkable
class QueueJournal(Protocol):
    """Durable record of pending observations (Q-DUR). With a journal, a "queued"
    observation survives a process restart: ``recover()`` re-enqueues what was never
    acknowledged. Without one (the default), the queue is in-process only."""

    def append(self, obs: Observation) -> None: ...

    def remove(self, observation_id: str) -> None: ...

    def load(self) -> list[Observation]: ...


class JsonFileJournal:
    """A simple durable journal: one JSON object per pending observation in a file.

    Removed on success or dead-letter. Not high-throughput, but it closes the
    vanish-on-restart trust gap; a production deployment can swap in a Redis-stream
    journal behind the same Protocol.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._entries: dict[str, dict[str, Any]] = {}
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    self._entries[obj["id"]] = obj

    def _flush(self) -> None:
        self._path.write_text(
            "\n".join(json.dumps(e) for e in self._entries.values()), encoding="utf-8"
        )

    def append(self, obs: Observation) -> None:
        self._entries[obs.id] = _obs_to_dict(obs)
        self._flush()

    def remove(self, observation_id: str) -> None:
        if observation_id in self._entries:
            del self._entries[observation_id]
            self._flush()

    def load(self) -> list[Observation]:
        return [_obs_from_dict(e) for e in self._entries.values()]


@dataclass(frozen=True, slots=True)
class EnqueueAck:
    """Returned immediately by ``enqueue`` - an acknowledgement, not a WriteReceipt."""

    observation_id: str
    status: str  # "queued" | "rejected"
    reason: str = ""


@dataclass(frozen=True, slots=True)
class FreshnessStatus:
    """Honest freshness for a group: last success plus how many writes were dropped.

    ``failed_count > 0`` means the group is silently degraded, not idle - a reader
    must never confuse the two. ``degraded`` is the one-glance signal.
    """

    last_ingested_at: datetime | None
    failed_count: int
    pending: int

    @property
    def degraded(self) -> bool:
        return self.failed_count > 0


@dataclass
class _GroupChannel:
    queue: asyncio.Queue[Observation]
    worker: asyncio.Task[None]
    backend: AsyncSubstrate | None = None
    last_ingested_at: datetime | None = None
    failed: list[str] = field(default_factory=list)


class WriteBackQueue:
    """Per-group serial, cross-group concurrent, bounded, idempotent, observable."""

    def __init__(
        self,
        backend_factory: BackendFactory,
        *,
        max_pending_per_group: int = 100,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.2,
        journal: QueueJournal | None = None,
    ) -> None:
        self._backend_factory = backend_factory
        self._max_pending = max_pending_per_group
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff_seconds
        self._journal = journal
        self._channels: dict[str, _GroupChannel] = {}
        self._closed = False

    def recover(self) -> int:
        """Re-enqueue observations a journal recorded but never acknowledged (Q-DUR).
        Call once at startup. Returns the number recovered. No-op without a journal."""
        if self._journal is None:
            return 0
        pending = self._journal.load()
        for obs in pending:
            self.enqueue(obs, _journal=False)  # already journaled
        return len(pending)

    # --- public API --------------------------------------------------------------

    def enqueue(self, observation: Observation, *, _journal: bool = True) -> EnqueueAck:
        """Non-blocking. Starts a per-group worker if needed, then ``put_nowait``.

        Returns "queued", or "rejected" with reason "saturated" when the per-group
        bound is hit (reject-with-signal; never drop-oldest, never block).
        """
        if self._closed:
            return EnqueueAck(observation.id, "rejected", "queue closed")
        channel = self._ensure_channel(observation.group_id)
        try:
            channel.queue.put_nowait(observation)
        except asyncio.QueueFull:
            log_queue_event(
                "reject",
                group_id=observation.group_id,
                observation_id=observation.id,
                reason="saturated",
                pending=channel.queue.qsize(),
            )
            return EnqueueAck(observation.id, "rejected", "saturated")
        if _journal and self._journal is not None:
            self._journal.append(observation)  # durable: survives restart until acked
        log_queue_event(
            "enqueue",
            group_id=observation.group_id,
            observation_id=observation.id,
            pending=channel.queue.qsize(),
        )
        return EnqueueAck(observation.id, "queued")

    async def drain(self) -> None:
        """Wait until every group's queue is empty and idle. Deterministic for tests."""
        await asyncio.gather(*(ch.queue.join() for ch in list(self._channels.values())))
        log_queue_event("drain", groups=len(self._channels))

    def last_ingested_at(self, group_id: str) -> datetime | None:
        """Freshness surface (T3): when this group last successfully ingested, or None."""
        channel = self._channels.get(group_id)
        return channel.last_ingested_at if channel else None

    def failed_count(self, group_id: str) -> int:
        """How many writes for this group exhausted retries and were dead-lettered."""
        channel = self._channels.get(group_id)
        return len(channel.failed) if channel else 0

    def freshness(self, group_id: str) -> FreshnessStatus:
        """Honest freshness (D1): last success + dead-letter count + pending, so a
        silently-degraded group is never mistaken for an idle one."""
        channel = self._channels.get(group_id)
        if channel is None:
            return FreshnessStatus(last_ingested_at=None, failed_count=0, pending=0)
        return FreshnessStatus(
            last_ingested_at=channel.last_ingested_at,
            failed_count=len(channel.failed),
            pending=channel.queue.qsize(),
        )

    def pending(self, group_id: str) -> int:
        channel = self._channels.get(group_id)
        return channel.queue.qsize() if channel else 0

    async def aclose(self) -> None:
        """Cancel workers and close backends. Idempotent."""
        self._closed = True
        for channel in list(self._channels.values()):
            channel.worker.cancel()
        for channel in list(self._channels.values()):
            try:
                await channel.worker
            except (asyncio.CancelledError, Exception):
                pass
            backend = channel.backend
            closer = getattr(backend, "close", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:
                    pass
        self._channels.clear()

    # --- internals ---------------------------------------------------------------

    def _ensure_channel(self, group_id: str) -> _GroupChannel:
        channel = self._channels.get(group_id)
        if channel is not None:
            return channel
        queue: asyncio.Queue[Observation] = asyncio.Queue(maxsize=self._max_pending)
        worker = asyncio.create_task(self._run_worker(group_id, queue))
        channel = _GroupChannel(queue=queue, worker=worker)
        self._channels[group_id] = channel
        return channel

    async def _run_worker(self, group_id: str, queue: asyncio.Queue[Observation]) -> None:
        while True:
            observation = await queue.get()
            try:
                await self._process(group_id, observation)
            finally:
                queue.task_done()

    async def _process(self, group_id: str, observation: Observation) -> None:
        channel = self._channels[group_id]
        if channel.backend is None:
            channel.backend = await self._backend_factory(group_id)
        backend = channel.backend

        metadata: dict[str, Any] = {"observation_id": observation.id}
        if observation.triple is not None:
            metadata["triple"] = observation.triple
        episode = Episode(
            id=observation.id,  # stable idempotency key -> dedup collapses retries
            content=observation.statement,
            reference_time=observation.reference_time or utc_now(),
            source="text",
            metadata=metadata,
        )

        for attempt in range(1, self._max_retries + 1):
            log_queue_event(
                "start", group_id=group_id, observation_id=observation.id, attempt=attempt
            )
            try:
                receipt = await backend.write(episode)
                channel.last_ingested_at = utc_now()
                if self._journal is not None:
                    self._journal.remove(observation.id)  # acknowledged -> durable record cleared
                log_queue_event(
                    "success",
                    group_id=group_id,
                    observation_id=observation.id,
                    created=len(receipt.created_belief_ids),
                    invalidated=len(receipt.invalidated_belief_ids),
                )
                return
            except Exception as exc:  # noqa: BLE001 - queue must not crash on any backend error
                if attempt < self._max_retries:
                    log_queue_event(
                        "retry",
                        group_id=group_id,
                        observation_id=observation.id,
                        attempt=attempt,
                        error=type(exc).__name__,
                    )
                    await asyncio.sleep(self._retry_backoff * attempt)
                    continue
                # Retry exhausted: dead-letter. Distinct event (D1), not a normal
                # failure, so monitoring can alert on silent data loss. Never a crash.
                channel.failed.append(observation.id)
                if self._journal is not None:
                    self._journal.remove(observation.id)  # dead-lettered; recorded in failed[]
                log_queue_event(
                    "dead_letter",
                    group_id=group_id,
                    observation_id=observation.id,
                    error=type(exc).__name__,
                    failed_total=len(channel.failed),
                )
                return

    def failed_ids(self, group_id: str) -> list[str]:
        channel = self._channels.get(group_id)
        return list(channel.failed) if channel else []
