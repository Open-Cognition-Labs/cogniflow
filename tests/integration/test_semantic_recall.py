"""The embedder plug's payoff, made a permanent proof: with BGE-M3 a PARAPHRASE that shares
almost no keywords with the stored fact still retrieves it ranked #1 - impossible under the
BM25-lexical hash embedder. Needs FalkorDB + COGNIFLOW_EMBEDDER_API_KEY + the OKF bundle.
"""

from __future__ import annotations

import asyncio
import os
import pathlib

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")
pytest.importorskip("yaml")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.context import serve_context  # noqa: E402
from cogniflow.okf import ingest_bundle  # noqa: E402

BUNDLE = pathlib.Path(__file__).resolve().parents[2] / "demo" / "okf_demo_bundle"


def _falkordb_up() -> bool:
    try:
        from falkordb import FalkorDB

        FalkorDB(host="localhost", port=6379).select_graph("__ping__").query("RETURN 1")
        return True
    except Exception:
        return False


requires_embedder = pytest.mark.skipif(
    not (
        _falkordb_up()
        and os.getenv("COGNIFLOW_EMBEDDER_API_KEY")
        and os.getenv("COGNIFLOW_LLM_API_KEY")
        and BUNDLE.exists()
    ),
    reason="requires FalkorDB, COGNIFLOW_EMBEDDER_API_KEY, COGNIFLOW_LLM_API_KEY, OKF bundle",
)


@pytest.mark.integration
@requires_embedder
def test_bge_m3_paraphrase_retrieves_the_right_fact() -> None:
    async def run() -> None:
        from falkordb import FalkorDB

        group = "it_semantic_recall"
        try:
            FalkorDB(host="localhost", port=6379).select_graph(group).delete()
        except Exception:
            pass
        cfg = GraphitiFalkorDBConfig.from_env(group_id=group)
        cfg.embedder = "bge-m3"  # real semantic embedder
        backend = GraphitiFalkorDBBackend(cfg)
        await backend.setup()
        try:
            await ingest_bundle(backend, BUNDLE / "v1")
            await ingest_bundle(backend, BUNDLE / "v2")  # current = 28-day
            # a paraphrase that shares essentially no keywords with the stored statement
            res = await serve_context(
                backend, "What is the rolling window for our core engagement metric?", top_k=3
            )
            assert res.facts, "semantic retrieval returned nothing"
            assert "28-day" in res.facts[0].statement, [f.statement for f in res.facts]
        finally:
            await backend.close()

    asyncio.run(run())
