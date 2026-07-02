"""module integration: OKF v1->v2 ingestion supersedes the old concept (both-stamps),
and the straight temporal-RAG loop replays as-of any date. Live FalkorDB + LLM; skipped
without them.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
from datetime import datetime, timezone

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")
pytest.importorskip("yaml")

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
from cogniflow.bridges.llamaindex import make_llm  # noqa: E402
from cogniflow.okf import ingest_bundle  # noqa: E402
from cogniflow.pipelines import temporal_rag_answer  # noqa: E402

BUNDLE = pathlib.Path(__file__).resolve().parents[2] / "demo" / "okf_demo_bundle"
QUESTION = "How is Weekly Active Users currently defined? State the trailing-window length."


def _falkordb_up() -> bool:
    try:
        from falkordb import FalkorDB

        FalkorDB(host="localhost", port=6379).select_graph("__ping__").query("RETURN 1")
        return True
    except Exception:
        return False


requires_stack = pytest.mark.skipif(
    not (_falkordb_up() and os.getenv("COGNIFLOW_LLM_API_KEY")),
    reason="requires a running FalkorDB and COGNIFLOW_LLM_API_KEY",
)


@pytest.mark.integration
@requires_stack
def test_okf_cross_version_supersession_and_replay() -> None:
    async def run() -> None:
        from falkordb import FalkorDB

        group = "it_okf_slice_a"
        try:
            FalkorDB(host="localhost", port=6379).select_graph(group).delete()
        except Exception:
            pass
        backend = GraphitiFalkorDBBackend(GraphitiFalkorDBConfig.from_env(group_id=group))
        await backend.setup()
        llm = make_llm(backend.config)
        try:
            await ingest_bundle(backend, BUNDLE / "v1") # March: 7-day
            receipts_v2 = await ingest_bundle(backend, BUNDLE / "v2") # June: 28-day

            # acceptance #3: the superseded concept carries BOTH stamps, via OKF ingestion
            invalidated = [i for r in receipts_v2 for i in r.invalidated_belief_ids]
            assert invalidated, "v2 ingestion did not supersede the v1 concept"
            old = await EntityEdge.get_by_uuid(backend._driver, invalidated[0])
            assert old.invalid_at is not None and old.expired_at is not None

            async def gen(prompt: str) -> str:
                return str(await llm.acomplete(prompt))

            # acceptance #5: as-of replay through the straight loop
            now = await temporal_rag_answer(backend, QUESTION, gen)
            march = await temporal_rag_answer(
                backend, QUESTION, gen, as_of=datetime(2026, 3, 15, tzinfo=timezone.utc)
            )
            assert "28" in now.answer, now
            assert "7" in march.answer and "28" not in march.answer, march
        finally:
            await backend.close()

    asyncio.run(run())
