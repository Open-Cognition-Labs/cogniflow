"""Reranker - cheap live check (one API call): the real NVIDIA cross-encoder reorders
confusable candidates correctly through the RerankerRetrievalPolicy. The full off-vs-on lift
measurement is reproducible via demo/capture_demo.py (captured in demo/static_demo/demo_data.json).
Skipped without a key.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

pytest.importorskip("graphiti_core")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from cogniflow.core.types import Belief, RetrievalQuery  # noqa: E402
from cogniflow.rerankers import RerankerRetrievalPolicy  # noqa: E402

requires_key = pytest.mark.skipif(
    not (os.getenv("COGNIFLOW_RERANKER_API_KEY") or os.getenv("COGNIFLOW_EMBEDDER_API_KEY")
         or os.getenv("COGNIFLOW_LLM_API_KEY")),
    reason="requires an NVIDIA API key for the reranker",
)


def _b(bid: str, statement: str) -> Belief:
    return Belief(id=bid, statement=statement, created_at=datetime(2020, 1, 1, tzinfo=timezone.utc))


@pytest.mark.integration
@requires_key
def test_nvidia_reranker_reorders_confusable_candidates_live() -> None:
    policy = RerankerRetrievalPolicy(reranker="nvidia-rerank")
    beliefs = [
        _b("rivian", "Rivian is headquartered in Irvine"),
        _b("model3", "Tesla makes the Model 3 electric car"),
        _b("tesla", "Tesla is headquartered in Austin"),
    ]
    ranked = policy.rank(RetrievalQuery(text="Where is Tesla headquartered?", top_k=3), beliefs)
    assert ranked[0].belief.id == "tesla" # the real cross-encoder floats the HQ fact to #1
    assert ranked[0].score >= ranked[-1].score # descending by relevance
