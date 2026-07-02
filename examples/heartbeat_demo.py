"""The heartbeat demo: ask the same question as-of two different times and get two
different answers, because a fact was superseded in between.

Prerequisites:
 - a running FalkorDB: docker run -d -p 6379:6379 falkordb/falkordb
 - a .env with COGNIFLOW_LLM_API_KEY / COGNIFLOW_LLM_BASE_URL / COGNIFLOW_LLM_MODEL
    (any OpenAI-compatible endpoint)
 - install: pip install -e ".[all]" python-dotenv

Run: python examples/heartbeat_demo.py
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from cogniflow.backends.graphiti_falkordb import GraphitiFalkorDBBackend, GraphitiFalkorDBConfig
from cogniflow.core.types import Episode, RetrievalQuery


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def _triple(ep_id: str, src: str, pred: str, tgt: str, fact: str, year: int) -> Episode:
    return Episode(
        id=ep_id,
        content=fact,
        reference_time=_dt(year),
        source="text",
        metadata={"triple": {"source": src, "predicate": pred, "target": tgt, "fact": fact}},
    )


async def main() -> None:
    backend = GraphitiFalkorDBBackend(GraphitiFalkorDBConfig.from_env(group_id="heartbeat_demo"))
    await backend.setup()
    try:
        await backend.write(
            _triple("ep1", "Acme Corp", "HEADQUARTERED_IN", "Boston",
                    "Acme Corp is headquartered in Boston", 2019)
        )
        await backend.write(
            _triple("ep2", "Acme Corp", "HEADQUARTERED_IN", "Denver",
                    "Acme Corp is headquartered in Denver", 2022)
        )

        question = "Where is Acme Corp headquartered?"
        for year in (2020, 2023):
            result = await backend.read(RetrievalQuery(text=question, as_of=_dt(year), top_k=5))
            answers = [s.belief.statement for s in result.results]
            print(f"as_of {year}: {answers}")
    finally:
        await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
