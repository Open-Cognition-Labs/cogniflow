"""module integration: document (PDF) front door -> cross-version supersession +
as-of replay, through the engine's prose extraction. Live FalkorDB + LLM; skipped without.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
from datetime import datetime, timezone

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")
pytest.importorskip("pypdf")

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
from cogniflow.documents import ingest_document  # noqa: E402
from cogniflow.pipelines import temporal_rag_answer  # noqa: E402

CORPUS = pathlib.Path(__file__).resolve().parents[2] / "demo" / "doc_demo_corpus"
Q = "Where is Acme Corp headquartered?"


def _falkordb_up() -> bool:
    try:
        from falkordb import FalkorDB

        FalkorDB(host="localhost", port=6379).select_graph("__ping__").query("RETURN 1")
        return True
    except Exception:
        return False


requires_stack = pytest.mark.skipif(
    not (_falkordb_up() and os.getenv("COGNIFLOW_LLM_API_KEY") and CORPUS.exists()),
    reason="requires FalkorDB, COGNIFLOW_LLM_API_KEY, and the demo PDF corpus",
)


@pytest.mark.integration
@requires_stack
def test_document_front_door_supersession_and_replay() -> None:
    async def run() -> None:
        from falkordb import FalkorDB

        group = "it_doc_slice_a2"
        try:
            FalkorDB(host="localhost", port=6379).select_graph(group).delete()
        except Exception:
            pass
        backend = GraphitiFalkorDBBackend(GraphitiFalkorDBConfig.from_env(group_id=group))
        await backend.setup()
        llm = make_llm(backend.config)
        try:
            await ingest_document(
                backend, CORPUS / "acme_report_v1.pdf",
                reference_time=datetime(2019, 1, 1, tzinfo=timezone.utc),
            )
            r2 = await ingest_document(
                backend, CORPUS / "acme_report_v2.pdf",
                reference_time=datetime(2022, 1, 1, tzinfo=timezone.utc),
            )
            invalidated = [i for r in r2 for i in r.invalidated_belief_ids]
            assert invalidated, "v2 document did not supersede the v1 fact"
            old = await EntityEdge.get_by_uuid(backend._driver, invalidated[0])
            assert old.invalid_at is not None and old.expired_at is not None # both stamps

            async def gen(prompt: str) -> str:
                return str(await llm.acomplete(prompt))

            now = await temporal_rag_answer(
                backend, Q, gen, as_of=datetime(2023, 1, 1, tzinfo=timezone.utc)
            )
            past = await temporal_rag_answer(
                backend, Q, gen, as_of=datetime(2020, 1, 1, tzinfo=timezone.utc)
            )
            assert "Denver" in now.answer, now
            assert "Boston" in past.answer, past
        finally:
            await backend.close()

    asyncio.run(run())
