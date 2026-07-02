"""milestone integration: the real Graphiti+FalkorDB AsyncSubstrate, proven against
a live FalkorDB and LLM. Skipped automatically when either is absent (e.g. CI).

THE heartbeat: the same question at as_of=T1 vs as_of=T2 returns different answers
because a fact was superseded between them.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from graphiti_core.edges import EntityEdge  # noqa: E402

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.conformance.suite import run_conformance_async  # noqa: E402
from cogniflow.core.types import Episode, RetrievalQuery  # noqa: E402

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


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _fresh_backend(group_id: str) -> GraphitiFalkorDBBackend:
    try:
        from falkordb import FalkorDB

        FalkorDB(host=HOST, port=PORT).select_graph(group_id).delete()
    except Exception:
        pass
    return GraphitiFalkorDBBackend(GraphitiFalkorDBConfig.from_env(group_id=group_id))


def _triple_episode(
    ep_id: str, src: str, pred: str, tgt: str, fact: str, year: int
) -> Episode:
    return Episode(
        id=ep_id,
        content=fact,
        reference_time=_dt(year),
        source="text",
        metadata={"triple": {"source": src, "predicate": pred, "target": tgt, "fact": fact}},
    )


@pytest.mark.integration
@requires_stack
def test_real_backend_passes_async_conformance() -> None:
    """The canonical backend ships through the gate that actually awaited it."""

    async def run() -> None:
        backend = _fresh_backend("it_conf")
        await backend.setup()
        try:
            results = await run_conformance_async(backend)
            assert all(r.passed for r in results), [r for r in results if not r.passed]
        finally:
            await backend.close()

    asyncio.run(run())


@pytest.mark.integration
@requires_stack
def test_heartbeat_and_invariants() -> None:
    """THE demo plus the behavioral invariants, against real FalkorDB + LLM."""

    async def run() -> None:
        backend = _fresh_backend("it_hb")
        await backend.setup()
        try:
            await backend.write(
                _triple_episode(
                    "ep1", "Acme Corp", "HEADQUARTERED_IN", "Boston",
                    "Acme Corp is headquartered in Boston", 2019,
                )
            )
            receipt = await backend.write(
                _triple_episode(
                    "ep2", "Acme Corp", "HEADQUARTERED_IN", "Denver",
                    "Acme Corp is headquartered in Denver", 2022,
                )
            )

            # invariant: both-stamps-on-contradiction (system-time expired_at set)
            assert receipt.invalidated_belief_ids, "superseded edge was not stamped expired_at"
            old_id = receipt.invalidated_belief_ids[0]
            verdict = await backend.falsify(old_id)
            assert verdict.superseded and verdict.invalid_at is not None, (
                "event-time invalid_at not set on superseded belief"
            )

            question = "Where is Acme Corp headquartered?"
            r1 = await backend.read(RetrievalQuery(text=question, as_of=_dt(2020), top_k=5))
            r2 = await backend.read(RetrievalQuery(text=question, as_of=_dt(2023), top_k=5))
            t1 = [s.belief.statement for s in r1.results]
            t2 = [s.belief.statement for s in r2.results]

            # THE heartbeat: same question, different answer across time
            assert t1 == ["Acme Corp is headquartered in Boston"], t1
            assert t2 == ["Acme Corp is headquartered in Denver"], t2
            # invariant: as-of excludes invalidated facts
            assert "Acme Corp is headquartered in Boston" not in t2
        finally:
            await backend.close()

    asyncio.run(run())


@pytest.mark.integration
@requires_stack
def test_idempotent_under_retry() -> None:
    """Writing the same fact twice must not produce a divergent duplicate."""

    async def run() -> None:
        backend = _fresh_backend("it_idem")
        await backend.setup()
        try:
            episode = _triple_episode(
                "epA", "Acme Corp", "HEADQUARTERED_IN", "Boston",
                "Acme Corp is headquartered in Boston", 2019,
            )
            await backend.write(episode)
            await backend.write(episode) # retry of the same fact
            results = (
                await backend.read(
                    RetrievalQuery(
                        text="Where is Acme Corp headquartered?", as_of=_dt(2020), top_k=10
                    )
                )
            ).results
            boston = [s for s in results if "Boston" in s.belief.statement]
            assert len(boston) == 1, f"expected 1 Boston belief after retry, got {len(boston)}"
        finally:
            await backend.close()

    asyncio.run(run())


@pytest.mark.integration
@requires_stack
def test_both_stamps_on_superseded_edge() -> None:
    """G2: a superseded edge carries BOTH invalid_at (event-time) and expired_at
    (system-time), asserted directly on the stored edge."""

    async def run() -> None:
        backend = _fresh_backend("it_stamps")
        await backend.setup()
        try:
            await backend.write(
                _triple_episode(
                    "ep1", "Acme Corp", "HEADQUARTERED_IN", "Boston",
                    "Acme Corp is headquartered in Boston", 2019,
                )
            )
            receipt = await backend.write(
                _triple_episode(
                    "ep2", "Acme Corp", "HEADQUARTERED_IN", "Denver",
                    "Acme Corp is headquartered in Denver", 2022,
                )
            )
            assert receipt.invalidated_belief_ids, "no edge was superseded"
            old = await EntityEdge.get_by_uuid(backend._driver, receipt.invalidated_belief_ids[0])
            assert old.invalid_at is not None, "event-time invalid_at not stamped"
            assert old.expired_at is not None, "system-time expired_at not stamped"
        finally:
            await backend.close()

    asyncio.run(run())


@pytest.mark.integration
@requires_stack
def test_triplet_provenance_present() -> None:
    """G4: a triplet-injected fact carries its originating episode id as provenance."""

    async def run() -> None:
        backend = _fresh_backend("it_prov")
        await backend.setup()
        try:
            await backend.write(
                _triple_episode(
                    "ep-prov", "Acme Corp", "HEADQUARTERED_IN", "Boston",
                    "Acme Corp is headquartered in Boston", 2019,
                )
            )
            result = await backend.read(
                RetrievalQuery(
                    text="Where is Acme Corp headquartered?", as_of=_dt(2020), top_k=5
                )
            )
            assert result.results, "no belief returned"
            assert "ep-prov" in result.results[0].belief.provenance, (
                result.results[0].belief.provenance
            )
        finally:
            await backend.close()

    asyncio.run(run())
