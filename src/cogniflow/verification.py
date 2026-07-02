"""verify_fact: the LLM-driven, read-only FalsificationPolicy .

This is the policy explicitly deferred in milestone, now filled in and registered as
``falsification: llm``. It is **read-only and advisory**: it returns a verdict and
NEVER writes to the graph. The authoritative falsification stays the free write-time
supersession from ingestion; if an agent acts on a verify verdict it does so through
the existing queued write-back path, not from here.

It is irreducibly probabilistic, so it is fully bounded: the LLM call goes through an
injected ``complete`` callable (the caller enforces the timeout); ANY failure, timeout,
or unparseable response yields a *distinguishable indeterminate* verdict
(``indeterminate=True``), never a confident "not superseded" and never a write.

Standard library only (urllib for the optional default client), so it is import-safe
without graphiti/llama-index and unit-testable with a fake ``complete``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from .core.types import Belief, FalsificationVerdict
from .registry import register_policy

# prompt -> raw model text. The caller is responsible for bounding it (timeout etc.).
CompleteFn = Callable[[str], str]


def _build_prompt(target: Belief, candidates: Sequence[Belief]) -> str:
    lines = [
        "You check whether a TARGET fact is contradicted or superseded by any CANDIDATE "
        "fact. Two facts contradict if they assign the same attribute of the same entity "
        "to different values over overlapping time. Respond with ONLY a JSON object: "
        '{"superseded": true|false, "superseded_by": "<candidate id or null>", '
        '"rationale": "<one sentence>"}.',
        "",
        f"TARGET[id={target.id}]: {target.statement} "
        f"(valid_at={target.valid_at}, invalid_at={target.invalid_at})",
        "CANDIDATES:",
    ]
    for c in candidates:
        lines.append(
            f"- [id={c.id}] {c.statement} "
            f"(valid_at={c.valid_at}, invalid_at={c.invalid_at})"
        )
    return "\n".join(lines)


def _extract_json(raw: str) -> dict[str, Any] | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError):
        return None


@register_policy("falsification", "llm")
class LLMFalsificationPolicy:
    """Read-only, advisory, bounded LLM contradiction check."""

    def __init__(self, complete: CompleteFn | None = None, *, max_candidates: int = 10) -> None:
        self._complete = complete
        self._max_candidates = max_candidates

    @staticmethod
    def _indeterminate(target: Belief, why: str) -> FalsificationVerdict:
        return FalsificationVerdict(
            target_id=target.id,
            superseded=False,
            indeterminate=True,
            rationale=f"indeterminate: {why}",
        )

    def assess(self, target: Belief, candidates: Sequence[Belief]) -> FalsificationVerdict:
        if self._complete is None:
            return self._indeterminate(target, "no LLM configured")
        pool = [c for c in candidates if c.id != target.id][: self._max_candidates]
        try:
            raw = self._complete(_build_prompt(target, pool))
        except Exception as exc: # noqa: BLE001 - any failure -> bounded indeterminate, never raise
            return self._indeterminate(target, f"llm error: {type(exc).__name__}")

        parsed = _extract_json(raw)
        if parsed is None or "superseded" not in parsed:
            return self._indeterminate(target, "unparseable verdict")

        superseded = bool(parsed.get("superseded"))
        if not superseded:
            return FalsificationVerdict(
                target_id=target.id,
                superseded=False,
                rationale=str(parsed.get("rationale", "not contradicted"))[:300],
            )
        by = parsed.get("superseded_by")
        match = next((c for c in pool if c.id == by), None)
        return FalsificationVerdict(
            target_id=target.id,
            superseded=True,
            superseded_by=match.id if match else None,
            invalid_at=match.valid_at if match else None,
            rationale=str(parsed.get("rationale", "contradicted"))[:300],
        )


def complete_from_env(timeout: float = 30.0) -> CompleteFn:
    """Build a bounded OpenAI-compatible ``complete`` from COGNIFLOW_LLM_* env (loads
    .env). The ``timeout`` is the hard bound; on expiry the HTTP call raises and the
    policy degrades to indeterminate."""
    import os
    import urllib.request

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    api_key = os.getenv("COGNIFLOW_LLM_API_KEY")
    base_url = (os.getenv("COGNIFLOW_LLM_BASE_URL") or "").rstrip("/")
    model = os.getenv("COGNIFLOW_LLM_MODEL")

    def complete(prompt: str) -> str:
        request = urllib.request.Request(
            base_url + "/chat/completions",
            data=json.dumps(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 512,
                    "temperature": 0,
                }
            ).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)["choices"][0]["message"]["content"]

    return complete
