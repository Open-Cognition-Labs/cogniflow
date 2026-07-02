# ruff: noqa: E501
"""Real two-panel benchmark: plain RAG vs Cogniflow, every number from a live run.

Panel 1 - STANDARD questions (stable current facts): plain RAG and Cogniflow both do well.
          An honest tie - Cogniflow inherits Graphiti's retrieval; it does not out-retrieve.
Panel 2 - AS-OF questions (what was true at a past date): plain RAG has no time axis and
          scores near-zero; Cogniflow answers from as-of-filtered context.

CRITICAL - the corpus is FICTIONAL (invented companies/cities), on purpose. On famous real
entities a large LLM already knows the history and would answer as-of questions from its
TRAINING, not from any temporal store - which confounds the test (measured: plain RAG scored
4/4 on real-company as-of questions purely from training). The temporal advantage only shows
on facts the model has never seen - i.e. YOUR private/enterprise data - so we benchmark there.
Dates live ONLY in metadata (valid_at), never in the fact text, so plain RAG genuinely cannot
recover the past. The honesty about Panel 1 is what makes Panel 2 credible. Writes benchmark_data.json.
Prereqs: FalkorDB, .env with COGNIFLOW_LLM_* and COGNIFLOW_EMBEDDER_API_KEY.
Run: PYTHONPATH=src python demo/benchmark.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import time
from datetime import datetime, timezone


def _retry(fn, attempts: int = 6):
    """Retry a flaky call (the plain-RAG LlamaIndex/embedding path has no backoff of its own;
    the hosted API returns transient 429/5xx)."""
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            time.sleep(2**i)

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from nvidia_embeddings import NvidiaEmbedding  # noqa: E402

from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.bridges.llamaindex import make_llm  # noqa: E402
from cogniflow.core.types import Episode  # noqa: E402
from cogniflow.generation import generate_answer  # noqa: E402
from cogniflow.generators import create_generator_from_env  # noqa: E402

UTC = timezone.utc
GROUP = "demo_benchmark"
OUT = pathlib.Path(__file__).parent / "static_demo" / "benchmark_data.json"


def _dt(y: int) -> datetime:
    return datetime(y, 1, 1, tzinfo=UTC)


def _hq(eid: str, company: str, city: str, year: int) -> Episode:
    # date lives ONLY in reference_time (valid_at metadata), never in the fact text - so plain
    # RAG has no textual way to recover the past, and the company is fictional so there is no
    # training to fall back on.
    return Episode(
        id=eid, content=f"{company} is headquartered in {city}.", reference_time=_dt(year),
        source="okf",
        metadata={"triple": {"source": company, "predicate": "HEADQUARTERED_IN", "target": city,
                             "fact": f"{company} is headquartered in {city}"},
                  "valid_at_source": "okf:timestamp"},
    )


# A FICTIONAL corpus: no LLM has memorized these COMPANIES, so as-of questions can only be
# answered by a temporal store. Changed-HQ entities are written oldest-first so the newer
# supersedes. F3 expansion: 20 stable companies (does the tie hold at 20?), 6 movers including
# a TWO-HOP supersession chain (Gantry: Redmarsh -> Stonewick -> Wrenfield).
_STABLE = [
    ("zephyr", "Zephyr Logistics", "Millbrook", 2010),
    ("corvus", "Corvus Analytics", "Fenwick", 2012),
    ("halcyon", "Halcyon Grid", "Ashford", 2013),
    ("vantor", "Vantor Foods", "Draymoor", 2014),
    ("ashgrove", "Ashgrove Metals", "Sablewood", 2010),
    ("bluewick", "Bluewick Energy", "Torvane", 2012),
    ("calderdyn", "Calder Dynamics", "Grelling", 2011),
    ("drayton", "Drayton Marine", "Ostmere", 2013),
    ("ellsworth", "Ellsworth Biotech", "Pellworth", 2014),
    ("foxbridge", "Foxbridge Capital", "Quillhaven", 2015),
    ("junewood", "Junewood Press", "Redfall", 2009),
    ("lorimer", "Lorimer Shipping", "Saltmere", 2011),
    ("marrowgate", "Marrowgate Pharma", "Thornmere", 2012),
    ("northquay", "Northquay Insurance", "Umberley", 2013),
    ("oakhollow", "Oakhollow Farms", "Veldmoor", 2010),
    ("pinemont", "Pinemont Software", "Wrenlow", 2016),
    ("quarrell", "Quarrell Robotics", "Yarrowgate", 2014),
    ("rushdale", "Rushdale Media", "Zellwick", 2015),
    ("silvermoor", "Silvermoor Textiles", "Brackenholt", 2012),
    ("tarnwick", "Tarnwick Optics", "Caldbrook", 2013),
]
_MOVES = [
    ("meridian_old", "Meridian Systems", "Calderport", 2009),
    ("orinoco_old", "Orinoco Labs", "Westfall", 2011),
    ("gantry_old", "Gantry Textiles", "Redmarsh", 2008),
    ("harwick_old", "Harwick Instruments", "Elmsworth", 2010),
    ("ironvale_old", "Ironvale Mining", "Fernbeck", 2012),
    ("kestrel_old", "Kestrel Avionics", "Glenmoor", 2011),
    ("gantry_mid", "Gantry Textiles", "Stonewick", 2015), # hop 1 of the chain
    ("kestrel_new", "Kestrel Avionics", "Hollowbrent", 2018),
    ("orinoco_new", "Orinoco Labs", "Kingsford", 2019),
    ("meridian_new", "Meridian Systems", "Newhaven", 2020),
    ("ironvale_new", "Ironvale Mining", "Ivorlan", 2020),
    ("gantry_new", "Gantry Textiles", "Wrenfield", 2021), # hop 2 of the chain
    ("harwick_new", "Harwick Instruments", "Dunmarsh", 2022),
]
# olds before news so supersession runs in write order
EPISODES = [_hq(*row) for row in (*_STABLE[:6], *_MOVES[:6], *_STABLE[6:], *_MOVES[6:])]


async def build(backend) -> None:
    # Retry-until-real per episode: a transient hosted-API 429/500 burst must never kill the
    # run (or worse, produce a partial corpus). Fail loud only after generous backoff.
    for ep in EPISODES:
        for attempt in range(8):
            try:
                await backend.write(ep)
                break
            except Exception:
                if attempt == 7:
                    raise
                await asyncio.sleep(min(2**attempt, 45))


# Panel 1: 20 stable fictional facts that do not change - a fair test both systems can pass.
# The honest tie at n=20 is what makes the as-of panel credible.
STANDARD = [
    {"q": f"Where is {company} headquartered?", "expect": city}
    for _, company, city, _y in _STABLE
]

# Panel 2: what was true at a PAST date, for entities that later moved - only a temporal store
# can answer (dates are not in the text; the companies are fictional). Includes the two-hop
# chain (both hops) and post-move boundaries (as-of AFTER a move must return the NEW city,
# not the older one).
AS_OF = [
    {"q": "Where was Meridian Systems headquartered in 2015?", "expect": "Calderport", "avoid": "Newhaven", "as_of": _dt(2015)},
    {"q": "Where was Orinoco Labs headquartered in 2013?", "expect": "Westfall", "avoid": "Kingsford", "as_of": _dt(2013)},
    {"q": "Where was Meridian Systems headquartered in 2011?", "expect": "Calderport", "avoid": "Newhaven", "as_of": _dt(2011)},
    {"q": "Where was Orinoco Labs headquartered in 2015?", "expect": "Westfall", "avoid": "Kingsford", "as_of": _dt(2015)},
    {"q": "Where was Gantry Textiles headquartered in 2012?", "expect": "Redmarsh", "avoid": "Stonewick", "as_of": _dt(2012)},
    {"q": "Where was Gantry Textiles headquartered in 2018?", "expect": "Stonewick", "avoid": "Wrenfield", "as_of": _dt(2018)},
    {"q": "Where was Gantry Textiles headquartered in 2010?", "expect": "Redmarsh", "avoid": "Wrenfield", "as_of": _dt(2010)},
    {"q": "Where was Harwick Instruments headquartered in 2016?", "expect": "Elmsworth", "avoid": "Dunmarsh", "as_of": _dt(2016)},
    {"q": "Where was Ironvale Mining headquartered in 2016?", "expect": "Fernbeck", "avoid": "Ivorlan", "as_of": _dt(2016)},
    {"q": "Where was Kestrel Avionics headquartered in 2014?", "expect": "Glenmoor", "avoid": "Hollowbrent", "as_of": _dt(2014)},
    {"q": "Where was Kestrel Avionics headquartered in 2019?", "expect": "Hollowbrent", "avoid": "Glenmoor", "as_of": _dt(2019)},
    {"q": "Where was Meridian Systems headquartered in 2021?", "expect": "Newhaven", "avoid": "Calderport", "as_of": _dt(2021)},
]


def _hit(answer: str, expect: str, avoid: str | None = None) -> bool:
    # An as-of answer is correct only if it isolates the right fact: it names the correct city
    # AND does not fall back on the superseded one (a hedge that lists both is not an answer).
    a = (answer or "").lower()
    if expect.lower() not in a:
        return False
    return not (avoid and avoid.lower() in a)


async def main() -> None:
    from falkordb import FalkorDB
    from llama_index.core import Document, VectorStoreIndex

    try:
        FalkorDB(host="localhost", port=6379).select_graph(GROUP).delete()
    except Exception:
        pass

    cfg = GraphitiFalkorDBConfig.from_env(group_id=GROUP)
    cfg.embedder = "bge-m3"
    backend = GraphitiFalkorDBBackend(cfg)
    await backend.setup()
    await build(backend)
    gen = create_generator_from_env()

    # plain RAG: a vector index over ALL fact statements (it has every fact, but no time axis)
    embed = NvidiaEmbedding(cfg.llm_api_key, cfg.llm_base_url)
    docs = [Document(text=ep.content) for ep in EPISODES]
    index = _retry(lambda: VectorStoreIndex.from_documents(docs, embed_model=embed))
    engine = index.as_query_engine(llm=make_llm(cfg), embed_model=embed, similarity_top_k=3)

    def plain(q: str) -> str:
        return _retry(lambda: str(engine.query(q)).strip())

    async def cog(q: str, as_of=None) -> str:
        return (await generate_answer(backend, q, gen, as_of=as_of)).answer

    panels = {}
    for name, qs, is_asof in (("standard", STANDARD, False), ("as_of", AS_OF, True)):
        rows = []
        for item in qs:
            p = plain(item["q"])
            c = await cog(item["q"], item.get("as_of") if is_asof else None)
            avoid = item.get("avoid")
            rows.append({
                "q": item["q"], "expect": item["expect"],
                "plain": p, "plain_hit": _hit(p, item["expect"], avoid),
                "cogniflow": c, "cogniflow_hit": _hit(c, item["expect"], avoid),
            })
        panels[name] = {
            "n": len(rows),
            "plain_score": sum(r["plain_hit"] for r in rows),
            "cogniflow_score": sum(r["cogniflow_hit"] for r in rows),
            "rows": rows,
        }

    data = {"captured_at": datetime.now(UTC).isoformat(), "panels": panels}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")

    print("=" * 74)
    for name in ("standard", "as_of"):
        p = panels[name]
        label = "STANDARD (stable facts)" if name == "standard" else "AS-OF (past dates)"
        print(f"{label}: plain RAG {p['plain_score']}/{p['n']} Cogniflow {p['cogniflow_score']}/{p['n']}")
    print("=" * 74)
    print(f"captured -> {OUT}")
    await backend.close()


if __name__ == "__main__":
    asyncio.run(main())
