"""Reranker plug (config-selected, fail-loud, off-by-default) - CI-safe, no network."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cogniflow.core.types import Belief, RetrievalQuery
from cogniflow.registry import DEFAULT_POLICIES, available_policies, create_policy
from cogniflow.rerankers import (
    NvidiaReranker,
    RerankerError,
    RerankerRetrievalPolicy,
    available_rerankers,
    create_reranker,
)


def _belief(bid: str, statement: str) -> Belief:
    return Belief(id=bid, statement=statement, created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))


class _FakeCrossEncoder:
    """Scores by keyword overlap with the query - deterministic, no network."""

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = set(query.lower().split())
        return [float(len(q & set(p.lower().split()))) for p in passages]


def test_reranker_is_registered_but_off_by_default() -> None:
    assert "reranker" in available_policies("retrieval") # plug is available
    assert DEFAULT_POLICIES["retrieval"] == "default" # ...but OFF by default (GPU-free path)


def test_reranker_policy_reorders_by_cross_encoder_score() -> None:
    policy = RerankerRetrievalPolicy(cross_encoder=_FakeCrossEncoder())
    beliefs = [
        _belief("rivian", "Rivian is headquartered in Irvine"),
        _belief("tesla", "Tesla is headquartered in Austin"),
        _belief("model3", "The Tesla Model 3 is an electric car"),
    ]
    q = RetrievalQuery(text="Where is Tesla headquartered", top_k=3)
    ranked = policy.rank(q, beliefs)
    assert ranked[0].belief.id == "tesla" # the query's entity floats to #1
    assert ranked[0].score >= (ranked[1].score or 0) # scores are descending


def test_reranker_policy_via_registry_with_injected_encoder() -> None:
    # config-selected through the same registry as every other policy
    policy = create_policy("retrieval", "reranker", cross_encoder=_FakeCrossEncoder())
    assert isinstance(policy, RerankerRetrievalPolicy)


def test_reranker_empty_candidates_is_safe() -> None:
    policy = RerankerRetrievalPolicy(cross_encoder=_FakeCrossEncoder())
    assert policy.rank(RetrievalQuery(text="x", top_k=5), []) == []


def test_create_reranker_fail_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("COGNIFLOW_RERANKER_API_KEY", "COGNIFLOW_EMBEDDER_API_KEY",
                "COGNIFLOW_LLM_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RerankerError):
        create_reranker("nvidia-rerank") # no key -> raise, never a silent no-op
    with pytest.raises(RerankerError):
        create_reranker("made-up-reranker") # unknown name -> raise


def test_nvidia_reranker_constructs_without_network() -> None:
    r = create_reranker("nvidia-rerank", api_key="x")
    assert isinstance(r, NvidiaReranker)
    assert r.model == "nvidia/rerank-qa-mistral-4b"
    assert "bge-reranker-v2-m3" in available_rerankers() # the documented self-hosted default
