"""module integration: the context API over the real store.

T3 (load-bearing): a fact ingested with a DERIVED valid_at is served by the context API
still labeled derived, provenance intact - the honesty label survives ingestion->output.
T2: the as-of axis changes the served context at the API boundary.
Live FalkorDB + LLM; skipped without them.
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

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.context import serve_context  # noqa: E402
from cogniflow.documents import ingest_document  # noqa: E402

CORPUS = pathlib.Path(__file__).resolve().parents[2] / "demo" / "doc_demo_corpus"


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


def _backend(group: str) -> GraphitiFalkorDBBackend:
    from falkordb import FalkorDB

    try:
        FalkorDB(host="localhost", port=6379).select_graph(group).delete()
    except Exception:
        pass
    return GraphitiFalkorDBBackend(GraphitiFalkorDBConfig.from_env(group_id=group))


@pytest.mark.integration
@requires_stack
def test_honesty_label_survives_to_the_context_api() -> None:
    async def run() -> None:
        backend = _backend("it_ctx_t3")
        await backend.setup()
        try:
            # ingest WITHOUT a reference_time -> valid_at derived from the file mtime
            await ingest_document(backend, CORPUS / "acme_report_v2.pdf")
            res = await serve_context(backend, "Where is Acme Corp headquartered?")
            assert res.facts, "no context served"
            denver = [f for f in res.facts if "Denver" in f.statement]
            assert denver, res.facts
            fact = denver[0]
            assert fact.valid_at_source == "derived" # T3: derived stays derived end to end
            assert fact.valid_at_source_raw == "document:mtime" # raw label round-tripped
            # provenance intact: the episode(s) that asserted this fact (UUIDs; resolving
            # them to human-readable document ids is the module audit surface)
            assert fact.provenance and all(p for p in fact.provenance)
        finally:
            await backend.close()

    asyncio.run(run())


@pytest.mark.integration
@requires_stack
def test_as_of_axis_at_the_api_boundary() -> None:
    async def run() -> None:
        utc = timezone.utc
        backend = _backend("it_ctx_t2")
        await backend.setup()
        try:
            v1, v2 = CORPUS / "acme_report_v1.pdf", CORPUS / "acme_report_v2.pdf"
            await ingest_document(backend, v1, reference_time=datetime(2019, 1, 1, tzinfo=utc))
            await ingest_document(backend, v2, reference_time=datetime(2022, 1, 1, tzinfo=utc))
            q = "Where is Acme Corp headquartered?"
            now = await serve_context(backend, q, as_of=datetime(2023, 1, 1, tzinfo=utc))
            past = await serve_context(backend, q, as_of=datetime(2020, 1, 1, tzinfo=utc))
            assert any("Denver" in f.statement for f in now.facts), now.facts
            assert any("Boston" in f.statement for f in past.facts), past.facts
            assert now.as_of == datetime(2023, 1, 1, tzinfo=utc)
        finally:
            await backend.close()

    asyncio.run(run())
