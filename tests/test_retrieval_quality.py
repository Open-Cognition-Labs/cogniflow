"""milestone: first-run retrieval is never silently meaning-blind, and the over-fetch
false-negative risk is surfaced, not silent. CI-safe (no infra, no network, no torch)."""

from __future__ import annotations

import asyncio
import importlib.util
import logging

import pytest

from cogniflow.backends._local_embedder import LocalDeterministicEmbedder
from cogniflow.backends.embedders import (
    EmbedderError,
    available_embedders,
    create_embedder,
    is_semantic,
    warn_if_non_semantic,
)
from cogniflow.context import (
    NON_SEMANTIC_RETRIEVAL_NOTE,
    OVERFETCH_SATURATED_NOTE,
    serve_context,
)
from cogniflow.core.types import RetrievalResult, ScoredBelief

_HAS_FLAG = importlib.util.find_spec("FlagEmbedding") is not None


class _FakeSubstrate:
    """Minimal AsyncSubstrate: serve_context only calls read() + reads the health flags."""

    def __init__(self, *, semantic: bool, saturated: bool) -> None:
        self.embedder_is_semantic = semantic
        self.last_read_saturated = saturated

    async def read(self, query): # noqa: ANN001
        return RetrievalResult(query=query, results=(), as_of=query.as_of)


def test_hash_is_boot_default_and_not_semantic() -> None:
    # the key-free boot default is preserved (T5) ...
    assert isinstance(create_embedder(), LocalDeterministicEmbedder)
    # ... but it is honestly labeled meaning-blind (T1)
    assert is_semantic(create_embedder("hash")) is False


def test_bge_m3_local_is_a_selectable_key_free_semantic_option() -> None:
    assert "bge-m3-local" in available_embedders() # the key-free semantic Quickstart choice


@pytest.mark.skipif(_HAS_FLAG, reason="fail-loud path only when the [embeddings] extra is absent")
def test_bge_m3_local_fails_loud_without_the_extra() -> None:
    with pytest.raises(EmbedderError) as e:
        create_embedder("bge-m3-local")
    msg = str(e.value)
    assert "embeddings" in msg # names the extra
    assert "hash" in msg # and states it will NOT silently fall back to hash


def test_warn_fires_on_hash_outside_tests(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False) # simulate a real (non-test) run
    with caplog.at_level(logging.WARNING, logger="cogniflow"):
        warn_if_non_semantic(create_embedder("hash"))
    assert caplog.records, "hash must warn loudly outside a test - never silent (T1)"
    assert "non-semantic" in caplog.records[0].message.lower()


def test_warn_is_silent_inside_tests(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "sentinel") # the pytest-run marker
    with caplog.at_level(logging.WARNING, logger="cogniflow"):
        warn_if_non_semantic(create_embedder("hash"))
    assert not caplog.records # deterministic + clean in the suite (correctness tests run on hash)


def test_serve_context_surfaces_both_retrieval_notes() -> None:
    resp = asyncio.run(serve_context(_FakeSubstrate(semantic=False, saturated=True), "q", top_k=3))
    assert NON_SEMANTIC_RETRIEVAL_NOTE in resp.notes # T1
    assert OVERFETCH_SATURATED_NOTE in resp.notes # T3


def test_serve_context_clean_when_semantic_and_unsaturated() -> None:
    resp = asyncio.run(serve_context(_FakeSubstrate(semantic=True, saturated=False), "q", top_k=3))
    assert NON_SEMANTIC_RETRIEVAL_NOTE not in resp.notes
    assert OVERFETCH_SATURATED_NOTE not in resp.notes


def test_scored_belief_shape_is_stable() -> None:
    # guard: serve_context maps ScoredBelief -> ServedFact; keep the field it reads
    assert ScoredBelief.__dataclass_fields__.keys() >= {"belief", "score"}
