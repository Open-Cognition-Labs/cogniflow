"""The generation layer - closing the RAG loop (context -> cited answer).

Thin and optional: it sits on the context API (A.3). The model-agnostic context core stays
underneath - a caller can still take context and bring their own model; this layer is the
convenience that answers with one configured LLM call. No core change; read-only.

Two load-bearing properties:
  A. Temporal correctness survives generation. The context is already as-of-filtered, so the
     answer is as-of-correct BY CONSTRUCTION - provided the LLM answers ONLY from the served
     context and is told to ignore its own training. Asked "where was X as of 2020", it must
     answer from the 2020 context (the old fact), not from what its training knows today. This
     is the milestone un-knowing invariant, at the generation step.
  B. The answer does not launder the extraction floor. Each cited fact carries its
     valid_at_source confidence (authoritative structured vs derived/prose), and the response
     surfaces it, so a confident sentence built on LLM-extracted prose is not mistaken for one
     built on deterministic structured facts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .context import ContextResponse, ServedFact, serve_context
from .core.contracts import AsyncSubstrate
from .faithfulness import FaithfulnessReport, create_checker

Generator = Callable[[str], "str | Awaitable[str]"]

# F2: strict-mode decline text - unsupported claims are never silently shipped OR silently
# rewritten; strict mode declines and says why, with the report attached for the caller.
_DECLINE = (
    "I cannot provide this answer: {n} claim(s) were not supported by the served facts "
    "(faithfulness check '{checker}'). See the attached faithfulness report."
)

# The constraint that makes temporal correctness nearly free: answer ONLY from the served
# (as-of-filtered) facts, and explicitly ignore the model's own training knowledge.
_PROMPT = """You answer strictly from the CONTEXT FACTS below, which are the system's \
knowledge as of {as_of}. Follow these rules exactly:
- Use ONLY the context facts. Do NOT use your own training/background knowledge.
- If a fact in the context conflicts with what you think you know, TRUST THE CONTEXT - it is \
the temporally-correct truth as of {as_of}.
- If the context does not contain the answer, say you do not have that information. Do not guess.
- Cite the facts you used.

CONTEXT FACTS (as of {as_of}):
{facts}

QUESTION: {query}

ANSWER (only from the context facts above):"""


@dataclass
class GenerationResult:
    """A cited, temporally-correct answer plus the facts (and their confidence + provenance)
    it was generated from. The context surface (A.3) still exists standalone; this is the
    optional answer-out convenience over it."""

    answer: str
    facts: list[ServedFact] = field(default_factory=list)
    as_of: datetime | None = None
    generator_model: str | None = None
    confidence: dict[str, int] = field(default_factory=dict) # valid_at_source histogram
    faithfulness: FaithfulnessReport | None = None # F2: the checked (not just asked) guarantee

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "generator_model": self.generator_model,
            "confidence": self.confidence, # B: don't launder the floor
            "facts": [f.to_dict() for f in self.facts], # T4: provenance attached
            "faithfulness": self.faithfulness.to_dict() if self.faithfulness else None,
        }


async def _maybe_await(value: str | Awaitable[str]) -> str:
    if hasattr(value, "__await__"):
        return await value # type: ignore[misc]
    return value # type: ignore[return-value]


def _format_facts(facts: list[ServedFact]) -> str:
    if not facts:
        return "(no facts available)"
    lines = []
    for f in facts:
        window = f.valid_at.date().isoformat() if f.valid_at else "undated"
        prov = ", ".join(f.provenance) if f.provenance else "unknown"
        lines.append(
            f"- {f.statement} [valid_from: {window}; confidence: {f.valid_at_source}; "
            f"source: {prov}]"
        )
    return "\n".join(lines)


def build_prompt(query: str, context: ContextResponse) -> str:
    as_of = context.as_of.date().isoformat() if context.as_of else "now"
    return _PROMPT.format(as_of=as_of, facts=_format_facts(context.facts), query=query)


def _confidence(facts: list[ServedFact]) -> dict[str, int]:
    return dict(Counter(f.valid_at_source for f in facts))


async def generate_answer(
    substrate: AsyncSubstrate,
    query: str,
    generator: Generator,
    *,
    as_of: datetime | None = None,
    top_k: int = 5,
    include_expired: bool = False,
    filters: dict[str, Any] | None = None,
    faithfulness: str | None = "lexical",
    faithfulness_mode: str = "flag",
) -> GenerationResult:
    """Close the loop: serve as-of-correct context, then generate a cited answer from ONLY
    that context. Reuses serve_context (A.3); adds no outside retrieval; never writes.

    F2: the answer is then CHECKED against the served facts (post-hoc, not prompt trust).
    ``faithfulness`` selects the checker by name ('lexical' default - deterministic, key-free;
    'llm-judge' opt-in; 'off' is visibly off). ``faithfulness_mode``: 'flag' (default - report
    attached, answer untouched) or 'strict' (unsupported claims -> the answer is declined,
    never silently shipped). Unknown names/modes raise (fail-loud)."""
    if faithfulness_mode not in ("flag", "strict"):
        raise ValueError(f"faithfulness_mode must be 'flag' or 'strict', got {faithfulness_mode!r}")
    context = await serve_context(
        substrate,
        query,
        as_of=as_of,
        top_k=top_k,
        include_expired=include_expired,
        filters=filters,
    )
    answer = (await _maybe_await(generator(build_prompt(query, context)))).strip()
    checker = create_checker(faithfulness, generator=generator)
    # the as-of year is caller-supplied truth (it appears in honest answers like "As of 2015,
    # ..."), so the checker must not count it as model-invented content
    known = {str(context.as_of.year)} if context.as_of else None
    report = await checker.check(answer, list(context.facts), known=known)
    if faithfulness_mode == "strict" and report.unsupported_claims:
        answer = _DECLINE.format(n=len(report.unsupported_claims), checker=report.checker)
    return GenerationResult(
        answer=answer,
        facts=list(context.facts),
        as_of=context.as_of,
        generator_model=getattr(generator, "model", None),
        confidence=_confidence(context.facts),
        faithfulness=report,
    )
