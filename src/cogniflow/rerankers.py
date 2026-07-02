"""Pluggable rerankers - config-selected, fail-loud, measured not assumed.

The reranker is a retrieval-stage plug (it slots into the existing "retrieval" policy family,
so no new mechanism and no core change): after the deterministic validity filter, a
cross-encoder re-scores the surviving candidates against the query, then truncation to top_k
runs. Reranking never runs on temporally-invalid facts (rank_valid's ordering), so it can
neither consume budget on nor resurrect an invalid fact.

Honest positioning:
- The retriever sets the ceiling. A reranker sharpens *ranking*; it does not fix *recall* -
  it cannot surface what retrieval never returned.
- Off by default. The minimal/GPU-free path uses the passthrough "default" retrieval policy;
  reranking is the opt-in "turn on for quality" tier, justified by measured lift, not by spec.
- Model-agnostic plug. Default target is ``bge-reranker-v2-m3`` (BAAI, Apache-2.0, ~278M,
  self-hostable, coherent with the BGE-M3 embedder); ``nvidia-rerank`` is the API-reachable
  option used to measure lift here. Heavier tiers (gemma / Qwen3 / hosted) are one config
  change away. Size does not determine quality - measure on YOUR corpus.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .core.types import Belief, RetrievalQuery, ScoredBelief
from .registry import register_policy

_RETRY_STATUS = {429, 500, 502, 503, 504}
_NVIDIA_RERANK_URL = "https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking"
_NVIDIA_RERANK_MODEL = "nvidia/rerank-qa-mistral-4b"
_DEFAULT_RERANKER = "bge-reranker-v2-m3"


class RerankerError(RuntimeError):
    """Fail-loud reranker selection/configuration error."""


@runtime_checkable
class CrossEncoder(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]:
        """Return a relevance score per passage, aligned to input order."""
        ...


class NvidiaReranker:
    """Cross-encoder over NVIDIA's reranking endpoint (the API-reachable option, used to
    measure lift). Stdlib HTTP; returns logits aligned to the input passage order."""

    def __init__(
        self,
        api_key: str,
        model: str = _NVIDIA_RERANK_MODEL,
        base_url: str = _NVIDIA_RERANK_URL,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout

    def _post_with_retry(self, req: urllib.request.Request, attempts: int = 4) -> dict:
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code in _RETRY_STATUS and attempt < attempts - 1:
                    time.sleep(2**attempt)
                    continue
                raise

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        req = urllib.request.Request(
            self.base_url,
            data=json.dumps(
                {
                    "model": self.model,
                    "query": {"text": query},
                    "passages": [{"text": p} for p in passages],
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        payload = self._post_with_retry(req)
        scores = [0.0] * len(passages)
        for row in payload.get("rankings", []):
            scores[row["index"]] = float(row["logit"])
        return scores


class BgeLocalReranker:
    """The DEFAULT, self-hostable cross-encoder: bge-reranker-v2-m3 via FlagEmbedding (the
    ``[reranker]`` extra + a local model download). Runs in the caller's environment - the
    VPC wedge. Not exercised in the CI/build env here (torch/model weights); the interface
    and seam are in place and a real API cross-encoder measures the lift."""

    def __init__(self, model: str = "BAAI/bge-reranker-v2-m3") -> None: # pragma: no cover
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as e:
            raise RerankerError(
                "bge-reranker-v2-m3 needs the 'reranker' extra: pip install "
                "'cogniflow-rag[reranker]'. Or select 'nvidia-rerank' for the hosted option."
            ) from e
        self.model = model
        self._reranker = FlagReranker(model, use_fp16=True)

    def score(self, query: str, passages: list[str]) -> list[float]: # pragma: no cover
        if not passages:
            return []
        return [float(s) for s in self._reranker.compute_score([[query, p] for p in passages])]


def available_rerankers() -> list[str]:
    return ["bge-reranker-v2-m3", "nvidia-rerank"]


def create_reranker(
    name: str | None = _DEFAULT_RERANKER,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> CrossEncoder:
    """Construct a reranker by config name. Fail-loud: a missing key or an unknown name
    raises - never a silent no-op (which would leave ranking unchanged while claiming a
    reranker is active)."""
    name = (name or _DEFAULT_RERANKER).strip()
    if name == "bge-reranker-v2-m3":
        return BgeLocalReranker(model or "BAAI/bge-reranker-v2-m3")
    if name == "nvidia-rerank":
        key = (
            api_key
            or os.getenv("COGNIFLOW_RERANKER_API_KEY")
            or os.getenv("COGNIFLOW_EMBEDDER_API_KEY")
            or os.getenv("COGNIFLOW_LLM_API_KEY")
            or os.getenv("NVIDIA_API_KEY")
        )
        if not key:
            raise RerankerError(
                "reranker 'nvidia-rerank' needs an API key; set COGNIFLOW_RERANKER_API_KEY "
                "(or COGNIFLOW_EMBEDDER_API_KEY / COGNIFLOW_LLM_API_KEY, or pass api_key)."
            )
        return NvidiaReranker(api_key=key, model=model or _NVIDIA_RERANK_MODEL,
                              base_url=base_url or _NVIDIA_RERANK_URL)
    raise RerankerError(
        f"unknown reranker {name!r}; available: {available_rerankers()} "
        "(heavier tiers like gemma/Qwen3 slot in via the same plug)."
    )


@register_policy("retrieval", "reranker")
class RerankerRetrievalPolicy:
    """A retrieval policy that reorders candidates with a cross-encoder. Selected by config
    (``retrieval_policy='reranker'``, ``retrieval_params={'reranker': 'nvidia-rerank'}``).
    Accepts an injected ``cross_encoder`` (for tests) or builds one from the name (fail-loud).
    """

    def __init__(
        self,
        reranker: str | None = _DEFAULT_RERANKER,
        *,
        cross_encoder: CrossEncoder | None = None,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._ce = cross_encoder or create_reranker(
            reranker, api_key=api_key, model=model, base_url=base_url
        )

    def resolve_as_of(self, query: RetrievalQuery): # noqa: ANN201 - mirrors the protocol
        return query.as_of

    def rank(self, query: RetrievalQuery, beliefs: Sequence[Belief]) -> Sequence[ScoredBelief]:
        items = list(beliefs)
        if not items:
            return []
        scores = self._ce.score(query.text, [b.statement for b in items])
        paired = sorted(zip(items, scores, strict=True), key=lambda t: t[1], reverse=True)
        return [ScoredBelief(belief=b, score=float(s)) for b, s in paired]
