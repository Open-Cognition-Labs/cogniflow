"""Document front door - CI-safe. Mapping, derived/labeled valid_at,
structure-preserving chunking, and (with pypdf) PDF parsing. No infra.
"""

from __future__ import annotations

import asyncio
import pathlib
from datetime import datetime, timezone

import pytest

from cogniflow.core.types import FalsificationVerdict, RetrievalResult, WriteReceipt
from cogniflow.documents import (
    DocBlock,
    chunk_blocks,
    document_to_episodes,
    ingest_document,
)

MD = """# Overview

Acme Corp is headquartered in Boston. Founded 2010.

# Metrics

| metric | value |
| ------ | ----- |
| users | 100 |
| spend | 50 |
"""


def test_chunking_keeps_table_whole_and_attaches_heading() -> None:
    blocks = [
        DocBlock("heading", "# Metrics"),
        DocBlock("table", "| a | b |\n| 1 | 2 |"),
        DocBlock("heading", "# Notes"),
        DocBlock("paragraph", "Some prose under notes."),
    ]
    chunks = chunk_blocks(blocks)
    table_chunks = [c for c in chunks if "| 1 | 2 |" in c]
    assert len(table_chunks) == 1 # table is one whole chunk, never split
    assert "# Metrics" in table_chunks[0] # heading attached to the table
    notes = [c for c in chunks if "Some prose under notes." in c]
    assert notes and "# Notes" in notes[0] # heading kept with its section


def test_document_to_episodes_mapping_and_provenance(tmp_path) -> None:
    p = tmp_path / "acme.md"
    p.write_text(MD, encoding="utf-8")
    when = datetime(2019, 1, 1, tzinfo=timezone.utc)
    episodes = document_to_episodes(p, reference_time=when)
    assert episodes
    first = episodes[0]
    assert first.id == "acme#chunk0" # doc identity -> provenance
    assert first.reference_time == when
    assert first.metadata["doc_id"] == "acme"
    assert first.metadata["chunk_index"] == 0
    assert first.metadata["valid_at_source"] == "provided" # labeled
    # the table survived as content somewhere
    assert any("| users | 100" in e.content for e in episodes)


def test_valid_at_source_label_defaults_to_document_mtime(tmp_path) -> None:
    p = tmp_path / "x.txt"
    p.write_text("Acme Corp is headquartered in Boston.", encoding="utf-8")
    ep = document_to_episodes(p)[0]
    assert ep.metadata["valid_at_source"] == "document:mtime" # derived, not authoritative


def test_ingest_document_writes_each_chunk(tmp_path) -> None:
    p = tmp_path / "doc.md"
    p.write_text(MD, encoding="utf-8")

    class _Recording:
        def __init__(self) -> None:
            self.ids: list[str] = []

        async def write(self, episode) -> WriteReceipt:
            self.ids.append(episode.id)
            return WriteReceipt(episode_id=episode.id)

        async def read(self, query) -> RetrievalResult: # pragma: no cover
            return RetrievalResult(query=query, results=(), as_of=query.as_of)

        async def falsify(self, target, against=None) -> FalsificationVerdict: # pragma: no cover
            return FalsificationVerdict(target_id=str(target), superseded=False)

    sub = _Recording()
    receipts = asyncio.run(ingest_document(sub, p))
    assert sub.ids and all(i.startswith("doc#chunk") for i in sub.ids)
    assert len(receipts) == len(sub.ids)


def test_pdf_parser_reads_real_pdf() -> None:
    pytest.importorskip("pypdf")
    corpus = pathlib.Path(__file__).resolve().parents[1] / "demo" / "doc_demo_corpus"
    pdf = corpus / "acme_report_v1.pdf"
    if not pdf.exists():
        pytest.skip("demo PDF not present")
    episodes = document_to_episodes(pdf, reference_time=datetime(2019, 1, 1, tzinfo=timezone.utc))
    text = " ".join(e.content for e in episodes)
    assert "Boston" in text # extracted real PDF text
    assert episodes[0].id.startswith("acme_report_v1#chunk")
