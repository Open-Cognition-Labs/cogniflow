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
from datetime import datetime, timezone

import pytest

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from cogniflow.core.types import Belief  # noqa: E402
from cogniflow.eval import FalsificationCase, score_falsification  # noqa: E402
from cogniflow.verification import LLMFalsificationPolicy, complete_from_env  # noqa: E402

requires_llm = pytest.mark.skipif(
    not os.getenv("COGNIFLOW_LLM_API_KEY"), reason="requires COGNIFLOW_LLM_API_KEY"
)


def _w(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _b(bid: str, statement: str, vy: int, iy: int | None = None) -> Belief:
    return Belief(
        id=bid,
        statement=statement,
        created_at=_w(vy),
        valid_at=_w(vy),
        invalid_at=_w(iy) if iy else None,
    )


CASES = [
    FalsificationCase(
        target=_b("t1", "Acme Corp is headquartered in Boston", 2019, 2022),
        candidates=(_b("c1", "Acme Corp is headquartered in Denver", 2022),),
        expected_superseded=True,
    ),
    FalsificationCase(
        target=_b("t2", "Acme Corp is headquartered in Denver", 2022),
        candidates=(_b("c2", "Acme Corp is headquartered in Seattle", 2024),),
        expected_superseded=True,
    ),
    FalsificationCase(
        target=_b("t3", "Acme Corp is headquartered in Boston", 2019),
        candidates=(_b("c3", "Alice is the CEO of Acme Corp", 2020),),
        expected_superseded=False,
    ),
    FalsificationCase(
        target=_b("t4", "Bob works at Acme Corp", 2021),
        candidates=(_b("c4", "Acme Corp is headquartered in Boston", 2019),),
        expected_superseded=False,
    ),
    FalsificationCase(
        target=_b("t5", "Acme Corp's CEO is Alice", 2019, 2021),
        candidates=(_b("c5", "Acme Corp's CEO is Carol", 2021),),
        expected_superseded=True,
    ),
    FalsificationCase(
        target=_b("t6", "Acme Corp employs 100 people", 2018, 2020),
        candidates=(_b("c6", "Acme Corp employs 250 people", 2020),),
        expected_superseded=True,
    ),
    FalsificationCase(
        target=_b("t7", "Acme Corp is headquartered in Boston", 2019),
        candidates=(_b("c7", "Acme Corp launched a new product", 2020),),
        expected_superseded=False,
    ),
    FalsificationCase(
        target=_b("t8", "Dana is a contractor at Acme", 2022),
        candidates=(_b("c8", "Acme Corp's CEO is Carol", 2021),),
        expected_superseded=False,
    ),
]


@pytest.mark.integration
@requires_llm
def test_verify_fact_reliability_is_measured() -> None:
    policy = LLMFalsificationPolicy(complete_from_env(timeout=40))
    report = score_falsification(policy, CASES)
    print(
        f"verify_fact eval: precision={report.precision:.2f} recall={report.recall:.2f} "
        f"accuracy={report.accuracy:.2f} indeterminate={report.indeterminate}/{report.total}"
    )
    # Recall is the HEADLINE for an audit ledger: a missed contradiction (false "not
    # superseded") is the dangerous error. Bounds are measured over the corpus, not a
    # single happy-path run; grow the corpus over time to tighten them.
    assert report.total >= 8
    assert report.recall >= 0.6, f"recall too low (audit risk): {report}"
    assert report.precision >= 0.5, report
