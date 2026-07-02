"""Q-DUR (durable queue survives restart) and T2 (replay over archived history).
CI-safe: stdlib + fakes, no infra.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from cogniflow.core.archive import (
    InMemoryArchive,
    bitemporal_query_archived,
)
from cogniflow.core.audit import bitemporal_query
from cogniflow.core.types import (
    Belief,
    FalsificationVerdict,
    RetrievalResult,
    WriteReceipt,
)
from cogniflow.writeback import JsonFileJournal, Observation, WriteBackQueue


def _w(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


# system-time line
T0, E = datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 6, 1, tzinfo=timezone.utc)
S_BEFORE = datetime(2026, 3, 1, tzinfo=timezone.utc)
S_AFTER = datetime(2026, 9, 1, tzinfo=timezone.utc)


class _Gated:
    def __init__(self, gate: asyncio.Event) -> None:
        self._gate = gate

    async def write(self, episode) -> WriteReceipt:
        await self._gate.wait() # never completes in q1 -> obs stays pending+journaled
        return WriteReceipt(episode_id=episode.id)

    async def read(self, query) -> RetrievalResult: # pragma: no cover
        return RetrievalResult(query=query, results=(), as_of=None)

    async def falsify(self, target, against=None) -> FalsificationVerdict: # pragma: no cover
        return FalsificationVerdict(target_id=str(target), superseded=False)


class _Working(_Gated):
    def __init__(self) -> None:
        super().__init__(asyncio.Event())
        self.stored: list[str] = []

    async def write(self, episode) -> WriteReceipt:
        self.stored.append(episode.id)
        return WriteReceipt(episode_id=episode.id)


def test_durable_journal_survives_restart(tmp_path) -> None:
    journal_path = str(tmp_path / "queue.jsonl")

    async def run() -> None:
        # q1: enqueue, worker blocks on the gate (unprocessed), then "crash"
        gate = asyncio.Event()
        q1 = WriteBackQueue(
            lambda _g: _to_async(_Gated(gate)), journal=JsonFileJournal(journal_path)
        )
        q1.enqueue(Observation(id="o1", group_id="g", statement="x"))
        await asyncio.sleep(0) # let the worker pick it up and block
        assert len(JsonFileJournal(journal_path).load()) == 1 # durable before ack
        await q1.aclose() # simulate restart (pending never processed)

        # q2: fresh process, same journal -> recover and drain
        working = _Working()
        q2 = WriteBackQueue(lambda _g: _to_async(working), journal=JsonFileJournal(journal_path))
        assert q2.recover() == 1
        await q2.drain()
        assert working.stored == ["o1"]
        assert JsonFileJournal(journal_path).load() == [] # acked -> cleared
        await q2.aclose()

    asyncio.run(run())


async def _to_async(backend):
    return backend


def _boston() -> Belief:
    return Belief(
        id="boston", statement="HQ Boston", created_at=T0, valid_at=_w(2019),
        invalid_at=_w(2022), expired_at=E, metadata={"group_id": "g"},
    )


def _denver() -> Belief:
    return Belief(
        id="denver", statement="HQ Denver", created_at=E, valid_at=_w(2022),
        metadata={"group_id": "g"},
    )


def test_replay_over_archived_history_is_correct() -> None:
    archive = InMemoryArchive()
    archive.archive([_boston()]) # Boston moved to cold storage
    hot = [_denver()]

    # without the archive, a past query loses history (the failure archiving must avoid)
    assert [b.id for b in bitemporal_query(hot, S_AFTER, _w(2020))] == []

    # archive-aware replay recovers it - un-knowing still holds over cold data
    recovered = bitemporal_query_archived(hot, archive, S_AFTER, _w(2020), "g")
    assert [b.id for b in recovered] == ["boston"]

    before = bitemporal_query_archived(hot, archive, S_BEFORE, _w(2023), "g")
    assert any(b.id == "boston" and b.invalid_at is None for b in before)
