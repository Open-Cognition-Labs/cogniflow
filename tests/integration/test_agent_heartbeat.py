"""milestone acceptance #1 - THE heartbeat through the agent path.

The first temporal eval scenario: one question, two as_of points, expected answers.
Asked of a LlamaIndex ReActAgent whose only tool is the TemporalGraphRetriever (seam a)
with the TemporalValidityPostprocessor (seam b). Skipped when FalkorDB / LLM / llama-index
are absent (e.g. CI).

This SCENARIO dict is the seed of the eval harness: later phases reuse the same
shape (question + as_of points + expected) as the gate every stage must pass.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")
pytest.importorskip("llama_index.core")

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.bridges.llamaindex import build_temporal_agent, make_llm  # noqa: E402
from cogniflow.core.types import Episode  # noqa: E402

HOST = os.getenv("COGNIFLOW_FALKORDB_HOST", "localhost")
PORT = int(os.getenv("COGNIFLOW_FALKORDB_PORT", "6379"))


def _falkordb_up() -> bool:
    try:
        from falkordb import FalkorDB

        FalkorDB(host=HOST, port=PORT).select_graph("__ping__").query("RETURN 1")
        return True
    except Exception:
        return False


requires_stack = pytest.mark.skipif(
    not (_falkordb_up() and os.getenv("COGNIFLOW_LLM_API_KEY")),
    reason="requires a running FalkorDB and COGNIFLOW_LLM_API_KEY",
)

# The eval scenario (harness seed).
SCENARIO = {
    "question": "Where is Acme Corp headquartered?",
    "facts": [
        ("Acme Corp", "HEADQUARTERED_IN", "Boston", "Acme Corp is headquartered in Boston", 2019),
        ("Acme Corp", "HEADQUARTERED_IN", "Denver", "Acme Corp is headquartered in Denver", 2022),
    ],
    "expected": {2020: "Boston", 2023: "Denver"},
}


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


@pytest.mark.integration
@requires_stack
def test_agent_heartbeat_as_of() -> None:
    async def run() -> None:
        group = "it_agent_hb"
        try:
            from falkordb import FalkorDB

            FalkorDB(host=HOST, port=PORT).select_graph(group).delete()
        except Exception:
            pass
        cfg = GraphitiFalkorDBConfig.from_env(group_id=group)
        backend = GraphitiFalkorDBBackend(cfg)
        await backend.setup()
        try:
            for i, (src, pred, tgt, fact, year) in enumerate(SCENARIO["facts"]):
                triple = {"source": src, "predicate": pred, "target": tgt, "fact": fact}
                await backend.write(
                    Episode(
                        id=f"ep{i}",
                        content=fact,
                        reference_time=_dt(year),
                        source="text",
                        metadata={"triple": triple},
                    )
                )

            llm = make_llm(cfg)
            for year, expected in SCENARIO["expected"].items():
                agent = build_temporal_agent(backend, as_of=_dt(year), llm=llm, top_k=5)
                response = await agent.run(user_msg=SCENARIO["question"])
                answer = str(response)
                assert expected in answer, f"as_of {year}: expected {expected!r} in {answer!r}"
                # the superseded city must NOT leak at this as_of
                other = "Denver" if expected == "Boston" else "Boston"
                assert other not in answer, f"as_of {year}: {other!r} leaked into {answer!r}"
        finally:
            await backend.close()

    asyncio.run(run())
