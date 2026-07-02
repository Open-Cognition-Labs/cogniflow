"""Generation layer (closing the RAG loop) - CI-safe, no network. Covers the generator plug
(fail-loud), the constrained prompt (temporal-correctness + faithfulness instructions),
confidence + provenance carried into the answer, and both serving surfaces.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from cogniflow.core.types import (
    Belief,
    FalsificationVerdict,
    RetrievalQuery,
    RetrievalResult,
    ScoredBelief,
)
from cogniflow.generation import build_prompt, generate_answer
from cogniflow.generators import GeneratorError, create_generator


def _dt(y: int) -> datetime:
    return datetime(y, 1, 1, tzinfo=timezone.utc)


class _FakeSubstrate:
    """Serves Palo Alto for a past as_of, Austin for the present (as-of filtered)."""

    async def read(self, query: RetrievalQuery) -> RetrievalResult:
        if query.as_of is not None and query.as_of < _dt(2021):
            b = Belief(
                id="hq1", statement="Tesla is headquartered in Palo Alto",
                created_at=_dt(2010), valid_at=_dt(2010),
                provenance=("annual_report_2010#chunk0",),
                metadata={"valid_at_source": "document:mtime"},
            )
        else:
            b = Belief(
                id="hq2", statement="Tesla is headquartered in Austin",
                created_at=_dt(2021), valid_at=_dt(2021),
                provenance=("annual_report_2021#chunk0",),
                metadata={"valid_at_source": "provided"},
            )
        return RetrievalResult(
            query=query, results=(ScoredBelief(belief=b, score=0.9),), as_of=query.as_of
        )

    async def write(self, episode): # pragma: no cover
        raise NotImplementedError

    async def falsify(self, target, against=None) -> FalsificationVerdict: # pragma: no cover
        return FalsificationVerdict(target_id=str(target), superseded=False)


class _FakeGenerator:
    """A constrained model: answers only from the context lines it is given."""

    model = "fake-model"

    def __init__(self) -> None:
        self.last_prompt: str | None = None

    async def __call__(self, prompt: str) -> str:
        self.last_prompt = prompt
        for line in prompt.splitlines():
            if line.startswith("- ") and "[valid_from:" in line: # a fact line, not a rule
                return line[2:].split(" [")[0]
        return "I do not have that information."


# ---- generator plug (G1 / acceptance #6) -----------------------------------------------

def test_generator_plug_selects_by_name_and_carries_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COGNIFLOW_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("COGNIFLOW_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    g = create_generator("nvidia", api_key="x")
    assert g.model == "minimaxai/minimax-m3" # config-selected, model carried


def test_generator_plug_fail_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COGNIFLOW_GENERATOR_API_KEY", raising=False)
    monkeypatch.delenv("COGNIFLOW_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(GeneratorError):
        create_generator("nvidia") # no key -> raise, never a silent no-op
    with pytest.raises(GeneratorError):
        create_generator("does-not-exist", api_key="x") # unknown name -> raise


# ---- the constrained prompt (T2 plumbing + faithfulness T5) -----------------------------

def test_prompt_constrains_to_context_and_ignores_training() -> None:
    gen = _FakeGenerator()
    res = asyncio.run(generate_answer(_FakeSubstrate(), "Where is Tesla HQ?", gen, as_of=_dt(2018)))
    p = gen.last_prompt
    assert "Do NOT use your own" in p and "TRUST THE CONTEXT" in p # temporal-correctness rule
    assert "do not have that information" in p.lower() # faithfulness rule
    assert "Palo Alto" in p and "Austin" not in p # only the as-of context is in the prompt
    assert "Palo Alto" in res.answer # answered from context (not present-day training)


# ---- confidence (T3) + provenance (T4) carried into the answer --------------------------

def test_answer_carries_confidence_and_provenance() -> None:
    res = asyncio.run(
        generate_answer(_FakeSubstrate(), "Where is Tesla HQ?", _FakeGenerator(), as_of=_dt(2018))
    )
    assert res.confidence == {"derived": 1} # B: extraction floor not laundered
    assert res.generator_model == "fake-model"
    d = res.to_dict()
    assert d["confidence"] == {"derived": 1}
    assert d["facts"][0]["provenance"] == ["annual_report_2010#chunk0"] # audit-traceable
    assert d["facts"][0]["valid_at_source"] == "derived"


def test_build_prompt_handles_empty_context() -> None:
    from cogniflow.context import ContextResponse

    p = build_prompt("anything", ContextResponse(query="anything", as_of=None))
    assert "no facts available" in p.lower()


# ---- both surfaces (T5 / acceptance #5) -------------------------------------------------

def test_http_answer_surface_present_only_with_generator() -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from cogniflow.serving import create_app

    # without a generator, /answer is not mounted (context-only surface survives)
    ctx_only = TestClient(create_app(_FakeSubstrate()))
    assert ctx_only.post("/answer", json={"query": "x"}).status_code == 404
    assert ctx_only.get("/healthz").json()["generation"] == "off"

    # with a generator, /answer returns a cited answer
    both = TestClient(create_app(_FakeSubstrate(), _FakeGenerator()))
    r = both.post(
        "/answer", json={"query": "Where is Tesla HQ?", "as_of": "2018-01-01T00:00:00+00:00"}
    )
    assert r.status_code == 200
    body = r.json()
    assert "Palo Alto" in body["answer"]
    assert body["confidence"] == {"derived": 1}
    assert body["facts"][0]["provenance"] == ["annual_report_2010#chunk0"]


def test_mcp_get_answer_tool_present_only_with_generator() -> None:
    pytest.importorskip("mcp")
    from cogniflow.serving import build_mcp_server

    ctx_only = build_mcp_server(_FakeSubstrate())
    names = {t.name for t in asyncio.run(ctx_only.list_tools())}
    assert names == {"get_context"}

    both = build_mcp_server(_FakeSubstrate(), _FakeGenerator())
    names2 = {t.name for t in asyncio.run(both.list_tools())}
    assert names2 == {"get_context", "get_answer"}
