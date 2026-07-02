"""milestone integration: the audit/replay layer against live FalkorDB.

Proves on real data: the un-knowing invariant (a fact's post-S invalidation is not
leaked backward), provenance trace with the reconstructed back-link, and that replay
bypasses graphiti.search entirely (direct temporal query). Skipped without infra.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.core.types import Episode  # noqa: E402

HOST = os.getenv("COGNIFLOW_FALKORDB_HOST", "localhost")
PORT = int(os.getenv("COGNIFLOW_FALKORDB_PORT", "6379"))


def _falkordb_up() -> bool:
    try:
        from falkordb import FalkorDB

        FalkorDB(host=HOST, port=PORT).select_graph("__ping__").query("RETURN 1")
        return True
    except Exception:
        return False


requires_stack = pytest.mark.skipif(
    not (_falkordb_up() and os.getenv("COGNIFLOW_LLM_API_KEY")),
    reason="requires a running FalkorDB and COGNIFLOW_LLM_API_KEY",
)


def _w(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _triple(ep_id, tgt, fact, year):
    return Episode(
        id=ep_id,
        content=fact,
        reference_time=_w(year),
        source="text",
        metadata={"triple": {"source": "Acme Corp", "predicate": "HEADQUARTERED_IN",
                             "target": tgt, "fact": fact}},
    )


def _fresh_backend(group: str) -> GraphitiFalkorDBBackend:
    try:
        from falkordb import FalkorDB

        FalkorDB(host=HOST, port=PORT).select_graph(group).delete()
    except Exception:
        pass
    return GraphitiFalkorDBBackend(GraphitiFalkorDBConfig.from_env(group_id=group))


@pytest.mark.integration
@requires_stack
def test_replay_unknowing_and_provenance_and_bypasses_search() -> None:
    async def run() -> None:
        backend = _fresh_backend("it_replay")
        await backend.setup()
        try:
            await backend.write(_triple("e1", "Boston", "Acme Corp is in Boston", 2019))
            await backend.write(_triple("e2", "Denver", "Acme Corp is in Denver", 2022))

            # locate Boston and the moment E the system learned it ended
            at_2020 = await backend.event_time_query(_w(2020))
            boston = next(b for b in at_2020 if "Boston" in b.statement)
            assert boston.expired_at is not None
            E = boston.expired_at
            before, after = E - timedelta(seconds=1), E + timedelta(seconds=1)

            # un-knowing on real data: at S<E Boston is believed live with invalid_at un-known
            live_before = await backend.system_time_replay(before)
            boston_before = next(b for b in live_before if "Boston" in b.statement)
            assert boston_before.invalid_at is None, "post-S invalidation leaked backward"

            # at S>=E Boston is no longer the live belief; Denver is
            live_after = {b.statement.split()[-1] for b in await backend.system_time_replay(after)}
            assert "Denver" in live_after and "Boston" not in live_after

            # bitemporal: as known after E, world-2020 still returns Boston (history kept)
            past = await backend.bitemporal_query(after, _w(2020))
            assert any("Boston" in b.statement for b in past)

            # provenance: asserting episode + reconstructed superseding episode
            trace = await backend.provenance_trace(boston.id)
            assert trace.asserted_by == ("e1",)
            assert trace.superseded_by_episode == "e2"

            # replay must NOT route through graphiti.search (direct temporal query)
            async def _boom(*a, **k):
                raise AssertionError("replay must not call graphiti.search")

            backend._graphiti.search = _boom # type: ignore[assignment]
            assert await backend.bitemporal_query(after, _w(2023)) is not None
            assert await backend.system_time_replay(before) is not None
        finally:
            await backend.close()

    asyncio.run(run())
