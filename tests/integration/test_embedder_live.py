"""Embedder plug - live probe (acceptance #1): the real BGE-M3 embedder is in the loop and
produces genuine semantic vectors, distinct from the hash embedder. Needs
COGNIFLOW_EMBEDDER_API_KEY; skipped without it.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytest.importorskip("graphiti_core")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from cogniflow.backends._local_embedder import LocalDeterministicEmbedder  # noqa: E402
from cogniflow.backends.embedders import NvidiaEmbedder, create_embedder  # noqa: E402

requires_key = pytest.mark.skipif(
    not os.getenv("COGNIFLOW_EMBEDDER_API_KEY"),
    reason="requires COGNIFLOW_EMBEDDER_API_KEY",
)


@pytest.mark.integration
@requires_key
def test_bge_m3_returns_real_semantic_vectors() -> None:
    async def run() -> None:
        embedder = create_embedder("bge-m3") # key from env
        assert isinstance(embedder, NvidiaEmbedder)
        text = "Acme Corp is headquartered in Denver"
        vec = await embedder.create(text)
        assert len(vec) == embedder.embedding_dim == 1024
        assert any(abs(x) > 1e-9 for x in vec) # real, non-trivial vector

        # genuinely semantic: different from the hash embedder's vector for the same text
        hash_vec = await LocalDeterministicEmbedder(1024).create(text)
        assert vec != hash_vec

        # related texts are closer than unrelated ones (cosine) - a sanity check that it
        # carries meaning, not noise
        denver2 = await embedder.create("The headquarters of Acme Corp is in Denver")
        paris = await embedder.create("The Eiffel Tower is a landmark in Paris")

        def cos(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b, strict=True))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(y * y for y in b) ** 0.5
            return dot / (na * nb)

        assert cos(vec, denver2) > cos(vec, paris)

    asyncio.run(run())
