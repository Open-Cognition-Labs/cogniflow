"""Serving surfaces (A.3 T4) - CI-safe. HTTP via FastAPI TestClient (no network) and the
MCP server build/tool registration. Skipped if the optional extras are absent.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from cogniflow.core.types import (
    Belief,
    FalsificationVerdict,
    RetrievalQuery,
    RetrievalResult,
    ScoredBelief,
)


def _dt(y: int) -> datetime:
    return datetime(y, 1, 1, tzinfo=timezone.utc)


class _FakeSubstrate:
    async def read(self, query: RetrievalQuery) -> RetrievalResult:
        belief = Belief(
            id="b1",
            statement="Acme Corp is headquartered in Denver",
            created_at=_dt(2022),
            valid_at=_dt(2022),
            provenance=("acme_report_v2#chunk0",),
            metadata={"valid_at_source": "document:mtime"},
        )
        return RetrievalResult(
            query=query, results=(ScoredBelief(belief=belief, score=0.9),), as_of=query.as_of
        )

    async def write(self, episode): # pragma: no cover
        raise NotImplementedError

    async def falsify(self, target, against=None) -> FalsificationVerdict: # pragma: no cover
        return FalsificationVerdict(target_id=str(target), superseded=False)


def test_http_context_endpoint_returns_context_not_answer() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from cogniflow.serving import create_app

    client = TestClient(create_app(_FakeSubstrate()))
    assert client.get("/healthz").json()["status"] == "ok"

    r = client.post(
        "/context", json={"query": "where is Acme", "as_of": "2023-01-01T00:00:00+00:00"}
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"query", "as_of", "facts", "notes"}
    assert "answer" not in body # context, not a generated answer
    fact = body["facts"][0]
    assert fact["statement"].endswith("Denver")
    assert fact["valid_at_source"] == "derived" # honesty label survives to the HTTP edge
    assert fact["provenance"] == ["acme_report_v2#chunk0"]
    assert body["as_of"] == "2023-01-01T00:00:00+00:00" # as-of echoed at the boundary


def test_http_endpoint_is_read_only() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from cogniflow.serving import create_app

    client = TestClient(create_app(_FakeSubstrate()))
    # no write verb is exposed on the context resource
    assert client.put("/context", json={}).status_code == 405
    assert client.delete("/context").status_code == 405


def test_mcp_server_builds_with_get_context_tool() -> None:
    pytest.importorskip("mcp")
    from cogniflow.serving import build_mcp_server

    server = build_mcp_server(_FakeSubstrate())
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert "get_context" in names # the read-only context tool is exposed over MCP
