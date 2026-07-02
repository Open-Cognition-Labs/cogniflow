"""verify_fact (LLM FalsificationPolicy) - CI-safe with a fake `complete` (no LLM, no
infra). Covers: registry slot, conformance invariants + determinism exemption,
bounding (timeout/garbage -> distinguishable indeterminate, never a write), and the
read-only no-mutation boundary of the tool.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cogniflow.conformance import run_policy_conformance
from cogniflow.core.types import Belief
from cogniflow.registry import available_policies, create_policy
from cogniflow.verification import LLMFalsificationPolicy


def _w(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _target() -> Belief:
    return Belief(id="boston", statement="HQ Boston", created_at=_w(2019),
                  valid_at=_w(2019), invalid_at=_w(2022))


def _denver() -> Belief:
    return Belief(id="denver", statement="HQ Denver", created_at=_w(2022), valid_at=_w(2022))


def test_llm_policy_is_registered() -> None:
    assert "llm" in available_policies("falsification")
    assert isinstance(create_policy("falsification", "llm"), LLMFalsificationPolicy)


def test_detects_contradiction_from_clean_json() -> None:
    def complete(_prompt: str) -> str:
        return '{"superseded": true, "superseded_by": "denver", "rationale": "moved"}'

    verdict = LLMFalsificationPolicy(complete).assess(_target(), [_target(), _denver()])
    assert verdict.superseded is True
    assert verdict.superseded_by == "denver"
    assert verdict.invalid_at == _w(2022) # taken from the matched candidate
    assert verdict.indeterminate is False


def test_clean_non_contradiction() -> None:
    def complete(_prompt: str) -> str:
        return 'noise {"superseded": false, "rationale": "consistent"} trailing'

    verdict = LLMFalsificationPolicy(complete).assess(_target(), [_denver()])
    assert verdict.superseded is False
    assert verdict.indeterminate is False


def test_timeout_or_error_degrades_to_indeterminate_never_raises() -> None:
    def boom(_prompt: str) -> str:
        raise TimeoutError("llm timed out")

    verdict = LLMFalsificationPolicy(boom).assess(_target(), [_denver()])
    assert verdict.indeterminate is True
    assert verdict.superseded is False # bounded fallback, NOT a confident clean


def test_unparseable_response_is_indeterminate() -> None:
    def garbage(_prompt: str) -> str:
        return "I think maybe it changed but I am not sure"

    verdict = LLMFalsificationPolicy(garbage).assess(_target(), [_denver()])
    assert verdict.indeterminate is True


def test_no_llm_configured_is_indeterminate() -> None:
    verdict = LLMFalsificationPolicy(complete=None).assess(_target(), [_denver()])
    assert verdict.indeterminate is True


def test_passes_conformance_invariants_and_does_not_mutate() -> None:
    policy = LLMFalsificationPolicy(lambda _p: '{"superseded": false, "rationale": "ok"}')
    results = run_policy_conformance("falsification", policy)
    assert all(r.passed for r in results), [r for r in results if not r.passed]


# --- tool no-mutation boundary (needs llama-index, no LLM/DB) -----------------

llama = pytest.importorskip("llama_index.core") # noqa: F841


def test_verify_fact_tool_is_read_only() -> None:
    import asyncio

    from cogniflow.bridges.llamaindex import make_verify_fact_tool
    from cogniflow.core.types import RetrievalQuery, RetrievalResult, ScoredBelief

    class _ReadOnlyTrackingBackend:
        def __init__(self) -> None:
            self.writes = 0

        async def read(self, query: RetrievalQuery) -> RetrievalResult:
            return RetrievalResult(
                query=query, results=(ScoredBelief(belief=_denver()),), as_of=query.as_of
            )

        async def write(self, episode): # must never be called by verify
            self.writes += 1
            raise AssertionError("verify_fact must not write")

        async def falsify(self, target, against=None): # pragma: no cover
            raise NotImplementedError

    backend = _ReadOnlyTrackingBackend()
    policy = LLMFalsificationPolicy(lambda _p: '{"superseded": true, "superseded_by": "denver"}')
    tool = make_verify_fact_tool(backend, policy)

    async def run() -> str:
        out = await tool.acall(statement="Acme is in Boston", valid_at="2019")
        return str(out)

    text = asyncio.run(run())
    assert "contradicted" in text
    assert backend.writes == 0 # read-only advisory: no mutation
