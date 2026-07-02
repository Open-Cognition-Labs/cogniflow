"""Context-serving API - CI-safe. Contract shape, context-not-answer,
valid_at_source normalization, and the as-of axis at the function boundary. No infra.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from cogniflow.context import (
    ContextResponse,
    ServedFact,
    _normalize_source,
    serve_context,
)
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
    """Returns the Boston or Denver fact depending on the query's as_of, with an A.2-style
    derived label and provenance, so we can prove the label survives serving."""

    async def read(self, query: RetrievalQuery) -> RetrievalResult:
        if query.as_of is not None and query.as_of < _dt(2022):
            belief = Belief(
                id="b1",
                statement="Acme Corp is headquartered in Boston",
                created_at=_dt(2019),
                valid_at=_dt(2019),
                provenance=("acme_report_v1#chunk0",),
                metadata={"valid_at_source": "document:mtime"},
            )
        else:
            belief = Belief(
                id="b2",
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


def test_normalize_source_mapping() -> None:
    assert _normalize_source("provided") == "authoritative"
    assert _normalize_source("document:mtime") == "derived"
    assert _normalize_source("okf:timestamp") == "derived"
    assert _normalize_source("none") == "none"
    assert _normalize_source(None) == "none"
    assert _normalize_source("anything-else") == "derived" # conservative default


def test_serves_context_not_an_answer() -> None:
    res = serve_context_sync()
    assert isinstance(res, ContextResponse)
    assert not hasattr(res, "answer") # we serve context, not a generated answer
    assert res.facts and isinstance(res.facts[0], ServedFact)
    d = res.to_dict()
    assert set(d) == {"query", "as_of", "facts", "notes"}
    assert "answer" not in d
    assert "extraction" in " ".join(d["notes"]).lower() # T5: floor surfaced in the response


def test_honesty_labels_and_provenance_survive() -> None:
    fact = serve_context_sync().facts[0]
    assert fact.valid_at_source == "derived" # T3: derived stays derived
    assert fact.valid_at_source_raw == "document:mtime" # raw label not hidden
    assert fact.provenance == ("acme_report_v2#chunk0",) # provenance intact
    assert fact.valid_at == _dt(2022)


def test_as_of_axis_changes_context() -> None:
    now = asyncio.run(serve_context(_FakeSubstrate(), "where is Acme", as_of=_dt(2023)))
    past = asyncio.run(serve_context(_FakeSubstrate(), "where is Acme", as_of=_dt(2020)))
    assert "Denver" in now.facts[0].statement
    assert "Boston" in past.facts[0].statement # same query, different as_of -> different context
    assert now.as_of == _dt(2023) and past.as_of == _dt(2020)


def test_response_is_json_serializable() -> None:
    json.dumps(serve_context_sync().to_dict()) # must not raise


def serve_context_sync() -> ContextResponse:
    return asyncio.run(serve_context(_FakeSubstrate(), "where is Acme", as_of=_dt(2023)))
