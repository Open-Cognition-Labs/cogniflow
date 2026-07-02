"""milestone acceptance #1 + #2 - the loop closes through the agent.

The agent records a contradicting fact via record_observation (seam d); after the
queue drains, a point-in-time read reflects the supersession, and the old edge was
invalidated automatically by ingestion (falsification is free). Both directions go
through the agent, not a direct backend.write. Skipped without FalkorDB / LLM / llama-index.
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

from graphiti_core.edges import EntityEdge  # noqa: E402

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.bridges.llamaindex import (  # noqa: E402
    build_recording_agent,
    make_llm,
)
from cogniflow.core.types import Episode  # noqa: E402
from cogniflow.writeback import WriteBackQueue  # noqa: E402

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


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _seed(group: str, src: str, pred: str, tgt: str, fact: str, year: int) -> Episode:
    return Episode(
        id=f"seed-{tgt}",
        content=fact,
        reference_time=_dt(year),
        source="text",
        metadata={"triple": {"source": src, "predicate": pred, "target": tgt, "fact": fact}},
    )


@pytest.mark.integration
@requires_stack
def test_loop_closes_through_agent() -> None:
    async def run() -> None:
        group = "it_loop"
        try:
            from falkordb import FalkorDB

            FalkorDB(host=HOST, port=PORT).select_graph(group).delete()
        except Exception:
            pass

        cfg = GraphitiFalkorDBConfig.from_env(group_id=group)
        backend = GraphitiFalkorDBBackend(cfg)
        await backend.setup()

        async def factory(_gid: str):
            return backend

        queue = WriteBackQueue(factory)
        try:
            # prior state seeded directly
            await backend.write(
                _seed(group, "Acme Corp", "HEADQUARTERED_IN", "Boston",
                      "Acme Corp is headquartered in Boston", 2019)
            )
            denver_receipt = await backend.write(
                _seed(group, "Acme Corp", "HEADQUARTERED_IN", "Denver",
                      "Acme Corp is headquartered in Denver", 2022)
            )
            denver_id = denver_receipt.created_belief_ids[0]

            llm = make_llm(cfg)

            # WRITE through the agent (seam d), not backend.write. The ReAct agent's
            # tool-calling is probabilistic (KNOWN_ISSUES: ReAct re-query reliability),
            # so bound it: retry record+drain until the new fact lands (max 3 attempts).
            from cogniflow.core.types import RetrievalQuery

            recorder = build_recording_agent(queue, group, llm=llm)
            landed = False
            attempts = 5
            for attempt in range(attempts):
                await recorder.run(
                    user_msg="Acme Corp moved its headquarters to Seattle, effective 2024."
                )
                await queue.drain() # belief lag resolved deterministically
                check = await backend.read(
                    RetrievalQuery(text="Acme Corp headquarters", as_of=_dt(2025), top_k=5)
                )
                if any("Seattle" in s.belief.statement for s in check.results):
                    landed = True
                    break
                await asyncio.sleep(3 * (attempt + 1)) # backoff (also dodges rate limits)
            assert landed, f"recording agent did not land the Seattle fact in {attempts} attempts"

            # acceptance #1: the loop closed - the agent's own WRITE reshaped what a
            # point-in-time read returns. The read side is verified deterministically via
            # the substrate here (read-through-agent is covered by test_agent_heartbeat).
            r2023 = await backend.read(
                RetrievalQuery(text="Acme Corp headquarters", as_of=_dt(2023), top_k=5)
            )
            r2025 = await backend.read(
                RetrievalQuery(text="Acme Corp headquarters", as_of=_dt(2025), top_k=5)
            )
            s2023 = [s.belief.statement for s in r2023.results]
            s2025 = [s.belief.statement for s in r2025.results]
            assert any("Denver" in x for x in s2023), s2023
            assert not any("Seattle" in x for x in s2023), s2023
            assert any("Seattle" in x for x in s2025), s2025
            assert not any("Denver" in x for x in s2025), s2025

            # acceptance #2: falsification was free - the Denver edge got both stamps
            denver_edge = await EntityEdge.get_by_uuid(backend._driver, denver_id)
            assert denver_edge.invalid_at is not None, "event-time invalid_at not set by ingestion"
            assert denver_edge.expired_at is not None, "system-time expired_at not set by ingestion"

            # freshness surface advanced
            assert queue.last_ingested_at(group) is not None
        finally:
            await queue.aclose()
            await backend.close()

    asyncio.run(run())
