"""T4 pipeline order (validity before rank) and G4b canonical-ISO ordering (CI-safe)."""

from __future__ import annotations

from datetime import datetime, timezone

from cogniflow.core.policies import DefaultValidityPolicy, rank_valid
from cogniflow.core.types import Belief, RetrievalQuery, ScoredBelief


def _w(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


class _RankInvalidFirst:
    """A ranker that would put everything (incl. invalid facts) at the top - to prove
    validity filtering runs BEFORE ranking, so an invalid fact can't be resurrected."""

    def resolve_as_of(self, query):
        return query.as_of

    def rank(self, query, beliefs):
        return [ScoredBelief(belief=b, score=999.0) for b in beliefs]


def test_validity_filter_precedes_rank() -> None:
    valid = Belief(id="valid", statement="x", created_at=_w(2019), valid_at=_w(2019))
    future = Belief(id="future", statement="x", created_at=_w(2019), valid_at=_w(2025))
    query = RetrievalQuery(text="q", as_of=_w(2020), top_k=10)

    ranked = rank_valid([future, valid], query, DefaultValidityPolicy(), _RankInvalidFirst())
    ids = [s.belief.id for s in ranked]
    assert ids == ["valid"], "ranker must not resurrect a temporally-invalid fact"


def test_rank_valid_truncates_after_filter() -> None:
    beliefs = [
        Belief(id=f"b{i}", statement="x", created_at=_w(2019), valid_at=_w(2019))
        for i in range(5)
    ]
    query = RetrievalQuery(text="q", as_of=_w(2020), top_k=2)
    assert len(rank_valid(beliefs, query)) == 2


def test_iso_lexicographic_equals_chronological() -> None:
    # G4b: the Cypher temporal predicate relies on ISO-8601 UTC strings sorting
    # chronologically, including the microseconds-vs-no-microseconds boundary.
    times = [
        datetime(2019, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 29, 1, 51, 55, tzinfo=timezone.utc), # no microseconds
        datetime(2026, 6, 29, 1, 51, 55, 253024, tzinfo=timezone.utc),
        datetime(2026, 6, 29, 1, 51, 57, 850130, tzinfo=timezone.utc),
    ]
    by_iso = sorted(t.isoformat() for t in times)
    by_time = [t.isoformat() for t in sorted(times)]
    assert by_iso == by_time
