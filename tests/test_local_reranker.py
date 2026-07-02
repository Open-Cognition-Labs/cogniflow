"""milestone: the DEFAULT local reranker (bge-reranker-v2-m3) is real or honestly labeled.

The reranking POLICY path is covered in test_rerankers.py with an injected cross-encoder. Here
we pin the local default itself: without the [reranker] extra it fails loud with the install
hint (never a silent no-op); with the extra it actually runs and reranks. So the default is
verified when the deps are present and honestly fail-loud otherwise - not a hollow default.
"""

from __future__ import annotations

import importlib.util

import pytest

from cogniflow.rerankers import RerankerError, create_reranker

_HAS_FLAG = importlib.util.find_spec("FlagEmbedding") is not None


@pytest.mark.skipif(_HAS_FLAG, reason="fail-loud path only when the [reranker] extra is absent")
def test_local_default_reranker_fails_loud_without_extra() -> None:
    with pytest.raises(RerankerError) as e:
        create_reranker("bge-reranker-v2-m3") # the documented self-hosted DEFAULT
    assert "reranker" in str(e.value).lower() # names the [reranker] extra; no silent no-op


@pytest.mark.skipif(not _HAS_FLAG, reason="requires the [reranker] extra (torch + model weights)")
def test_local_default_reranker_runs_and_reranks() -> None:
    r = create_reranker("bge-reranker-v2-m3")
    scores = r.score(
        "Where is Tesla headquartered",
        ["Tesla is headquartered in Austin", "A cat sat on a mat"],
    )
    assert len(scores) == 2
    assert scores[0] > scores[1] # the on-topic passage outranks the off-topic one
