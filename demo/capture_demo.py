"""Capture a REAL run for the static demo + measure the reranker on the confusable corpus.

Writes demo/static_demo/demo_data.json (a real captured run - never faked) and prints a
report: the as-of head-to-head (the lead), the cited answer with confidence, the reranker
lift (off vs on), and the weak-context faithfulness check.

Prereqs: FalkorDB, .env with COGNIFLOW_LLM_* and COGNIFLOW_EMBEDDER_API_KEY.
Run: PYTHONPATH=src python demo/capture_demo.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from confusable_corpus import AS_OF_CASE, EPISODES, GOLDEN, build  # noqa: E402

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.context import serve_context  # noqa: E402
from cogniflow.generation import generate_answer  # noqa: E402
from cogniflow.generators import create_generator_from_env  # noqa: E402

UTC = timezone.utc
GROUP = "demo_confusable"
OUT = pathlib.Path(__file__).parent / "static_demo" / "demo_data.json"


def _backend(retrieval_policy: str, params: dict | None = None) -> GraphitiFalkorDBBackend:
    cfg = GraphitiFalkorDBConfig.from_env(group_id=GROUP)
    cfg.embedder = "bge-m3"
    cfg.retrieval_policy = retrieval_policy
    cfg.retrieval_params = params or {}
    return GraphitiFalkorDBBackend(cfg)


def _top1_hits(results: list[dict]) -> tuple[int, float]:
    """top-1 accuracy count and MRR over the golden set."""
    hits, rr = 0, 0.0
    for r in results:
        ranks = [i for i, s in enumerate(r["ranked"]) if r["expect_company"].split()[0] in s]
        if ranks:
            rr += 1.0 / (ranks[0] + 1)
            if ranks[0] == 0:
                hits += 1
    return hits, rr / len(results) if results else 0.0


async def _golden_run(backend: GraphitiFalkorDBBackend) -> list[dict]:
    out = []
    for g in GOLDEN:
        ctx = await serve_context(backend, g["query"], top_k=5)
        out.append({
            "query": g["query"],
            "expect_company": g["expect_company"],
            "ranked": [f.statement for f in ctx.facts],
        })
    return out


async def main() -> None:
    from falkordb import FalkorDB

    try:
        FalkorDB(host="localhost", port=6379).select_graph(GROUP).delete()
    except Exception:
        pass

    ingest = _backend("default")
    await ingest.setup()
    await build(ingest) # confusable corpus, chronological order

    plain = ingest # retrieval OFF (default passthrough)
    rerank = _backend("reranker", {"reranker": "nvidia-rerank"}) # retrieval ON, same graph
    gen = create_generator_from_env()

    # --- the reranker measurement (off vs on) ---
    off = await _golden_run(plain)
    on = await _golden_run(rerank)
    off_hits, off_mrr = _top1_hits(off)
    on_hits, on_mrr = _top1_hits(on)

    # --- the as-of head-to-head lead + cited answer with confidence ---
    q = AS_OF_CASE["query"]
    now = await generate_answer(rerank, q, gen)
    past = await generate_answer(rerank, q, gen, as_of=AS_OF_CASE["past"]["as_of"])

    # --- weak-context faithfulness ---
    weak = await generate_answer(rerank, "What was Tesla's annual revenue in 2019?", gen)

    data = {
        "captured_at": datetime.now(UTC).isoformat(),
        "corpus_size": len(EPISODES),
        "as_of_headline": {
            "query": q,
            "now": {"answer": now.answer, "confidence": now.confidence,
                    "facts": [f.to_dict() for f in now.facts]},
            "past_2015": {"answer": past.answer, "confidence": past.confidence,
                          "facts": [f.to_dict() for f in past.facts]},
            "plain_rag_note": "Plain RAG has no as-of axis: it cannot answer the 2015 case at all.",
        },
        "reranker": {
            "model": "nvidia-rerank (measures the plug; default self-hosted = bge-reranker-v2-m3)",
            "golden_size": len(GOLDEN),
            "off": {"top1": off_hits, "mrr": round(off_mrr, 3), "runs": off},
            "on": {"top1": on_hits, "mrr": round(on_mrr, 3), "runs": on},
        },
        "weak_context": {
            "query": "What was Tesla's annual revenue in 2019?",
            "answer": weak.answer,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")

    print("=" * 78)
    print(f"AS-OF HEADLINE: {q}")
    print(f" now -> {now.answer} {now.confidence}")
    print(f" as of 2015 -> {past.answer} {past.confidence}")
    print(" plain RAG -> cannot answer 'as of 2015' at all (no temporal axis)")
    print("-" * 78)
    print(f"RERANKER on the confusable corpus (golden n={len(GOLDEN)}):")
    print(f" OFF (retrieval only): top1={off_hits}/{len(GOLDEN)} MRR={off_mrr:.3f}")
    print(f" ON (nvidia-rerank) : top1={on_hits}/{len(GOLDEN)} MRR={on_mrr:.3f}")
    print(f" LIFT: top1 {on_hits - off_hits:+d} MRR {on_mrr - off_mrr:+.3f}")
    print("-" * 78)
    print(f"WEAK CONTEXT: {weak.answer[:120]}")
    print("=" * 78)
    print(f"captured -> {OUT}")

    await rerank.close()
    await ingest.close()


if __name__ == "__main__":
    asyncio.run(main())
