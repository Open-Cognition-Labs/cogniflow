"""The context-serving API - query in, temporally-correct *context* out.

Cogniflow as a standalone context engine: any model/agent asks for context "as of T" and
gets validated, provenance-carrying facts to put in its own prompt. **Generation is not our
job** - we serve context, the caller generates the answer.

The load-bearing constraint: the honesty labels survive to the output. Validity intervals,
provenance, and the ``valid_at_source`` confidence (authoritative / derived / none) reach
the consumer, or they were decorative. This module is a read-only serving layer over the
existing substrate read path; it touches no core and never writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .core.contracts import AsyncSubstrate
from .core.types import Belief, RetrievalQuery, ScoredBelief

# T5: the extraction floor, surfaced at the API edge (not just in docs). A consumer should
# weight a derived stamp differently from an authoritative one, and know that prose-extracted
# facts are only as good as the extraction model.
EXTRACTION_FLOOR_NOTE = (
    "Facts from structured input (e.g. OKF 'fact' keys) carry authoritative time; facts "
    "extracted from prose are as reliable as the extraction model and may carry derived or "
    "no validity. Use each fact's valid_at_source to weight confidence."
)

# milestone retrieval-quality notes (T1/T3), surfaced so a consumer never unknowingly evaluates on
# meaning-blind or below-window retrieval. Distinct from the extraction floor above: these are
# about RETRIEVAL (the embedder / the over-fetch window), not prose EXTRACTION (the LLM).
NON_SEMANTIC_RETRIEVAL_NOTE = (
    "Retrieval is non-semantic (hash embedder): results are ranked by lexical token overlap, not "
    "meaning. Configure a real embedder for semantic recall - 'bge-m3-local' (key-free, needs the "
    "[embeddings] extra) or 'bge-m3' (needs COGNIFLOW_EMBEDDER_API_KEY). See the Quickstart."
)
OVERFETCH_SATURATED_NOTE = (
    "The retrieval over-fetch window was saturated: a valid fact ranked below it may have been "
    "missed. Raise COGNIFLOW_OVERFETCH_FACTOR / COGNIFLOW_MIN_OVERFETCH, or narrow the query."
)

# Normalize the producer's raw label into a 3-way confidence signal. The raw label is also
# carried (valid_at_source_raw) so nothing is hidden.
# authoritative - an explicit time was asserted by the source or the caller
# derived - the time was inferred from metadata (e.g. a file mtime)
# none - no validity signal at all
_SOURCE_NORMALIZATION = {
    "okf:timestamp": "derived", # OKF declares a timestamp but has no validity model
    "provided": "authoritative", # caller explicitly asserted the reference time
    "document:mtime": "derived", # inferred from file metadata
    "none": "none",
}


def _normalize_source(raw: str | None) -> str:
    if not raw:
        return "none"
    return _SOURCE_NORMALIZATION.get(raw, "derived")


@dataclass(frozen=True)
class ServedFact:
    """One temporally-correct fact, with its honesty labels intact (the G1 contract)."""

    belief_id: str
    statement: str
    valid_at: datetime | None
    invalid_at: datetime | None
    valid_at_source: str # normalized: "authoritative" | "derived" | "none"
    valid_at_source_raw: str | None # the producer's original label, for full transparency
    provenance: tuple[str, ...] # episode/document ids that asserted this
    superseded_by: str | None # the belief that superseded this one, if any
    score: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "belief_id": self.belief_id,
            "statement": self.statement,
            "valid_at": self.valid_at.isoformat() if self.valid_at else None,
            "invalid_at": self.invalid_at.isoformat() if self.invalid_at else None,
            "valid_at_source": self.valid_at_source,
            "valid_at_source_raw": self.valid_at_source_raw,
            "provenance": list(self.provenance),
            "superseded_by": self.superseded_by,
            "score": self.score,
        }


@dataclass(frozen=True)
class ContextResponse:
    """Structured, model-neutral context for a query - NOT a generated answer. The caller
    formats these facts into its own prompt."""

    query: str
    as_of: datetime | None
    facts: list[ServedFact] = field(default_factory=list)
    notes: tuple[str, ...] = (EXTRACTION_FLOOR_NOTE,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "facts": [f.to_dict() for f in self.facts],
            "notes": list(self.notes),
        }


def _belief_to_served(scored: ScoredBelief) -> ServedFact:
    b: Belief = scored.belief
    raw = b.metadata.get("valid_at_source")
    return ServedFact(
        belief_id=b.id,
        statement=b.statement,
        valid_at=b.valid_at,
        invalid_at=b.invalid_at,
        valid_at_source=_normalize_source(raw),
        valid_at_source_raw=raw,
        provenance=b.provenance,
        superseded_by=b.metadata.get("superseded_by"),
        score=scored.score,
    )


async def serve_context(
    substrate: AsyncSubstrate,
    query: str,
    *,
    as_of: datetime | None = None,
    top_k: int = 5,
    include_expired: bool = False,
    filters: dict[str, Any] | None = None,
) -> ContextResponse:
    """Serve temporally-correct context for ``query`` (read-only).

    ``as_of`` is a first-class parameter (T2): the same query at two ``as_of`` values returns
    different context. Routes through the existing temporal retriever + validity filter; the
    honesty labels (T3) ride through unchanged. Returns context, never a generated answer.
    """
    result = await substrate.read(
        RetrievalQuery(
            text=query,
            as_of=as_of,
            top_k=top_k,
            include_expired=include_expired,
            filters=filters or {},
        )
    )
    facts = [_belief_to_served(sb) for sb in result.results]
    # Surface retrieval-quality notes when the substrate reports them (generic getattr, so a
    # substrate that does not expose these is unaffected). Never silent about meaning-blind
    # retrieval or a saturated over-fetch window .
    notes = [EXTRACTION_FLOOR_NOTE]
    if not getattr(substrate, "embedder_is_semantic", True):
        notes.append(NON_SEMANTIC_RETRIEVAL_NOTE)
    if getattr(substrate, "last_read_saturated", False):
        notes.append(OVERFETCH_SATURATED_NOTE)
    return ContextResponse(query=query, as_of=result.as_of, facts=facts, notes=tuple(notes))
