"""Pluggable embedders - config-selected, fail-loud, bring-your-own.

The embedder is a commodity layer like backends and policies: selectable by config name, not
by editing code. The hash embedder stays the key-free default (correctness tests do not depend
on embeddings); a real NVIDIA-API embedder (default ``baai/bge-m3``) puts genuine semantic
vectors in the loop for the end-to-end and demo paths.

Two safety properties are load-bearing:
  A. Fail-loud. A selected embedder with a missing key/dependency, or an unknown/excluded
     name, raises at construction - it NEVER silently falls back to the hash embedder. A
     silent fallback would serve meaning-blind retrieval that still returns results: no error,
     just silently wrong answers, the worst failure mode for a retrieval system.
  B. The dimension travels with the embedder and is validated against the store at startup,
     hard-crashing on mismatch (``check_embedding_dimension``). Mixing dimensions silently
     corrupts the vector space.

Model policy (see docs/EMBEDDERS.md): default ``baai/bge-m3`` (the self-hosted production
target; later swap to a local BGE-M3 with no code change), proven fallback
``nvidia/nv-embedqa-e5-v5``. ``nvidia/nv-embed-v1`` is EXCLUDED - non-commercial license -
and is never a default or selectable option.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request

from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig

from ._local_embedder import LocalDeterministicEmbedder

_LOG = logging.getLogger("cogniflow")
_RETRY_STATUS = {429, 500, 502, 503, 504}
_DEFAULT_NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"

# Config name -> NVIDIA model string. The default is bge-m3.
_NVIDIA_MODELS: dict[str, str] = {
    "bge-m3": "baai/bge-m3",
    "nvidia-e5": "nvidia/nv-embedqa-e5-v5",
}

# Deliberately excluded, with the reason. Never a default or selectable embedder.
EXCLUDED_MODELS: dict[str, str] = {
    "nvidia/nv-embed-v1": "non-commercial license; would poison open-source/enterprise adoption",
    "nv-embed-v1": "non-commercial license; would poison open-source/enterprise adoption",
}


class EmbedderError(RuntimeError):
    """Fail-loud embedder selection/configuration error (safety property A)."""


class EmbedderDimensionMismatch(EmbedderError):
    """The embedder's dimension does not match the existing store (safety property B)."""


class NvidiaEmbedder(EmbedderClient):
    """A Graphiti ``EmbedderClient`` backed by an NVIDIA OpenAI-compatible embeddings
    endpoint. Carries its vector dimension (the contract detail that makes 'any embedder'
    safe). Stdlib HTTP only - no extra dependency."""

    def __init__(
        self,
        api_key: str,
        model: str = "baai/bge-m3",
        base_url: str = _DEFAULT_NVIDIA_BASE,
        embedding_dim: int = 1024,
        timeout: float = 60.0,
    ) -> None:
        self.config = EmbedderConfig(embedding_dim=embedding_dim)
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    @property
    def embedding_dim(self) -> int:
        return self.config.embedding_dim

    def _post(self, texts: list[str], input_type: str) -> list[list[float]]:
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/embeddings",
            data=json.dumps(
                {"model": self.model, "input": texts, "input_type": input_type, "truncate": "END"}
            ).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read())
                break
            except urllib.error.HTTPError as e:
                if e.code in _RETRY_STATUS and attempt < 4:
                    time.sleep(2**attempt) # transient 429/5xx from the hosted API
                    continue
                raise
        return [row["embedding"] for row in payload["data"]]

    async def create(self, input_data: str | list[str]) -> list[float]:
        text = input_data if isinstance(input_data, str) else " ".join(map(str, input_data))
        vectors = await asyncio.to_thread(self._post, [text], "query")
        return vectors[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        if not input_data_list:
            return []
        return await asyncio.to_thread(self._post, list(input_data_list), "passage")


class LocalBgeEmbedder(EmbedderClient):
    """The key-free SEMANTIC embedder: BGE-M3 run locally via FlagEmbedding (the
    ``[embeddings]`` extra + a local model download). No API key; runs entirely in the caller's
    environment (the VPC path). Needs torch/model weights, so it is NOT the dependency-light
    default. 1024-dim dense vectors, matching the hosted ``bge-m3`` option, so the store
    dimension is identical either way. Verified by ``test_embedder_local`` when the extra is
    installed; a labeled wired-but-unverified seam otherwise (like the local reranker)."""

    def __init__( # pragma: no cover
        self, model: str = "BAAI/bge-m3", embedding_dim: int = 1024
    ) -> None:
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as e:
            raise EmbedderError(
                "embedder 'bge-m3-local' needs the 'embeddings' extra: pip install "
                "'cogniflow-rag[embeddings]' (torch + model weights). Or select 'bge-m3' for the "
                "dependency-light hosted option (needs COGNIFLOW_EMBEDDER_API_KEY). Refusing to "
                "silently fall back to the hash embedder."
            ) from e
        self.config = EmbedderConfig(embedding_dim=embedding_dim)
        self.model = model
        self._model = BGEM3FlagModel(model, use_fp16=True)

    @property
    def embedding_dim(self) -> int: # pragma: no cover
        return self.config.embedding_dim

    def _encode(self, texts: list[str]) -> list[list[float]]: # pragma: no cover
        dense = self._model.encode(texts, return_dense=True)["dense_vecs"]
        return [list(map(float, v)) for v in dense]

    async def create( # pragma: no cover
        self, input_data: str | list[str]
    ) -> list[float]:
        text = input_data if isinstance(input_data, str) else " ".join(map(str, input_data))
        vectors = await asyncio.to_thread(self._encode, [text])
        return vectors[0]

    async def create_batch( # pragma: no cover
        self, input_data_list: list[str]
    ) -> list[list[float]]:
        if not input_data_list:
            return []
        return await asyncio.to_thread(self._encode, list(input_data_list))


# The retrieval-quality warning surfaced when the meaning-blind hash embedder is in use. Kept
# here (the embedder concern); the serving layer surfaces its own response note .
NON_SEMANTIC_RETRIEVAL_WARNING = (
    "Retrieval is NON-SEMANTIC: the hash embedder is meaning-blind (it ranks by token overlap, "
    "not meaning). Configure a real embedder for semantic recall - 'bge-m3-local' (key-free, "
    "needs the [embeddings] extra) or 'bge-m3' (dependency-light, needs "
    "COGNIFLOW_EMBEDDER_API_KEY). See the Quickstart. (Hash stays the key-free boot default.)"
)


def is_semantic(embedder: EmbedderClient) -> bool:
    """True when the embedder produces meaning-based vectors (i.e. not the hash placeholder)."""
    return not isinstance(embedder, LocalDeterministicEmbedder)


def warn_if_non_semantic(embedder: EmbedderClient) -> None:
    """Emit a loud warning when running on the meaning-blind hash embedder outside a test, so a
    stranger never unknowingly evaluates retrieval on lexical results . Silent inside
    pytest so correctness tests (which run on hash by design) stay clean and deterministic."""
    if is_semantic(embedder) or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _LOG.warning(NON_SEMANTIC_RETRIEVAL_WARNING)


def available_embedders() -> list[str]:
    return ["hash", "bge-m3-local", *sorted(_NVIDIA_MODELS)]


def create_embedder(
    name: str | None = "hash",
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    embedding_dim: int = 1024,
) -> EmbedderClient:
    """Construct an embedder by config name. Fail-loud (safety property A): a missing key,
    an excluded model, or an unknown name raises - it never silently returns the hash embedder.
    """
    name = (name or "hash").strip()

    if name == "hash":
        return LocalDeterministicEmbedder(embedding_dim)

    if name == "bge-m3-local":
        # key-free semantic option (needs the [embeddings] extra); fail-loud if torch absent
        return LocalBgeEmbedder(model or "BAAI/bge-m3", embedding_dim=embedding_dim)

    if name in EXCLUDED_MODELS or (model and model in EXCLUDED_MODELS):
        reason = EXCLUDED_MODELS.get(name) or EXCLUDED_MODELS.get(model or "", "excluded")
        raise EmbedderError(f"embedder {name!r} is excluded: {reason}. See docs/EMBEDDERS.md.")

    if name in _NVIDIA_MODELS:
        resolved_model = model or _NVIDIA_MODELS[name]
        key = api_key or os.getenv("COGNIFLOW_EMBEDDER_API_KEY") or os.getenv("NVIDIA_API_KEY")
        if not key:
            raise EmbedderError(
                f"embedder {name!r} needs an API key; set COGNIFLOW_EMBEDDER_API_KEY "
                "(or pass api_key). Refusing to silently fall back to the hash embedder."
            )
        return NvidiaEmbedder(
            api_key=key,
            model=resolved_model,
            base_url=base_url or _DEFAULT_NVIDIA_BASE,
            embedding_dim=embedding_dim,
        )

    raise EmbedderError(
        f"unknown embedder {name!r}; available: {available_embedders()} "
        "(or plug a new EmbedderClient). Refusing to silently fall back to the hash embedder."
    )


def check_embedding_dimension(store_dim: int | None, embedder_dim: int) -> None:
    """Validate the selected embedder's dimension against the existing store (safety
    property B). Hard-crash on a definite mismatch; a ``None`` store_dim (empty/undetectable
    store) is a no-op - there is nothing yet to corrupt."""
    if store_dim is not None and store_dim != embedder_dim:
        raise EmbedderDimensionMismatch(
            f"embedding dimension mismatch: the store holds {store_dim}-dim vectors but the "
            f"selected embedder produces {embedder_dim}-dim vectors. Mixing dimensions "
            "corrupts the vector space. Re-ingest into a fresh store with a matching embedder, "
            "or select an embedder whose dimension matches the store."
        )
