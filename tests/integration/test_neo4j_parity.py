"""T1 - multi-backend parity: Neo4j passes the SAME behavioral + replay assertions as
FalkorDB, with no weakened check and no core special-casing (only config selects the
driver). If a check had to be softened to make Neo4j pass, the contract leaked.

Skipped without a reachable Neo4j and an LLM key.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("graphiti_core")

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
from cogniflow.core.types import Episode, RetrievalQuery  # noqa: E402

NEO4J_URI = os.getenv("COGNIFLOW_NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("COGNIFLOW_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("COGNIFLOW_NEO4J_PASSWORD", "cogniflowtest")


def _neo4j_up() -> bool:
    try:
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        driver.close()
        return True
    except Exception:
        return False


requires_neo4j = pytest.mark.skipif(
    not (_neo4j_up() and os.getenv("COGNIFLOW_LLM_API_KEY")),
    reason="requires a reachable Neo4j and COGNIFLOW_LLM_API_KEY",
)


def _w(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _triple(ep_id, tgt, fact, year):
    return Episode(
        id=ep_id, content=fact, reference_time=_w(year), source="text",
        metadata={"triple": {"source": "Acme Corp", "predicate": "HEADQUARTERED_IN",
                             "target": tgt, "fact": fact}},
    )


def _neo4j_backend(group: str) -> GraphitiFalkorDBBackend:
    cfg = GraphitiFalkorDBConfig.from_env(group_id=group)
    cfg.backend_driver = "neo4j"
    cfg.neo4j_uri, cfg.neo4j_user, cfg.neo4j_password = NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
    return GraphitiFalkorDBBackend(cfg)


@pytest.mark.integration
@requires_neo4j
def test_neo4j_parity_heartbeat_stamps_replay_provenance() -> None:
    async def run() -> None:
        group = "it_neo4j_parity"
        backend = _neo4j_backend(group)
        await backend._driver.execute_query(
            "MATCH (n) WHERE n.group_id = $g DETACH DELETE n", g=group
        )
        await backend.setup()
        try:
            await backend.write(_triple("e1", "Boston", "Acme Corp is in Boston", 2019))
            receipt = await backend.write(_triple("e2", "Denver", "Acme Corp is in Denver", 2022))

            # heartbeat (same assertion as FalkorDB)
            q = "Where is Acme Corp headquartered?"
            r1 = await backend.read(RetrievalQuery(text=q, as_of=_w(2020), top_k=5))
            r2 = await backend.read(RetrievalQuery(text=q, as_of=_w(2023), top_k=5))
            assert [s.belief.statement for s in r1.results] == ["Acme Corp is in Boston"]
            assert [s.belief.statement for s in r2.results] == ["Acme Corp is in Denver"]

            # both-stamps invariant
            assert receipt.invalidated_belief_ids
            old = await EntityEdge.get_by_uuid(backend._driver, receipt.invalidated_belief_ids[0])
            assert old.invalid_at is not None and old.expired_at is not None

            # replay un-knowing invariant (the centerpiece) on Neo4j
            at_2020 = await backend.event_time_query(_w(2020))
            boston = next(b for b in at_2020 if "Boston" in b.statement)
            before = boston.expired_at - timedelta(seconds=1)
            live = next(
                b for b in await backend.system_time_replay(before) if "Boston" in b.statement
            )
            assert live.invalid_at is None # post-S invalidation not leaked backward

            # provenance with stored superseded_by (SUP)
            trace = await backend.provenance_trace(boston.id)
            assert trace.asserted_by == ("e1",)
            assert trace.superseded_by_episode == "e2"
        finally:
            await backend.close()

    asyncio.run(run())
