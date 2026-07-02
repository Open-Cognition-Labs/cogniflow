# ruff: noqa: E501
"""A deliberately confusable corpus - it does double duty .

- Many similar entities with the SAME predicate ("headquartered in") and overlapping cities
  (two companies both moved to Austin) so retrieval faces genuine near-ties -> the first real
  stress of ranking (settles the reranker question on evidence, not a leaderboard).
- Two entities whose HQ changed over time (Tesla, Oracle) so the as-of axis has real contrast.

Deterministic: facts are structured triples (OKF fact-key path), written in chronological
order so the time-changed pairs supersede correctly regardless of embedder/LLM.
"""

from __future__ import annotations

from datetime import datetime, timezone

from cogniflow.core.types import Episode

UTC = timezone.utc


def _dt(y: int, m: int = 1) -> datetime:
    return datetime(y, m, 1, tzinfo=UTC)


def _hq(eid: str, company: str, city: str, year: int) -> Episode:
    return Episode(
        id=eid,
        content=f"{company} is headquartered in {city}.",
        reference_time=_dt(year),
        source="okf",
        metadata={
            "triple": {
                "source": company,
                "predicate": "HEADQUARTERED_IN",
                "target": city,
                "fact": f"{company} is headquartered in {city}",
            },
            "valid_at_source": "okf:timestamp",
        },
    )


def _makes(eid: str, company: str, product: str, year: int) -> Episode:
    return Episode(
        id=eid,
        content=f"{company} makes {product}.",
        reference_time=_dt(year),
        source="okf",
        metadata={
            "triple": {
                "source": company,
                "predicate": "MAKES",
                "target": product,
                "fact": f"{company} makes {product}",
            },
            "valid_at_source": "okf:timestamp",
        },
    )


# Chronological order: the older HQ of each moved company is written BEFORE the newer one, so
# the newer supersedes it (both-stamps) deterministically.
EPISODES: list[Episode] = [
    _hq("oracle_hq_old", "Oracle", "Redwood City", 1977),
    _hq("tesla_hq_old", "Tesla", "Palo Alto", 2010),
    _hq("rivian_hq", "Rivian", "Irvine", 2009),
    _hq("lucid_hq", "Lucid Motors", "Newark", 2016),
    _hq("x_hq", "X Corp", "San Francisco", 2007),
    _hq("palantir_hq", "Palantir", "Denver", 2020),
    _hq("oracle_hq_new", "Oracle", "Austin", 2020), # Oracle moved to Austin...
    _hq("tesla_hq_new", "Tesla", "Austin", 2021), # ...and so did Tesla (the collision)
    _makes("tesla_model3", "Tesla", "the Model 3 electric car", 2017),
    _makes("rivian_r1t", "Rivian", "the R1T electric truck", 2021),
]

# Golden set for reranking (current time). Each: a query and the entity whose HQ fact should
# rank #1. The cities collide (two Austins) and the predicate is shared, so this is a real
# disambiguation test, not a keyword lookup.
GOLDEN: list[dict[str, str]] = [
    {"query": "Where is Tesla headquartered?", "expect_city": "Austin", "expect_company": "Tesla"},
    {"query": "Where is Rivian's head office?", "expect_city": "Irvine", "expect_company": "Rivian"},
    {"query": "In which city is Lucid Motors based?", "expect_city": "Newark", "expect_company": "Lucid"},
    {"query": "Where does Palantir have its headquarters?", "expect_city": "Denver", "expect_company": "Palantir"},
    {"query": "Where is the maker of the R1T truck based?", "expect_city": "Irvine", "expect_company": "Rivian"},
    # harder, indirect queries (no entity name; require semantic disambiguation) - the real
    # stress on ranking, where a cross-encoder could earn its place
    {"query": "Which enterprise database company relocated to Texas?", "expect_city": "Austin", "expect_company": "Oracle"},
    {"query": "Which electric-truck company is based in Southern California?", "expect_city": "Irvine", "expect_company": "Rivian"},
    {"query": "Which data-analytics firm is headquartered in the Mile High City?", "expect_city": "Denver", "expect_company": "Palantir"},
]

# The as-of case for the head-to-head (temporal contrast).
AS_OF_CASE = {
    "query": "Where is Tesla headquartered?",
    "past": {"as_of": _dt(2015), "expect": "Palo Alto"},
    "now": {"expect": "Austin"},
}


async def build(backend) -> None:
    """Ingest the confusable corpus into a backend (already set up)."""
    for episode in EPISODES:
        await backend.write(episode)
