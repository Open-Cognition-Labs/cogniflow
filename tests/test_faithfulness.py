"""F2 faithfulness: the answer is CHECKED against the served facts, post-hoc.

The centerpiece assertions:
  1. a planted hallucination (a claim not in the served facts) is caught and flagged;
  2. a fully-grounded answer passes clean;
  3. the as-of leak trap - an answer that leaks training knowledge past the as-of context
     (Austin against a served Palo-Alto fact) - is caught as unsupported, so the faithfulness
     check now also guards the temporal constraint MECHANICALLY, not by prompt trust.
Plus: fail-loud plug, visibly-off 'off', flag-vs-strict modes, and the response contract.
All pure - no infra, no model.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from cogniflow.context import ServedFact
from cogniflow.core.types import (
    Belief,
    FalsificationVerdict,
    RetrievalQuery,
    RetrievalResult,
    ScoredBelief,
)
from cogniflow.faithfulness import (
    FaithfulnessError,
    LexicalChecker,
    available_checkers,
    create_checker,
    decompose,
)
from cogniflow.generation import generate_answer


def _dt(y: int) -> datetime:
    return datetime(y, 1, 1, tzinfo=timezone.utc)


def _fact(bid: str, statement: str, year: int = 2010) -> ServedFact:
    return ServedFact(
        belief_id=bid, statement=statement, valid_at=_dt(year), invalid_at=None,
        valid_at_source="provided", valid_at_source_raw="provided",
        provenance=(f"{bid}-src",), superseded_by=None, score=0.9,
    )


PALO_ALTO = [_fact("hq1", "Tesla is headquartered in Palo Alto")]


def _check(answer: str, facts=None):
    return asyncio.run(LexicalChecker().check(answer, facts if facts is not None else PALO_ALTO))


# ---- decomposition --------------------------------------------------------------------------
def test_decompose_splits_and_strips_citations() -> None:
    answer = (
        "According to the context facts, Tesla is headquartered in Palo Alto "
        "[valid_from: 2010-01-01; confidence: provided].\n"
        "Source: annual_report_2010#chunk0"
    )
    claims = decompose(answer)
    assert len(claims) == 1 # the source-only line is dropped; the citation tail stripped
    assert "Palo Alto" in claims[0] and "[" not in claims[0]


# ---- the centerpiece ------------------------------------------------------------------------
def test_grounded_answer_passes_clean() -> None:
    r = _check("According to the context facts, Tesla is headquartered in Palo Alto.")
    assert r.status == "grounded" and r.unsupported_claims == []
    assert r.claims[0].best_fact == "hq1"


def test_planted_hallucination_is_caught() -> None:
    r = _check(
        "Tesla is headquartered in Palo Alto. "
        "Tesla also employs five thousand robotics engineers in Berlin."
    )
    assert r.status == "unsupported_claims"
    assert any("Berlin" in c for c in r.unsupported_claims) # the planted claim, flagged
    assert not any("Palo Alto" in c for c in r.unsupported_claims) # the grounded one, not


def test_as_of_leak_is_caught_mechanically() -> None:
    # The temporal trap: the served (as-of) fact says Palo Alto; the model leaks its training
    # knowledge and answers Austin. The checker must flag it - the un-knowing invariant now
    # guarded at the generation edge by measurement, not trust.
    r = _check("Tesla is headquartered in Austin.")
    assert r.status == "unsupported_claims"
    assert "Austin" in r.unsupported_claims[0]


def test_refusal_is_no_checkable_claims_not_a_pass() -> None:
    r = _check("I do not have that information in the context facts.")
    assert r.status == "no_checkable_claims" # honest: not 'grounded'


# ---- the fail-loud plug ---------------------------------------------------------------------
def test_unknown_checker_fails_loud() -> None:
    with pytest.raises(FaithfulnessError):
        create_checker("made-up-checker")
    with pytest.raises(FaithfulnessError):
        create_checker("llm-judge") # no generator -> raise, never a silent no-op
    assert available_checkers() == ["lexical", "llm-judge", "off"]


def test_off_is_visibly_off() -> None:
    r = asyncio.run(create_checker("off").check("anything", PALO_ALTO))
    assert r.status == "unchecked" # off never looks like grounded


def test_llm_judge_parses_verdicts() -> None:
    def judge(prompt: str) -> str:
        return "1: SUPPORTED\n2: UNSUPPORTED"

    checker = create_checker("llm-judge", generator=judge)
    r = asyncio.run(checker.check(
        "Tesla is headquartered in Palo Alto. Tesla sells sandwiches.", PALO_ALTO
    ))
    assert r.status == "unsupported_claims"
    assert [c.status for c in r.claims] == ["supported", "unsupported"]


# ---- generation wiring (flag + strict + contract) --------------------------------------------
class _FakeSubstrate:
    async def read(self, query: RetrievalQuery) -> RetrievalResult:
        b = Belief(
            id="hq1", statement="Tesla is headquartered in Palo Alto",
            created_at=_dt(2010), valid_at=_dt(2010),
            provenance=("annual_report_2010#chunk0",),
            metadata={"valid_at_source": "provided"},
        )
        return RetrievalResult(
            query=query, results=(ScoredBelief(belief=b, score=0.9),), as_of=query.as_of
        )

    async def write(self, episode): # pragma: no cover
        raise NotImplementedError

    async def falsify(self, target, against=None) -> FalsificationVerdict: # pragma: no cover
        return FalsificationVerdict(target_id=str(target), superseded=False)


def _leaky_generator(prompt: str) -> str:
    return "Tesla is headquartered in Austin." # ignores the served context (training leak)


def test_generate_answer_flags_but_ships_by_default() -> None:
    res = asyncio.run(generate_answer(_FakeSubstrate(), "Where is Tesla HQ?", _leaky_generator))
    assert res.answer == "Tesla is headquartered in Austin." # flag mode: untouched...
    assert res.faithfulness is not None
    assert res.faithfulness.status == "unsupported_claims" # ...but loudly flagged
    d = res.to_dict()
    assert d["faithfulness"]["unsupported_claims"] # the response contract carries it


def test_generate_answer_strict_declines() -> None:
    res = asyncio.run(generate_answer(
        _FakeSubstrate(), "Where is Tesla HQ?", _leaky_generator, faithfulness_mode="strict"
    ))
    assert "Austin" not in res.answer # never silently shipped
    assert "cannot provide" in res.answer.lower()
    assert res.faithfulness.status == "unsupported_claims" # the report says exactly why


def test_generate_answer_bad_mode_fails_loud() -> None:
    with pytest.raises(ValueError):
        asyncio.run(generate_answer(
            _FakeSubstrate(), "q", _leaky_generator, faithfulness_mode="silently-fix"
        ))
