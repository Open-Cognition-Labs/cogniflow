"""F3: the labeled corpus is well-formed, and the F2 faithfulness checker is MEASURED on it.

The headline for a faithfulness checker is hallucination detection: recall on unsupported
claims (a hallucination that PASSES is the dangerous error), precision on the flags it raises
(false flags erode trust). Measured, printed, and bounded from the measurement - the same
discipline as verify_fact. Pure: no infra, no model.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from cogniflow.context import ServedFact
from cogniflow.eval_corpus import FAITHFULNESS_CASES, verify_cases
from cogniflow.faithfulness import LexicalChecker


def _fact(i: int, statement: str) -> ServedFact:
    return ServedFact(
        belief_id=f"f{i}", statement=statement,
        valid_at=datetime(2015, 1, 1, tzinfo=timezone.utc), invalid_at=None,
        valid_at_source="provided", valid_at_source_raw="provided",
        provenance=(f"doc{i}",), superseded_by=None, score=0.9,
    )


# ---- corpus shape guards --------------------------------------------------------------------
def test_verify_corpus_is_grown_and_balanced() -> None:
    cases = verify_cases()
    assert len(cases) >= 50 # the n=8 coin-flip era is over
    pos = sum(1 for c in cases if c.expected_superseded)
    neg = len(cases) - pos
    assert min(pos, neg) / len(cases) >= 0.4 # balanced within 40/60
    # fictional-universe rule: dates in metadata, never in fact text
    for c in cases:
        for b in (c.target, *c.candidates):
            assert not any(ch.isdigit() and len(tok) == 4 for tok in b.statement.split()
                           for ch in tok[:1]), b.statement
    # ids unique
    ids = [b.id for c in cases for b in (c.target, *c.candidates)]
    assert len(ids) == len(set(ids))


def test_faithfulness_corpus_is_balanced() -> None:
    labels = [expected for _, _, expected in FAITHFULNESS_CASES]
    assert len(labels) >= 20
    assert 0.3 <= sum(labels) / len(labels) <= 0.7


# ---- the checker measurement ---------------------------------------------------------
def test_lexical_checker_measured_on_labeled_corpus() -> None:
    checker = LexicalChecker()
    tp = fp = fn = tn = 0 # positive class = UNSUPPORTED (hallucination detected)
    misses: list[str] = []
    for facts_text, claim, expected_supported in FAITHFULNESS_CASES:
        facts = [_fact(i, s) for i, s in enumerate(facts_text)]
        report = asyncio.run(checker.check(claim, facts, known={"2015"}))
        assert report.claims, claim
        predicted_supported = report.claims[0].status == "supported"
        if not expected_supported and not predicted_supported:
            tp += 1
        elif not expected_supported and predicted_supported:
            fn += 1
            misses.append(f"PASSED-HALLUCINATION: {claim}")
        elif expected_supported and not predicted_supported:
            fp += 1
            misses.append(f"FALSE-FLAG: {claim}")
        else:
            tn += 1
    total = len(FAITHFULNESS_CASES)
    det_recall = tp / (tp + fn) if (tp + fn) else 1.0
    det_precision = tp / (tp + fp) if (tp + fp) else 1.0
    print(
        f"faithfulness(lexical) on n={total}: hallucination-detection "
        f"recall={det_recall:.2f} precision={det_precision:.2f} "
        f"(tp={tp} fp={fp} fn={fn} tn={tn})"
    )
    for m in misses:
        print(" ", m)
    # Bounds set FROM the measurement (not the other way around). A hallucination that passes
    # is the audit-dangerous error: recall is the headline and must stay at 1.0 on this set.
    assert det_recall >= 0.99, misses
    assert det_precision >= 0.85, misses
