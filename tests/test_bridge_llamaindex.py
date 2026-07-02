"""Bridge unit tests (need llama-index-core, but no FalkorDB/LLM; skipped in CI).

Covers acceptance items that do not require the live stack:
  #2 one validity definition: the postprocessor drops the same node the backend
     read would, using the shared policy (no third copy).
  #4 the retriever overrides ``_aretrieve``: ``aretrieve`` succeeds inside a running
     loop, which is only possible if the async override runs (the sync ``_retrieve``
     raises inside a loop by design).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

pytest.importorskip("llama_index.core")

from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode  # noqa: E402

from cogniflow.bridges.llamaindex.postprocessor import (  # noqa: E402
    TemporalValidityPostprocessor,
)
from cogniflow.bridges.llamaindex.retriever import TemporalGraphRetriever  # noqa: E402
from cogniflow.core.policies import DefaultValidityPolicy, filter_valid  # noqa: E402
from cogniflow.core.types import (  # noqa: E402
    Belief,
    RetrievalQuery,
    RetrievalResult,
    ScoredBelief,
)


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _boston() -> Belief:
    return Belief(
        id="boston",
        statement="Acme Corp is headquartered in Boston",
        created_at=_dt(2019),
        valid_at=_dt(2019),
        invalid_at=_dt(2022),
        expired_at=_dt(2022),
        provenance=("ep1",),
    )


def _denver() -> Belief:
    return Belief(
        id="denver",
        statement="Acme Corp is headquartered in Denver",
        created_at=_dt(2022),
        valid_at=_dt(2022),
        provenance=("ep2",),
    )


class _FakeSubstrate:
    """Async in-memory substrate that applies the SAME validity rule as the backend."""

    def __init__(self, beliefs: list[Belief]) -> None:
        self._beliefs = beliefs

    async def write(self, episode): # pragma: no cover - not used here
        raise NotImplementedError

    async def read(self, query: RetrievalQuery) -> RetrievalResult:
        kept = filter_valid(self._beliefs, query.as_of, query.include_expired)
        results = tuple(ScoredBelief(belief=b) for b in kept[: query.top_k])
        return RetrievalResult(query=query, results=results, as_of=query.as_of)

    async def falsify(self, target, against=None): # pragma: no cover - not used here
        raise NotImplementedError


def _node(belief: Belief) -> NodeWithScore:
    return NodeWithScore(
        node=TextNode(
            text=belief.statement,
            metadata={
                "belief_id": belief.id,
                "valid_at": belief.valid_at.isoformat() if belief.valid_at else None,
                "invalid_at": belief.invalid_at.isoformat() if belief.invalid_at else None,
                "created_at": belief.created_at.isoformat(),
                "expired_at": belief.expired_at.isoformat() if belief.expired_at else None,
                "provenance": list(belief.provenance),
            },
        )
    )


def test_postprocessor_uses_shared_policy_and_drops_future_fact() -> None:
    nodes = [_node(_boston()), _node(_denver())]
    pp = TemporalValidityPostprocessor(validity_policy=DefaultValidityPolicy(), as_of=_dt(2020))
    kept = pp.postprocess_nodes(nodes)
    # at 2020 only Boston is valid - exactly what the backend read would keep
    assert [n.node.text for n in kept] == ["Acme Corp is headquartered in Boston"]


def test_postprocessor_excludes_invalidated_fact_after_supersession() -> None:
    nodes = [_node(_boston()), _node(_denver())]
    pp = TemporalValidityPostprocessor(validity_policy=DefaultValidityPolicy(), as_of=_dt(2023))
    kept = [n.node.text for n in pp.postprocess_nodes(nodes)]
    assert kept == ["Acme Corp is headquartered in Denver"]


def test_postprocessor_uses_injected_policy_instance() -> None:
    # P1: the injected instance governs behavior (one instance, not one class).
    class _AlwaysInvalid:
        def is_valid(self, belief, as_of, include_expired=False) -> bool:
            return False

    policy = _AlwaysInvalid()
    pp = TemporalValidityPostprocessor(validity_policy=policy, as_of=_dt(2020))
    assert pp.validity is policy
    assert pp.postprocess_nodes([_node(_boston())]) == [] # injected policy drops everything


def test_postprocessor_requires_explicit_policy_fail_loud() -> None:
    # T2/P1': no silent default. A missing policy must raise at construction time.
    with pytest.raises(ValueError):
        TemporalValidityPostprocessor(as_of=_dt(2020))


def test_retriever_async_override_runs_inside_event_loop() -> None:
    async def run() -> list[str]:
        retriever = TemporalGraphRetriever(_FakeSubstrate([_boston(), _denver()]), as_of=_dt(2020))
        # aretrieve must dispatch to _aretrieve; if it fell back to _retrieve, that
        # raises inside a running loop by design.
        nodes = await retriever.aretrieve(QueryBundle(query_str="where is Acme HQ?"))
        return [n.node.text for n in nodes]

    assert asyncio.run(run()) == ["Acme Corp is headquartered in Boston"]
