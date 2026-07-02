"""OKF (Open Knowledge Format) intake - the first front door .

Parses a Google OKF bundle (a directory of markdown files with YAML frontmatter) and
maps each concept to a cogniflow ``Episode`` that the existing substrate ``write`` path
ingests. Touches no core; it is a pure producer.

Built to the OKF SPEC's weak conformance (SPEC.md sec.4.1/sec.9), NOT the reference
agent's stricter rule:
 - only ``type`` is meaningful; missing optional fields are tolerated,
 - unknown ``type`` values are tolerated,
 - broken cross-links are tolerated (never a parse failure).

Honesty rule: OKF's ``timestamp`` is *last-modified* and ``log.md`` is a prose changelog
- neither is an authoritative validity interval. So a concept's ``valid_at`` is *derived*
and labeled in metadata (``valid_at_source``); when a bundle gives no temporal signal the
fact carries no OKF-authoritative time. A producer MAY add a ``fact`` extension key
(OKF allows arbitrary keys) for a precise temporal triple; otherwise the body is ingested
as prose and the engine extracts what it can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .core.contracts import AsyncSubstrate
from .core.types import Episode, WriteReceipt, utc_now

_FM = "---"
_RESERVED = {"index.md", "log.md"}
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


@dataclass
class OKFConcept:
    concept_id: str # file path within the bundle, minus .md (sec.2)
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    links: list[str] = field(default_factory=list)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FM:
        return {}, text # no frontmatter is tolerated (weak conformance)
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == _FM), None)
    if end is None:
        return {}, text
    try:
        fm = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return fm, body


def parse_concept(text: str, concept_id: str) -> OKFConcept:
    fm, body = _split_frontmatter(text)
    return OKFConcept(
        concept_id=concept_id, frontmatter=fm, body=body, links=_LINK_RE.findall(body)
    )


def parse_bundle(root: str | Path) -> list[OKFConcept]:
    """Parse every non-reserved .md concept in the bundle, in stable path order."""
    root = Path(root)
    concepts: list[OKFConcept] = []
    for path in sorted(root.rglob("*.md")):
        if path.name in _RESERVED:
            continue
        concept_id = path.relative_to(root).as_posix()[: -len(".md")]
        concepts.append(parse_concept(path.read_text(encoding="utf-8"), concept_id))
    return concepts


def _derive_valid_at(frontmatter: dict[str, Any]) -> tuple[datetime | None, str]:
    """Derive a (best-effort, non-authoritative) valid_at from OKF metadata.

    Returns (datetime|None, source_label). OKF gives only a last-modified timestamp;
    we surface it as derived and label its provenance so the audit trail never claims
    temporal certainty OKF did not provide.
    """
    ts = frontmatter.get("timestamp")
    if isinstance(ts, datetime):
        return ts, "okf:timestamp"
    if isinstance(ts, str) and ts.strip():
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")), "okf:timestamp"
        except ValueError:
            return None, "unparseable-timestamp"
    return None, "none"


def concept_to_episode(concept: OKFConcept) -> Episode:
    """Map one OKF concept to an Episode. Concept id flows into provenance; OKF fields
    are preserved in metadata; valid_at is derived and labeled."""
    fm = concept.frontmatter
    valid_at, valid_src = _derive_valid_at(fm)
    metadata: dict[str, Any] = {
        "okf_concept_id": concept.concept_id, # identity -> provenance/lineage
        "okf_type": fm.get("type"),
        "okf_resource": fm.get("resource"),
        "okf_tags": list(fm.get("tags") or []),
        "okf_links": list(concept.links), # untyped directed edges (generic first cut)
        "valid_at_source": valid_src, # honesty label: derived, not OKF-authoritative
    }
    # Optional precise temporal fact via an OKF extension key (arbitrary keys allowed).
    fact = fm.get("fact")
    if isinstance(fact, dict) and {"subject", "predicate", "object"} <= set(fact):
        statement = fact.get("statement") or (fm.get("title") or concept.concept_id)
        metadata["triple"] = {
            "source": fact["subject"],
            "predicate": fact["predicate"],
            "target": fact["object"],
            "fact": statement,
        }
    return Episode(
        id=concept.concept_id,
        content=concept.body,
        reference_time=valid_at or utc_now(),
        source="okf",
        source_description=str(fm.get("title") or concept.concept_id),
        metadata=metadata,
    )


async def ingest_bundle(substrate: AsyncSubstrate, root: str | Path) -> list[WriteReceipt]:
    """Ingest every concept in a bundle through the existing substrate write path.

    Cross-version supersession is free: re-ingesting an evolved bundle whose concept
    changed triggers the engine's contradiction resolution. Ingest v1 then v2 to see it.
    """
    receipts: list[WriteReceipt] = []
    for concept in parse_bundle(root):
        receipts.append(await substrate.write(concept_to_episode(concept)))
    return receipts
