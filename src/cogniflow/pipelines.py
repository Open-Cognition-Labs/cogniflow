"""Straight temporal-RAG query loop .

Deliberately a STRAIGHT pipeline, not the milestone agentic loop:

    question -> temporal retrieve (validity-filtered, as-of-able) -> generate

Retrieval goes through the substrate's existing temporal read (the validity filter does
the work); generation is the only new piece and is injected, so the loop is testable with
a fake generator (CI) and a real LLM (integration). It accepts an ``as_of`` so the same
question can be asked at two points in time - the heartbeat, now over the product surface.

Touches no core; depends only on the AsyncSubstrate contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime

from .core.contracts import AsyncSubstrate
from .core.types import RetrievalQuery

# prompt -> answer text. May be sync or async; both are awaited safely.
GenerateFn = Callable[[str], "str | Awaitable[str]"]

_PROMPT = (
    "You answer strictly from the facts below, which are the ones known to be valid at "
    "the requested time. Do not use any other knowledge. If the facts do not contain the "
    "answer, say you do not know.\n\nFacts:\n{facts}\n\nQuestion: {question}\nAnswer in one "
    "short sentence:"
)


@dataclass
class RAGResult:
    answer: str
    facts: list[str] = field(default_factory=list)
    as_of: datetime | None = None


async def _maybe_await(value: str | Awaitable[str]) -> str:
    if hasattr(value, "__await__"):
        return await value # type: ignore[misc]
    return value # type: ignore[return-value]


async def temporal_rag_answer(
    substrate: AsyncSubstrate,
    question: str,
    generate: GenerateFn,
    *,
    as_of: datetime | None = None,
    top_k: int = 5,
    include_expired: bool = False,
) -> RAGResult:
    """Retrieve the temporally-valid facts (as of ``as_of``), then generate an answer."""
    result = await substrate.read(
        RetrievalQuery(text=question, as_of=as_of, top_k=top_k, include_expired=include_expired)
    )
    facts = [s.belief.statement for s in result.results]
    context = "\n".join(f"- {f}" for f in facts) if facts else "(no facts valid at this time)"
    answer = await _maybe_await(generate(_PROMPT.format(facts=context, question=question)))
    return RAGResult(answer=str(answer).strip(), facts=facts, as_of=as_of)
