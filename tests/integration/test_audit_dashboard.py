"""module integration: the audit API over the real store, with DETERMINISTIC supersession
(OKF `fact` triples - no LLM extraction flakiness). Proves the event-time axis at the API
boundary and G1 provenance resolution (episode UUID -> concept name). Live FalkorDB; skipped
without it.
"""

from __future__ import annotations

import asyncio
import os
import pathlib

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")
pytest.importorskip("fastapi")
pytest.importorskip("yaml")
pytest.importorskip("httpx")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from httpx import ASGITransport, AsyncClient  # noqa: E402

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.documents import ingest_document  # noqa: E402
from cogniflow.okf import ingest_bundle  # noqa: E402
from cogniflow.serving import create_audit_app  # noqa: E402

_DEMO = pathlib.Path(__file__).resolve().parents[2] / "demo"
BUNDLE = _DEMO / "okf_demo_bundle"
CORPUS = _DEMO / "doc_demo_corpus"


def _falkordb_up() -> bool:
    try:
        from falkordb import FalkorDB

        FalkorDB(host="localhost", port=6379).select_graph("__ping__").query("RETURN 1")
        return True
    except Exception:
        return False


requires_stack = pytest.mark.skipif(
    not (_falkordb_up() and os.getenv("COGNIFLOW_LLM_API_KEY") and BUNDLE.exists()),
    reason="requires FalkorDB, COGNIFLOW_LLM_API_KEY, and the OKF demo bundle",
)


@pytest.mark.integration
@requires_stack
def test_audit_api_event_axis_and_provenance_resolution() -> None:
    async def run() -> None:
        from falkordb import FalkorDB

        group = "it_audit_dash"
        try:
            FalkorDB(host="localhost", port=6379).select_graph(group).delete()
        except Exception:
            pass
        backend = GraphitiFalkorDBBackend(GraphitiFalkorDBConfig.from_env(group_id=group))
        await backend.setup()
        try:
            await ingest_bundle(backend, BUNDLE / "v1") # March: 7-day
            await ingest_bundle(backend, BUNDLE / "v2") # June: 28-day (supersedes)
            app = create_audit_app(backend)
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://audit.test") as ac:
                # event-time axis: what WAS true in April (7-day) vs July (28-day)
                march = (await ac.get("/audit/event", params={"as_of": "2026-04-01"})).json()
                july = (await ac.get("/audit/event", params={"as_of": "2026-07-01"})).json()
                march_text = " ".join(b["statement"] for b in march["beliefs"])
                july_text = " ".join(b["statement"] for b in july["beliefs"])
                assert "7-day" in march_text and "28-day" not in march_text
                assert "28-day" in july_text

                # current = the live (June) definition
                current = (await ac.get("/audit/current")).json()["beliefs"]
                assert any("28-day" in b["statement"] for b in current)

                # provenance display is human-readable. For OKF triples the concept id is
                # stored directly as the episode reference, so the name needs no lookup.
                bid = current[0]["belief_id"]
                trace = (await ac.get(f"/audit/provenance/{bid}")).json()
                assert any(
                    a["display"] == "metrics/weekly_active_users" for a in trace["asserted_by"]
                ), trace
        finally:
            await backend.close()

    asyncio.run(run())


@pytest.mark.integration
@pytest.mark.skipif(
    not (_falkordb_up() and os.getenv("COGNIFLOW_LLM_API_KEY") and CORPUS.exists()),
    reason="requires FalkorDB, COGNIFLOW_LLM_API_KEY, and the demo PDF corpus",
)
def test_g1_provenance_uuid_resolves_to_document_name() -> None:
    # The document (add_episode) path stores a real episode UUID with a backing Episodic
    # node, so this is where UUID->name resolution actually fires (G1).
    async def run() -> None:
        from falkordb import FalkorDB

        group = "it_audit_g1"
        try:
            FalkorDB(host="localhost", port=6379).select_graph(group).delete()
        except Exception:
            pass
        backend = GraphitiFalkorDBBackend(GraphitiFalkorDBConfig.from_env(group_id=group))
        await backend.setup()
        try:
            await ingest_document(backend, CORPUS / "acme_report_v2.pdf")
            app = create_audit_app(backend)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://audit.test"
            ) as ac:
                current = (await ac.get("/audit/current")).json()["beliefs"]
                assert current, "no beliefs ingested"
                bid = current[0]["belief_id"]
                trace = (await ac.get(f"/audit/provenance/{bid}")).json()
                resolved = [a for a in trace["asserted_by"] if a["resolved"]]
                assert resolved, trace # a real UUID resolved from stored Episodic linkage
                assert any("acme_report_v2" in a["name"] for a in resolved), trace
        finally:
            await backend.close()

    asyncio.run(run())
