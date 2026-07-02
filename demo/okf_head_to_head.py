"""module head-to-head: OKF in -> temporally-correct answer out, vs plain RAG.

Same OKF bundle (a concept redefined v1->v2), same LLM, same pipeline shape. The ONLY
difference is the memory layer:
 - Plain RAG indexes the accumulated concept files (both the March and June definitions)
    and retrieves by similarity - it has no way to mark which is current, so it surfaces
    the stale/ambiguous definition.
 - Cogniflow ingests v1 then v2; ingestion supersedes the old definition. It answers the
    current one for "now" and replays the old one for as_of=March.

The win is temporal correctness (currency + as-of replay), NOT recall.

Prereqs: FalkorDB running, a .env with COGNIFLOW_LLM_*, `pip install -e ".[all,okf]"`.
Run: PYTHONPATH=src python demo/okf_head_to_head.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from llama_index.core import Document, VectorStoreIndex  # noqa: E402
from nvidia_embeddings import NvidiaEmbedding  # noqa: E402

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.bridges.llamaindex import make_llm  # noqa: E402
from cogniflow.okf import ingest_bundle, parse_bundle  # noqa: E402
from cogniflow.pipelines import temporal_rag_answer  # noqa: E402

BUNDLE = pathlib.Path(__file__).parent / "okf_demo_bundle"
QUESTION = "How is Weekly Active Users currently defined? State the trailing-window length."


def run_plain_rag(cfg: GraphitiFalkorDBConfig) -> tuple[str, list[str]]:
    embed = NvidiaEmbedding(cfg.llm_api_key, cfg.llm_base_url)
    docs = []
    for version in ("v1", "v2"): # the accumulated corpus: both definitions coexist
        for c in parse_bundle(BUNDLE / version):
            docs.append(Document(text=f"{c.frontmatter.get('title', c.concept_id)}\n\n{c.body}"))
    index = VectorStoreIndex.from_documents(docs, embed_model=embed)
    engine = index.as_query_engine(llm=make_llm(cfg), embed_model=embed, similarity_top_k=2)
    resp = engine.query(QUESTION)
    return str(resp).strip(), [n.node.get_content().strip()[:80] for n in resp.source_nodes]


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
        await ingest_bundle(backend, BUNDLE / "v1") # March: 7-day
        await ingest_bundle(backend, BUNDLE / "v2") # June: 28-day (supersedes)

        async def gen(prompt: str) -> str:
            return str(await llm.acomplete(prompt))

        now = await temporal_rag_answer(backend, QUESTION, gen)
        march = await temporal_rag_answer(
            backend, QUESTION, gen, as_of=datetime(2026, 3, 15, tzinfo=timezone.utc)
        )
        return {"now": now, "march": march}
    finally:
        await backend.close()


def main() -> None:
    cfg = GraphitiFalkorDBConfig.from_env(group_id="okf_head_to_head")
    print("=" * 80)
    print(f"QUESTION: {QUESTION}")
    print(f"BUNDLE: {BUNDLE.name} (v1 March=7-day -> v2 June=28-day)")
    print("=" * 80)

    rag_answer, rag_src = run_plain_rag(cfg)
    cf = asyncio.run(run_cogniflow(cfg))

    print("\n--- PLAIN RAG (vector over accumulated v1+v2 files, top-2) ---")
    for s in rag_src:
        print(f" retrieved: {s!r}")
    print(f" ANSWER: {rag_answer}")
    print(f" VERDICT: {'STALE/AMBIGUOUS (surfaces 7-day)' if '7' in rag_answer else 'check'}")

    print("\n--- COGNIFLOW-RAG (temporal, as_of = now) ---")
    print(f" facts: {cf['now'].facts}")
    print(f" ANSWER: {cf['now'].answer}")
    print(f" VERDICT: {'CURRENT (28-day)' if '28' in cf['now'].answer else 'check'}")

    print("\n--- COGNIFLOW-RAG (temporal, as_of = March 2026 = replay) ---")
    print(f" facts: {cf['march'].facts}")
    print(f" ANSWER: {cf['march'].answer}")
    print(f" VERDICT: {'REPLAYED OLD (7-day)' if '7' in cf['march'].answer else 'check'}")
    print("=" * 80)


if __name__ == "__main__":
    main()
