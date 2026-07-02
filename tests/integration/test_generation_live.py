"""Generation layer - live centerpiece (acceptance #2): temporal correctness survives
generation. Tesla HQ moved Palo Alto -> Austin (2021); the generation model's TRAINING knows
Austin. Asked "as of 2018", the answer must be Palo Alto (from the as-of context), not Austin
(from training). Also checks faithfulness (no invention). Live FalkorDB + LLM; skipped without.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.core.types import Episode  # noqa: E402
from cogniflow.generation import generate_answer  # noqa: E402
from cogniflow.generators import create_generator_from_env  # noqa: E402

UTC = timezone.utc


def _dt(y: int) -> datetime:
    return datetime(y, 1, 1, tzinfo=UTC)


def _falkordb_up() -> bool:
    try:
        from falkordb import FalkorDB

        FalkorDB(host="localhost", port=6379).select_graph("__ping__").query("RETURN 1")
        return True
    except Exception:
        return False


requires_stack = pytest.mark.skipif(
    not (_falkordb_up() and os.getenv("COGNIFLOW_LLM_API_KEY")),
    reason="requires FalkorDB and COGNIFLOW_LLM_API_KEY",
)


def _hq_episode(eid: str, city: str, year: int) -> Episode:
    # deterministic structured fact (OKF-style triple) so setup does not depend on extraction
    return Episode(
        id=eid,
        content=f"Tesla is headquartered in {city}.",
        reference_time=_dt(year),
        source="okf",
        metadata={
            "triple": {
                "source": "Tesla",
                "predicate": "HEADQUARTERED_IN",
                "target": city,
                "fact": f"Tesla is headquartered in {city}",
            },
            "valid_at_source": "okf:timestamp",
        },
    )


@pytest.mark.integration
@requires_stack
def test_temporal_correctness_survives_generation() -> None:
    async def run() -> None:
        from falkordb import FalkorDB

        group = "it_gen_tesla"
        try:
            FalkorDB(host="localhost", port=6379).select_graph(group).delete()
        except Exception:
            pass
        backend = GraphitiFalkorDBBackend(GraphitiFalkorDBConfig.from_env(group_id=group))
        await backend.setup()
        gen = create_generator_from_env()
        try:
            await backend.write(_hq_episode("tesla_2010", "Palo Alto", 2010))
            await backend.write(_hq_episode("tesla_2021", "Austin", 2021)) # supersedes

            q = "Where is Tesla headquartered?"
            past = await generate_answer(backend, q, gen, as_of=_dt(2018))
            now = await generate_answer(backend, q, gen, as_of=_dt(2023))

            # THE centerpiece: as-of 2018 answers Palo Alto (context), NOT Austin (training)
            assert "Palo Alto" in past.answer, past.answer
            assert "Austin" not in past.answer, past.answer
            assert "Austin" in now.answer, now.answer # present -> the current fact

            # provenance + confidence carried into the answer (T3/T4)
            assert past.facts and past.facts[0].provenance
            assert past.confidence # a valid_at_source histogram, non-empty

            # faithfulness (T5): a question the context cannot answer -> decline, don't invent
            unanswerable = await generate_answer(
                backend, "What was Tesla's annual revenue?", gen, as_of=_dt(2023)
            )
            ans = unanswerable.answer.lower()
            assert any(
                w in ans for w in ("do not", "don't", "no information", "not have", "cannot",
                                   "does not", "unable", "no ")
            ), unanswerable.answer
        finally:
            await backend.close()

    asyncio.run(run())
