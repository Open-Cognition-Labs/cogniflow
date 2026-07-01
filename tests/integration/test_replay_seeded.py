"""CI-gated un-knowing invariant on a LIVE FalkorDB, with NO LLM key.

The headline property of the whole system is the un-knowing invariant: replaying to a
system-time *before* a correction must NOT leak the later invalidation backward. The pure
version is covered in ``tests/test_audit_replay.py``; this test proves it end-to-end against a
real FalkorDB, so the invariant is *enforced on every PR*, not merely unit-tested.

It seeds two structured facts directly (backdated ``created_at``; no extraction LLM), then
asserts the invariant through the actual engine queries (``system_time_replay`` +
reconstruction). It needs only a running FalkorDB - no external model key - so it runs in CI as
a service container with no secrets.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)

HOST = os.getenv("COGNIFLOW_FALKORDB_HOST", "localhost")
PORT = int(os.getenv("COGNIFLOW_FALKORDB_PORT", "6379"))

_C2019 = "2019-01-01T00:00:00+00:00"  # learned + valid: the Boston filing
_C2022 = "2022-01-01T00:00:00+00:00"  # learned + valid: the Denver filing; Boston ends here


def _falkordb_up() -> bool:
    try:
        from falkordb import FalkorDB

        FalkorDB(host=HOST, port=PORT).select_graph("__ping__").query("RETURN 1")
        return True
    except Exception:
        return False


requires_falkordb = pytest.mark.skipif(not _falkordb_up(), reason="requires a running FalkorDB")


def _cfg(group: str) -> GraphitiFalkorDBConfig:
    cfg = GraphitiFalkorDBConfig.from_env(group_id=group)
    # Backend construction builds an OpenAI client eagerly; a placeholder is enough because this
    # test never calls the model (it seeds via Cypher and only runs temporal queries). No real
    # key is required - that is the whole point: the invariant is checkable without an LLM.
    cfg.llm_api_key = cfg.llm_api_key or "ci-not-used"
    cfg.llm_base_url = cfg.llm_base_url or "https://api.openai.com/v1"
    cfg.llm_model = cfg.llm_model or "gpt-4o-mini"
    cfg.embedder = "hash"  # key-free; audit queries do not touch embeddings
    return cfg


async def _seed(backend: GraphitiFalkorDBBackend) -> None:
    """Seed Boston (2019, superseded 2022 by Denver) and Denver (2022, live) directly."""
    gid = backend.group_id
    drv = backend._driver
    for uuid, name in (("s-acme", "Acme Corp"), ("s-bos", "Boston"), ("s-den", "Denver")):
        await drv.execute_query(
            "MERGE (x:Entity {uuid:$u}) SET x.name=$n, x.group_id=$g", u=uuid, n=name, g=gid
        )
    for uuid, name in (("s-ep-bos", "2019 report"), ("s-ep-den", "2022 release")):
        await drv.execute_query(
            "MERGE (x:Episodic {uuid:$u}) SET x.name=$n, x.group_id=$g", u=uuid, n=name, g=gid
        )
    await drv.execute_query(
        "MATCH (a:Entity {uuid:$s}), (b:Entity {uuid:$t}) "
        "MERGE (a)-[r:RELATES_TO {uuid:$id}]->(b) "
        "SET r.fact=$f, r.name='HEADQUARTERED_IN', r.group_id=$g, r.created_at=$c, r.valid_at=$c, "
        "r.invalid_at=$iv, r.expired_at=$iv, r.episodes=$eps, r.superseded_by=$sb, "
        "r.superseded_by_episode=$sbe, r.valid_at_source='provided'",
        s="s-acme", t="s-bos", id="s-boston", f="Acme Corp is headquartered in Boston", g=gid,
        c=_C2019, iv=_C2022, eps=["s-ep-bos"], sb="s-denver", sbe="s-ep-den",
    )
    await drv.execute_query(
        "MATCH (a:Entity {uuid:$s}), (b:Entity {uuid:$t}) "
        "MERGE (a)-[r:RELATES_TO {uuid:$id}]->(b) "
        "SET r.fact=$f, r.name='HEADQUARTERED_IN', r.group_id=$g, r.created_at=$c, r.valid_at=$c, "
        "r.episodes=$eps, r.valid_at_source='provided' "
        "REMOVE r.invalid_at, r.expired_at, r.superseded_by, r.superseded_by_episode",
        s="s-acme", t="s-den", id="s-denver", f="Acme Corp is headquartered in Denver", g=gid,
        c=_C2022, eps=["s-ep-den"],
    )


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _cities(beliefs) -> set[str]:
    return {b.statement.rstrip(".").split()[-1] for b in beliefs}


@pytest.mark.integration
@requires_falkordb
def test_unknowing_invariant_on_live_falkordb_without_llm() -> None:
    async def run() -> None:
        from falkordb import FalkorDB

        group = "it_replay_seeded"
        try:
            FalkorDB(host=HOST, port=PORT).select_graph(group).delete()
        except Exception:
            pass
        backend = GraphitiFalkorDBBackend(_cfg(group))
        await backend.setup()
        try:
            await _seed(backend)

            # THE INVARIANT: replay to before the 2022 correction -> Boston is live, and the
            # later invalidation is un-known (not leaked backward).
            before = await backend.system_time_replay(_dt(2021))
            assert _cities(before) == {"Boston"}, before
            boston = next(b for b in before if "Boston" in b.statement)
            assert boston.invalid_at is None, "post-S invalidation leaked backward"

            # replay after the correction -> Denver is the live belief, Boston no longer
            after = await backend.system_time_replay(_dt(2023))
            assert _cities(after) == {"Denver"}, after

            # event-time axis: true in 2020 = Boston; true now = Denver
            assert _cities(await backend.event_time_query(_dt(2020))) == {"Boston"}
            assert _cities(await backend.event_time_query(datetime.now(timezone.utc))) == {"Denver"}

            # bitemporal: as known in 2023, the world of 2020 still returns Boston (history kept)
            assert "Boston" in _cities(await backend.bitemporal_query(_dt(2023), _dt(2020)))

            # provenance back-link is the exact stamped one (not the reconstructed heuristic)
            trace = await backend.provenance_trace("s-boston")
            assert trace.superseded_by_belief == "s-denver"
            assert trace.superseded_by_episode == "s-ep-den"
        finally:
            await backend.close()

    asyncio.run(run())
