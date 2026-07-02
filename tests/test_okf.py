"""OKF intake - CI-safe (no infra). Covers G1 spec conformance, the concept->Episode
mapping, derived/labeled valid_at, links->edges, and ingestion through a fake substrate.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

pytest.importorskip("yaml")

from cogniflow.core.types import FalsificationVerdict, RetrievalResult, WriteReceipt  # noqa: E402
from cogniflow.okf import (  # noqa: E402
    concept_to_episode,
    ingest_bundle,
    parse_bundle,
    parse_concept,
)

TYPE_ONLY = "---\ntype: Concept\n---\njust a body, only `type` in frontmatter.\n"
BROKEN_LINKS = (
    "---\ntype: Reference\ntitle: Has broken links\n---\n"
    "See [missing](/does/not/exist.md) and [also missing](./nope.md).\n"
)
FULL = (
    "---\n"
    "type: Metric\n"
    "title: Weekly Active Users\n"
    "description: Distinct active users in a trailing window.\n"
    "resource: https://example.com/metrics/wau\n"
    "tags: [growth, kpi]\n"
    "timestamp: '2026-03-01T00:00:00+00:00'\n"
    "fact:\n"
    " subject: Weekly Active Users\n"
    " predicate: DEFINED_AS\n"
    " object: trailing 7-day distinct users\n"
    " statement: Weekly Active Users is defined as trailing 7-day distinct users.\n"
    "---\n"
    "# Definition\nTrailing 7-day distinct users. See [users](/tables/users.md).\n"
)


def _write_bundle(root, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def test_spec_conformance_type_only_and_broken_links(tmp_path) -> None:
    # G1: a type-only bundle and a broken-links bundle must ingest cleanly.
    _write_bundle(tmp_path, {"a.md": TYPE_ONLY, "refs/b.md": BROKEN_LINKS, "index.md": "# ignored"})
    concepts = parse_bundle(tmp_path)
    ids = sorted(c.concept_id for c in concepts)
    assert ids == ["a", "refs/b"] # index.md is reserved, skipped
    for c in concepts: # mapping must not raise on minimal / broken-link concepts
        ep = concept_to_episode(c)
        assert ep.id == c.concept_id


def test_concept_to_episode_mapping_and_derived_valid_at() -> None:
    concept = parse_concept(FULL, "metrics/wau")
    ep = concept_to_episode(concept)
    assert ep.id == "metrics/wau" # concept id -> provenance/lineage
    assert "Trailing 7-day distinct users" in ep.content
    assert ep.reference_time == datetime(2026, 3, 1, tzinfo=timezone.utc)
    md = ep.metadata
    assert md["okf_type"] == "Metric"
    assert md["okf_resource"] == "https://example.com/metrics/wau"
    assert md["okf_tags"] == ["growth", "kpi"]
    assert md["valid_at_source"] == "okf:timestamp" # derived, labeled
    assert "/tables/users.md" in md["okf_links"] # link -> edge
    assert md["triple"]["target"] == "trailing 7-day distinct users" # extension fast-path


def test_no_timestamp_is_labeled_not_okf_authoritative() -> None:
    ep = concept_to_episode(parse_concept(TYPE_ONLY, "a"))
    assert ep.metadata["valid_at_source"] == "none" # honesty: not OKF-authoritative
    assert "triple" not in ep.metadata # no extension fact -> prose path


def test_ingest_bundle_writes_each_concept_through_substrate(tmp_path) -> None:
    _write_bundle(tmp_path, {"a.md": TYPE_ONLY, "metrics/wau.md": FULL})

    class _RecordingSubstrate:
        def __init__(self) -> None:
            self.written: list[str] = []

        async def write(self, episode) -> WriteReceipt:
            self.written.append(episode.id)
            return WriteReceipt(episode_id=episode.id)

        async def read(self, query) -> RetrievalResult: # pragma: no cover
            return RetrievalResult(query=query, results=(), as_of=query.as_of)

        async def falsify(self, target, against=None) -> FalsificationVerdict: # pragma: no cover
            return FalsificationVerdict(target_id=str(target), superseded=False)

    sub = _RecordingSubstrate()
    receipts = asyncio.run(ingest_bundle(sub, tmp_path))
    assert sorted(sub.written) == ["a", "metrics/wau"]
    assert len(receipts) == 2
