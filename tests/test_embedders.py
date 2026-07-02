"""Embedder plug (config-selected, fail-loud, dimension-safe) - CI-safe, no network.

The two load-bearing properties get the hardest tests: fail-loud (never a silent hash
fallback) and dimension-validation (hard-crash on mismatch).
"""

from __future__ import annotations

import pytest

pytest.importorskip("graphiti_core") # the embedder layer wraps Graphiti's EmbedderClient

from cogniflow.backends._local_embedder import LocalDeterministicEmbedder  # noqa: E402
from cogniflow.backends.embedders import (  # noqa: E402
    EXCLUDED_MODELS,
    EmbedderDimensionMismatch,
    EmbedderError,
    NvidiaEmbedder,
    available_embedders,
    check_embedding_dimension,
    create_embedder,
)
from cogniflow.backends.graphiti_falkordb import GraphitiFalkorDBConfig  # noqa: E402


@pytest.fixture(autouse=True)
def _no_ambient_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # the fail-loud tests must not be rescued by an ambient key in the environment
    monkeypatch.delenv("COGNIFLOW_EMBEDDER_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)


def test_hash_is_the_default_and_key_free() -> None:
    assert GraphitiFalkorDBConfig().embedder == "hash" # T5: default stays hash
    e = create_embedder("hash")
    assert isinstance(e, LocalDeterministicEmbedder)
    assert e.embedding_dim == 1024
    assert isinstance(create_embedder(None), LocalDeterministicEmbedder)


def test_real_embedder_selected_by_name_carries_dimension() -> None:
    e = create_embedder("bge-m3", api_key="x") # no network at construction
    assert isinstance(e, NvidiaEmbedder)
    assert e.model == "baai/bge-m3"
    assert e.embedding_dim == 1024 # T1: dimension carried
    assert create_embedder("nvidia-e5", api_key="x").model == "nvidia/nv-embedqa-e5-v5"
    assert create_embedder("bge-m3", api_key="x", embedding_dim=2048).embedding_dim == 2048


def test_fail_loud_missing_key_does_not_fall_back_to_hash() -> None:
    with pytest.raises(EmbedderError) as ei:
        create_embedder("bge-m3") # no key, no ambient env
    assert "key" in str(ei.value).lower() # clear message
    # the crucial property: it raised, it did NOT silently return the hash embedder


def test_fail_loud_unknown_name() -> None:
    with pytest.raises(EmbedderError) as ei:
        create_embedder("totally-made-up", api_key="x")
    assert "unknown" in str(ei.value).lower()


def test_excluded_model_is_license_blocked() -> None:
    assert "nvidia/nv-embed-v1" in EXCLUDED_MODELS # documented exclusion
    with pytest.raises(EmbedderError) as ei:
        create_embedder("nv-embed-v1", api_key="x")
    assert "license" in str(ei.value).lower()
    # cannot sneak it in via a model override either
    with pytest.raises(EmbedderError):
        create_embedder("bge-m3", api_key="x", model="nvidia/nv-embed-v1")


def test_dimension_guard_hard_crashes_on_mismatch() -> None:
    check_embedding_dimension(None, 1024) # empty/undetectable store -> no-op
    check_embedding_dimension(1024, 1024) # match -> ok
    with pytest.raises(EmbedderDimensionMismatch) as ei:
        check_embedding_dimension(768, 1024) # mismatch -> hard-crash, never warn
    assert "mismatch" in str(ei.value).lower()


def test_available_embedders_lists_hash_and_real() -> None:
    names = available_embedders()
    assert "hash" in names and "bge-m3" in names and "nvidia-e5" in names
