"""Live head-to-head: plain RAG vs Cogniflow on the SAME corpus, SAME question, SAME LLM.

Only the retrieval differs:
 - Plain RAG: a real vector index (NVIDIA embeddings) + top-k similarity. It has no
    recency/supersession model, so it returns the abundant, similar-but-stale answer.
 - Cogniflow: temporal substrate. It knows the old fact was superseded and returns the
    current one - and, asked as-of an earlier date, correctly returns the old one.

Edit demo/corpus.py and re-run; the contrast reproduces on your data.

Prereqs: FalkorDB running (docker run -p 6379:6379 falkordb/falkordb), a .env with
COGNIFLOW_LLM_*, and `pip install -e ".[all]"`.
Run: PYTHONPATH=src python demo/head_to_head.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from corpus import CORPUS, QUESTION  # noqa: E402
from llama_index.core import Document, VectorStoreIndex  # noqa: E402
from nvidia_embeddings import NvidiaEmbedding  # noqa: E402

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.bridges.llamaindex import make_llm  # noqa: E402
from cogniflow.core.types import Episode, RetrievalQuery  # noqa: E402

TOP_K = 3


def _dt(year: int) -> datetime:
    return datetime(year, 1, 1, tzinfo=timezone.utc)


def run_plain_rag(cfg: GraphitiFalkorDBConfig) -> tuple[str, list[str]]:
    embed = NvidiaEmbedding(cfg.llm_api_key, cfg.llm_base_url)
    index = VectorStoreIndex.from_documents(
        [Document(text=e["text"]) for e in CORPUS], embed_model=embed
    )
    engine = index.as_query_engine(llm=make_llm(cfg), embed_model=embed, similarity_top_k=TOP_K)
    response = engine.query(QUESTION)
    retrieved = [n.node.get_content().strip() for n in response.source_nodes]
    return str(response).strip(), retrieved


async def run_cogniflow(cfg: GraphitiFalkorDBConfig) -> dict:
    from falkordb import FalkorDB

    try:
        FalkorDB(host=cfg.host, port=cfg.port).select_graph(cfg.group_id).delete()
    except Exception:
        pass
    backend = GraphitiFalkorDBBackend(cfg)
    await backend.setup()
    llm = make_llm(cfg)
    try:
        for i, entry in enumerate(e for e in CORPUS if "fact" in e):
            f = entry["fact"]
            await backend.write(
                Episode(
                    id=f"c{i}",
                    content=entry["text"],
                    reference_time=_dt(entry["year"]),
                    source="text",
                    metadata={"triple": {"source": f["subject"], "predicate": f["predicate"],
                                         "target": f["object"], "fact": entry["text"]}},
                )
            )

        async def answer(as_of: datetime) -> tuple[str, list[str]]:
            res = await backend.read(RetrievalQuery(text=QUESTION, as_of=as_of, top_k=5))
            ctx = "; ".join(s.belief.statement for s in res.results) or "(no valid fact)"
            out = await llm.acomplete(
                f"Context: {ctx}\nQuestion: {QUESTION}\n"
                "Answer in one short sentence using only the context."
            )
            return str(out).strip(), [s.belief.statement for s in res.results]

        now_ans, now_ctx = await answer(datetime.now(timezone.utc))
        past_ans, past_ctx = await answer(_dt(2016))
        return {"now": (now_ans, now_ctx), "past": (past_ans, past_ctx)}
    finally:
        await backend.close()


def _verdict(answer: str, current: str, stale: str) -> str:
    a = answer.lower()
    if current.lower() in a and stale.lower() not in a:
        return "CURRENT (correct)"
    if stale.lower() in a:
        return "STALE (wrong)"
    return "unclear"


def main() -> None:
    cfg = GraphitiFalkorDBConfig.from_env(group_id="head_to_head_demo")
    print("=" * 78)
    print(f"QUESTION: {QUESTION}")
    print(f"CORPUS: {len(CORPUS)} documents (edit demo/corpus.py to swap)")
    print("=" * 78)

    rag_answer, rag_retrieved = run_plain_rag(cfg)
    cf = asyncio.run(run_cogniflow(cfg))

    print(f"\n--- PLAIN RAG (vector similarity, top-{TOP_K}) ---")
    for r in rag_retrieved:
        print(f" retrieved: {r}")
    print(f" ANSWER: {rag_answer}")
    print(f" VERDICT: {_verdict(rag_answer, 'Denver', 'Boston')}")

    now_ans, now_ctx = cf["now"]
    past_ans, past_ctx = cf["past"]
    print("\n--- COGNIFLOW (temporal, as_of = now) ---")
    print(f" retrieved: {now_ctx}")
    print(f" ANSWER: {now_ans}")
    print(f" VERDICT: {_verdict(now_ans, 'Denver', 'Boston')}")

    print("\n--- COGNIFLOW (temporal, as_of = 2016, proving it is not just always-new) ---")
    print(f" retrieved: {past_ctx}")
    print(f" ANSWER: {past_ans}")
    print(f" VERDICT: {_verdict(past_ans, 'Boston', 'Denver')}")
    print("=" * 78)


if __name__ == "__main__":
    main()
