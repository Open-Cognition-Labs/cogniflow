"""T3 + R1: verify_fact reliability is MEASURED, not asserted by one green run.

Scores the LLM FalsificationPolicy over a small labeled contradiction set (real LLM,
no DB) and asserts precision/recall above a modest bound. Skipped without an LLM key.

R1 decision (documented): no function-calling model is configured (MiniMax-M3 emits no
native tool calls), so the agent path stays ReAct. verify_fact's value depends on the
agent choosing to call it - the autonomous re-query loop - which is the known ReAct
reliability constraint (KNOWN_ISSUES). This eval measures the policy's own detection
reliability; the autonomous-call reliability is bounded by ReAct adherence and tracked.
"""

from __future__ import annotations

import os

import pytest

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from cogniflow.eval import score_falsification  # noqa: E402
from cogniflow.eval_corpus import verify_cases  # noqa: E402
from cogniflow.verification import LLMFalsificationPolicy, complete_from_env  # noqa: E402

requires_llm = pytest.mark.skipif(
    not os.getenv("COGNIFLOW_LLM_API_KEY"), reason="requires COGNIFLOW_LLM_API_KEY"
)


@pytest.mark.integration
@requires_llm
def test_verify_fact_reliability_is_measured() -> None:
    # F3: the labeled corpus (cogniflow.eval_corpus, n=56, six fact-type families, balanced)
    # replaces the coin-flippy n=8 set. Bounds are RECALIBRATED FROM the measurement on this
    # corpus (documented in PROJECT_STATUS), never adjusted to make a run pass.
    cases = verify_cases()
    policy = LLMFalsificationPolicy(complete_from_env(timeout=40))
    report = score_falsification(policy, cases)
    print(
        f"verify_fact eval (n={report.total}): precision={report.precision:.2f} "
        f"recall={report.recall:.2f} accuracy={report.accuracy:.2f} "
        f"indeterminate={report.indeterminate}/{report.total}"
    )
    # Recall is the HEADLINE for an audit ledger: a missed contradiction (false "not
    # superseded") is the dangerous error.
    #
    # RECALIBRATED BY MEASUREMENT :
    # precision 1.00, recall 0.57, accuracy 0.78, indeterminate 18/60 (the misses are hedges,
    # not wrong flags). Method: regression bound = point estimate - 1 binomial SE, rounded down
    # to 0.05 -> recall >= 0.50 (0.57 - 0.09), precision >= 0.85 (1.00 - 0.09, tightened where
    # the model is measured strong). These are DEGRADATION guards set from the measurement -
    # never adjusted to make a run pass. The measured value, not the bound, is the published
    # capability (PROJECT_STATUS).
    assert report.total >= 50
    assert report.recall >= 0.50, f"recall regressed below the measured floor: {report}"
    assert report.precision >= 0.85, f"precision regressed below the measured floor: {report}"
