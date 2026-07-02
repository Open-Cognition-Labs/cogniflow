"""Pluggable generation LLMs - config-selected, fail-loud, model-agnostic.

The generation layer is model-agnostic even in generation: the answer-producing LLM is a
plug (like the embedder), selected by config, never hard-wired. One OpenAI-compatible client
covers NVIDIA (MiniMax), OpenAI, and any compatible endpoint via base_url + model; a
self-hosted/local model slots in the same way for the VPC wedge.

Dependency-light: stdlib HTTP only, so the generation core carries no LLM-SDK dependency.
Fail-loud: a missing key or an unknown name raises at construction - never a silent no-op.

WARNING - swapping the generation model is not free: temporal correctness at the generation
edge has a model-dependent half (prompt adherence - the model honoring "answer only from the
served context, ignore your training"). The as-of filtering that removes the wrong fact is
deterministic, but a weaker model may still override the context with its training knowledge.
Re-run the centerpiece test against any new model before trusting it
(tests/integration/test_generation_live.py; see docs/GENERATION.md).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request

_RETRY_STATUS = {429, 500, 502, 503, 504}


def _urlopen_json(req: urllib.request.Request, timeout: float, attempts: int = 6) -> dict:
    """POST with bounded backoff on transient statuses (429/5xx) - hosted APIs rate-limit."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code in _RETRY_STATUS and attempt < attempts - 1:
                time.sleep(2**attempt) # 1s, 2s, 4s
                continue
            raise

_DEFAULT_BASE = "https://integrate.api.nvidia.com/v1"
_DEFAULT_MODEL = "minimaxai/minimax-m3"

# Config name -> (default model, default base_url). All are OpenAI-compatible chat endpoints.
_PRESETS: dict[str, tuple[str, str]] = {
    "nvidia": (_DEFAULT_MODEL, _DEFAULT_BASE),
    "minimax": (_DEFAULT_MODEL, _DEFAULT_BASE),
    "openai": ("gpt-4o-mini", "https://api.openai.com/v1"),
}


class GeneratorError(RuntimeError):
    """Fail-loud generation-LLM selection/configuration error."""


class OpenAICompatibleGenerator:
    """An async, model-agnostic chat generator over any OpenAI-compatible endpoint.

    ``max_tokens`` is set deliberately: MiniMax-M3 (a reasoning model) returns empty choices
    when unbounded, so leave headroom for reasoning plus the answer. Temperature defaults to 0
    for a grounded, reproducible answer.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE,
        max_tokens: int = 2048,
        temperature: float = 0.0,
        timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    def _post(self, prompt: str) -> str:
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(
                {
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        payload = _urlopen_json(req, self.timeout)
        choices = payload.get("choices") or []
        if not choices:
            raise GeneratorError(f"generation LLM returned no choices: {payload!r}")
        return (choices[0].get("message", {}).get("content") or "").strip()

    async def __call__(self, prompt: str) -> str:
        return await asyncio.to_thread(self._post, prompt)


def available_generators() -> list[str]:
    return sorted(_PRESETS)


def create_generator(
    name: str | None = "nvidia",
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    max_tokens: int = 2048,
) -> OpenAICompatibleGenerator:
    """Construct a generation LLM by config name. Fail-loud: a missing key or an unknown name
    raises - it never silently returns a no-op generator."""
    name = (name or "nvidia").strip()
    if name not in _PRESETS:
        raise GeneratorError(
            f"unknown generator {name!r}; available: {available_generators()} "
            "(or pass model + base_url for another OpenAI-compatible endpoint)."
        )
    default_model, default_base = _PRESETS[name]
    key = (
        api_key
        or os.getenv("COGNIFLOW_GENERATOR_API_KEY")
        or os.getenv("COGNIFLOW_LLM_API_KEY")
        or os.getenv("NVIDIA_API_KEY")
    )
    if not key:
        raise GeneratorError(
            f"generator {name!r} needs an API key; set COGNIFLOW_GENERATOR_API_KEY "
            "(or COGNIFLOW_LLM_API_KEY, or pass api_key)."
        )
    return OpenAICompatibleGenerator(
        api_key=key,
        model=model or default_model,
        base_url=base_url or default_base,
        max_tokens=max_tokens,
    )


def create_generator_from_env(max_tokens: int = 2048) -> OpenAICompatibleGenerator:
    """Build a generator from environment (COGNIFLOW_GENERATOR* then COGNIFLOW_LLM_*)."""
    return create_generator(
        os.getenv("COGNIFLOW_GENERATOR", "nvidia"),
        model=os.getenv("COGNIFLOW_GENERATOR_MODEL") or os.getenv("COGNIFLOW_LLM_MODEL"),
        base_url=os.getenv("COGNIFLOW_GENERATOR_BASE_URL") or os.getenv("COGNIFLOW_LLM_BASE_URL"),
        max_tokens=max_tokens,
    )
