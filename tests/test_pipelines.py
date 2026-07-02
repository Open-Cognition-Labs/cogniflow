"""Straight temporal-RAG loop (T3) - CI-safe with a fake substrate + fake generator.

Confirms it is a STRAIGHT pipeline (retrieve -> generate, one shot), that it threads
as_of into retrieval, and that the answer is grounded only in the retrieved facts.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from cogniflow.core.types import (
    Belief,
    FalsificationVerdict,
    RetrievalQuery,
    RetrievalResult,
    ScoredBelief,
)
from cogniflow.pipelines import temporal_rag_answer


def _w(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


class _AsOfSubstrate:
    """Returns the March or June definition depending on the query's as_of."""

    async def read(self, query: RetrievalQuery) -> RetrievalResult:
        if query.as_of is not None and query.as_of < _w(2026):
            fact = "WAU = trailing 7-day distinct users"
        else:
            fact = "WAU = trailing 28-day distinct users"
        belief = Belief(id="wau", statement=fact, created_at=_w(2025))
        return RetrievalResult(
            query=query, results=(ScoredBelief(belief=belief),), as_of=query.as_of
        )

    async def write(self, episode): # pragma: no cover
        raise NotImplementedError

    async def falsify(self, target, against=None) -> FalsificationVerdict: # pragma: no cover
        return FalsificationVerdict(target_id=str(target), superseded=False)


async def _echo_generate(prompt: str) -> str:
    # A trivial "LLM": echo the single fact line so we can assert grounding.
    for line in prompt.splitlines():
        if line.startswith("- "):
            return line[2:]
    return "do not know"


def test_straight_loop_grounds_answer_in_retrieved_facts() -> None:
    res = asyncio.run(temporal_rag_answer(_AsOfSubstrate(), "Define WAU", _echo_generate))
    assert res.facts == ["WAU = trailing 28-day distinct users"]
    assert "28-day" in res.answer # answered only from the retrieved fact


def test_as_of_is_threaded_into_retrieval() -> None:
    march = asyncio.run(
        temporal_rag_answer(_AsOfSubstrate(), "Define WAU", _echo_generate, as_of=_w(2020))
    )
    june = asyncio.run(
        temporal_rag_answer(_AsOfSubstrate(), "Define WAU", _echo_generate, as_of=_w(2027))
    )
    assert "7-day" in march.answer
    assert "28-day" in june.answer # same question, different as_of -> different answer


def test_sync_generator_is_supported() -> None:
    res = asyncio.run(
        temporal_rag_answer(_AsOfSubstrate(), "Define WAU", lambda p: "static answer")
    )
    assert res.answer == "static answer"
