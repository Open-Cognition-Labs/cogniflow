"""module head-to-head over a real PDF corpus (acceptance #7).

Same RAG-wrong / Cogniflow-right + replay demo as module, now over PDF *documents*
instead of OKF concepts. Two versions of a company report (HQ Boston -> Denver). Same
LLM, same pipeline shape; only the memory layer differs.

Prereqs: FalkorDB running, .env with COGNIFLOW_LLM_*, `pip install -e ".[all,documents]"`.
Run: PYTHONPATH=src python demo/doc_head_to_head.py
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from llama_index.core import Document, VectorStoreIndex  # noqa: E402
from nvidia_embeddings import NvidiaEmbedding  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.bridges.llamaindex import make_llm  # noqa: E402
from cogniflow.documents import ingest_document  # noqa: E402
from cogniflow.pipelines import temporal_rag_answer  # noqa: E402

CORPUS = pathlib.Path(__file__).parent / "doc_demo_corpus"
Q = "Where is Acme Corp headquartered?"


def run_plain_rag(cfg: GraphitiFalkorDBConfig) -> str:
    embed = NvidiaEmbedding(cfg.llm_api_key, cfg.llm_base_url)
    docs = []
    for pdf in sorted(CORPUS.glob("*.pdf")): # accumulated corpus: both report versions
        text = "\n".join(p.extract_text() or "" for p in PdfReader(str(pdf)).pages)
        docs.append(Document(text=text))
    index = VectorStoreIndex.from_documents(docs, embed_model=embed)
    engine = index.as_query_engine(llm=make_llm(cfg), embed_model=embed, similarity_top_k=3)
    return str(engine.query(Q)).strip()


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
        await ingest_document(backend, CORPUS / "acme_report_v1.pdf",
                              reference_time=datetime(2019, 1, 1, tzinfo=timezone.utc))
        await ingest_document(backend, CORPUS / "acme_report_v2.pdf",
                              reference_time=datetime(2022, 1, 1, tzinfo=timezone.utc))

        async def gen(prompt: str) -> str:
            return str(await llm.acomplete(prompt))

        utc = timezone.utc
        now = await temporal_rag_answer(backend, Q, gen, as_of=datetime(2023, 1, 1, tzinfo=utc))
        past = await temporal_rag_answer(backend, Q, gen, as_of=datetime(2020, 1, 1, tzinfo=utc))
        return {"now": now, "past": past}
    finally:
        await backend.close()


def main() -> None:
    cfg = GraphitiFalkorDBConfig.from_env(group_id="doc_head_to_head")
    print("=" * 80)
    print(f"QUESTION: {Q}")
    print("CORPUS: PDF reports (v1 2019 = Boston -> v2 2022 = Denver)")
    print("=" * 80)

    rag = run_plain_rag(cfg)
    cf = asyncio.run(run_cogniflow(cfg))

    rag_stale = "Boston" in rag and "Denver" not in rag
    print("\n--- PLAIN RAG (vector over both PDF reports, top-3) ---")
    print(f" ANSWER: {rag}")
    print(f" VERDICT: {'STALE (Boston)' if rag_stale else 'see answer'}")
    print("\n--- COGNIFLOW-RAG (temporal, as_of = now) ---")
    print(f" facts: {cf['now'].facts}")
    print(f" ANSWER: {cf['now'].answer}")
    print(f" VERDICT: {'CURRENT (Denver)' if 'Denver' in cf['now'].answer else 'see answer'}")
    print("\n--- COGNIFLOW-RAG (temporal, as_of = 2020 = replay) ---")
    print(f" facts: {cf['past'].facts}")
    print(f" ANSWER: {cf['past'].answer}")
    print(f" VERDICT: {'REPLAYED (Boston)' if 'Boston' in cf['past'].answer else 'see answer'}")
    print("=" * 80)
    print(
        "NOTE: plain RAG may answer the *current* question correctly on a small corpus.\n"
        "The structural gap is the as-of axis: plain RAG cannot answer 'as of 2020' at\n"
        "all - it has no temporal dimension. The win is temporal correctness, not recall."
    )


if __name__ == "__main__":
    main()
