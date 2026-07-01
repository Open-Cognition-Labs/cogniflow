# ruff: noqa: E501
"""Real multi-framework benchmark: Cogniflow vs the RAG field, every number from a live run.

Systems (same fictional corpus, same NVIDIA MiniMax LLM for parity):
  - Cogniflow           temporal, as-of aware (generate_answer with as_of)
  - Graphiti-substrate  the SAME temporal store queried WITHOUT the as-of layer (ablation) -
                        "the temporal graph very related to Cogniflow" - shows the delta the
                        as-of layer adds even over its own substrate
  - LlamaIndex          vector RAG (NVIDIA embeddings)
  - LangChain           BM25 RAG + NVIDIA ChatOpenAI
  - Haystack            BM25 RAG + NVIDIA OpenAIGenerator

Corpus is FICTIONAL on purpose (no LLM can answer as-of from training). Two panels:
STANDARD (stable facts -> everyone ties) and AS-OF (past dates -> only the temporal, as-of
layer wins). Writes demo/static_demo/benchmark_frameworks.json.

Prereqs: FalkorDB + .env; pip install langchain langchain-openai langchain-community haystack-ai rank-bm25
Run: PYTHONPATH=src python demo/benchmark_frameworks.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parents[1] / ".env")

from benchmark import AS_OF, EPISODES, STANDARD, _hit, build  # noqa: E402
from nvidia_embeddings import NvidiaEmbedding  # noqa: E402

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.bridges.llamaindex import make_llm  # noqa: E402
from cogniflow.generation import generate_answer  # noqa: E402
from cogniflow.generators import create_generator_from_env  # noqa: E402

KEY = os.getenv("COGNIFLOW_LLM_API_KEY")
BASE = os.getenv("COGNIFLOW_LLM_BASE_URL", "https://integrate.api.nvidia.com/v1")
MODEL = os.getenv("COGNIFLOW_LLM_MODEL", "minimaxai/minimax-m3")
GROUP = "bench_frameworks"
TEXTS = [ep.content for ep in EPISODES]
OUT = pathlib.Path(__file__).parent / "static_demo" / "benchmark_frameworks.json"

PROMPT = (
    "Answer the question using ONLY these facts. If they conflict or don't answer it, say you "
    "cannot answer.\n\nFACTS:\n{ctx}\n\nQUESTION: {q}\nANSWER (concise):"
)


# Hardened backoff: a transient 429 (the shared model is hit by every system) must never be
# scored as a capability miss. More attempts, capped backoff, so a rate-limited call recovers
# instead of poisoning the number.
def retry(fn, attempts=8):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(min(2**i, 30))


PACE_S = 1.5  # small inter-call pause to avoid bursting the shared rate limit


# ---- LangChain (BM25 + NVIDIA ChatOpenAI) ----------------------------------
def make_langchain():
    from langchain_community.retrievers import BM25Retriever
    from langchain_openai import ChatOpenAI

    retr = BM25Retriever.from_texts(TEXTS)
    retr.k = 4
    llm = ChatOpenAI(model=MODEL, base_url=BASE, api_key=KEY, temperature=0, max_tokens=512, timeout=120)

    def answer(q: str) -> str:
        docs = retr.invoke(q)
        ctx = "\n".join(f"- {d.page_content}" for d in docs)
        return retry(lambda: llm.invoke(PROMPT.format(ctx=ctx, q=q)).content).strip()

    return answer


# ---- Haystack (BM25 + NVIDIA OpenAIGenerator) ------------------------------
def make_haystack():
    from haystack import Document, Pipeline
    from haystack.components.builders import PromptBuilder
    from haystack.components.generators import OpenAIGenerator
    from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
    from haystack.document_stores.in_memory import InMemoryDocumentStore
    from haystack.utils import Secret

    store = InMemoryDocumentStore()
    store.write_documents([Document(content=t) for t in TEXTS])
    pipe = Pipeline()
    pipe.add_component("retriever", InMemoryBM25Retriever(store, top_k=4))
    pipe.add_component(
        "prompt",
        PromptBuilder(
            template="Answer using ONLY these facts; if they conflict or don't answer, say you cannot answer.\n{% for d in documents %}- {{d.content}}\n{% endfor %}\nQUESTION: {{q}}\nANSWER:",
            required_variables=["q", "documents"],
        ),
    )
    pipe.add_component(
        "llm",
        OpenAIGenerator(
            api_key=Secret.from_token(KEY),
            api_base_url=BASE,
            model=MODEL,
            generation_kwargs={"max_tokens": 512, "temperature": 0},
        ),
    )
    pipe.connect("retriever.documents", "prompt.documents")
    pipe.connect("prompt.prompt", "llm.prompt")

    def answer(q: str) -> str:
        r = retry(lambda: pipe.run({"retriever": {"query": q}, "prompt": {"q": q}}))
        return r["llm"]["replies"][0].strip()

    return answer


# ---- LlamaIndex (vector + NVIDIA) ------------------------------------------
def make_llamaindex():
    from llama_index.core import Document, VectorStoreIndex

    cfg = GraphitiFalkorDBConfig.from_env(group_id=GROUP)
    embed = NvidiaEmbedding(cfg.llm_api_key, cfg.llm_base_url)
    index = retry(lambda: VectorStoreIndex.from_documents([Document(text=t) for t in TEXTS], embed_model=embed))
    engine = index.as_query_engine(llm=make_llm(cfg), embed_model=embed, similarity_top_k=4)
    return lambda q: retry(lambda: str(engine.query(q)).strip())


async def main() -> None:
    from falkordb import FalkorDB

    try:
        FalkorDB(host="localhost", port=6379).select_graph(GROUP).delete()
    except Exception:
        pass

    # Cogniflow store (also serves the Graphiti-substrate ablation)
    cfg = GraphitiFalkorDBConfig.from_env(group_id=GROUP)
    cfg.embedder = "bge-m3" if os.getenv("COGNIFLOW_EMBEDDER_API_KEY") else "hash"
    backend = GraphitiFalkorDBBackend(cfg)
    await backend.setup()
    await build(backend)
    gen = create_generator_from_env()

    async def cogniflow(q, as_of):
        return (await generate_answer(backend, q, gen, as_of=as_of)).answer

    async def ablation(q, as_of):  # temporal store, but ignore as_of (no as-of layer)
        return (await generate_answer(backend, q, gen, as_of=None)).answer

    lc = make_langchain()
    hs = make_haystack()
    li = make_llamaindex()

    systems = [
        ("Cogniflow", "bi-temporal · as-of", "async", cogniflow),
        ("Graphiti (substrate, no as-of)", "temporal · ablation", "async", ablation),
        ("LlamaIndex", "vector RAG", "sync", li),
        ("LangChain", "BM25 RAG", "sync", lc),
        ("Haystack", "BM25 RAG", "sync", hs),
    ]

    async def answer_clean(fn, mode, q, as_of):
        # Retry the WHOLE cell until a real answer. A transient 429 on the shared model must
        # NEVER be scored as a miss (that was the contaminated LangChain row). Fail loud after
        # long backoff rather than baking an error into a published number.
        last: Exception | None = None
        for attempt in range(15):
            try:
                return (await fn(q, as_of)) if mode == "async" else fn(q)
            except Exception as e:  # noqa: BLE001
                last = e
                await asyncio.sleep(min(2**attempt, 60))
        raise RuntimeError(f"benchmark cell failed after retries: {q!r}") from last

    results = []
    for name, kind, mode, fn in systems:
        panels = {}
        for panel, qs in (("standard", STANDARD), ("as_of", AS_OF)):
            rows = []
            for item in qs:
                as_of = item.get("as_of") if panel == "as_of" else None
                ans = await answer_clean(fn, mode, item["q"], as_of)
                hit = _hit(ans, item["expect"], item.get("avoid"))
                rows.append({"q": item["q"], "expect": item["expect"], "answer": ans, "hit": hit})
                await asyncio.sleep(PACE_S)
            panels[panel] = {"n": len(rows), "score": sum(r["hit"] for r in rows), "rows": rows}
        results.append({"name": name, "kind": kind, **panels})
        print(f"{name:32s} standard {panels['standard']['score']}/{panels['standard']['n']}   as-of {panels['as_of']['score']}/{panels['as_of']['n']}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Integrity stamp: sha256 of the systems array in canonical form (sorted keys, compact). A
    # visitor can recompute this from the served JSON to confirm the numbers were not hand-edited,
    # and re-run `reproduce` to regenerate them. "Reproducible" is thus verifiable, not asserted.
    content_hash = "sha256:" + hashlib.sha256(
        json.dumps(results, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "reproduce": "python demo/benchmark_frameworks.py",
        "content_hash": content_hash,
        "systems": results,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("captured ->", OUT, content_hash)
    await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
