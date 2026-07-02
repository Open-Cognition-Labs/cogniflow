"""Document ingestion - the second front door .

Any document (text, markdown, PDF) -> parse -> structure-preserving chunks -> Episodes
-> the existing substrate ``write`` path -> temporal store. Identical boundary to OKF;
touches no core; it is a pure producer.

Two architectural decisions (see docs/DOCUMENT_INGESTION.md):
  A. ColPali / image-based indexing is OUT - you cannot attach a validity interval to a
     page-image embedding. The temporal model needs *facts*, facts need *text*, so the
     text-extraction path is correct for this architecture.
  B. Take the parser, not the framework. Parsed content -> Episodes; never adopt a
     parser framework's own storage/retrieval/graph. The parser is pluggable
     (``DocumentParser``); a lightweight pypdf parser is the default, MinerU is the
     documented production adapter, both behind optional extras.

Temporal honesty: documents carry a weaker temporal signal than OKF. ``valid_at`` is
derived from document metadata or a caller-provided reference time and LABELED
(``valid_at_source``); dates inside the text are left to the engine's extraction; with
no signal the fact arrives time-less. Document identity flows into provenance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from .core.contracts import AsyncSubstrate
from .core.types import Episode, WriteReceipt, utc_now

_HEADING = re.compile(r"^#{1,6}\s+\S")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


@dataclass
class DocBlock:
    """A structural unit of a parsed document. ``kind`` guides chunking (a table is
    never split; a heading attaches to the following block)."""

    kind: str # "heading" | "paragraph" | "table" | "text"
    text: str


@runtime_checkable
class DocumentParser(Protocol):
    def parse(self, path: str | Path) -> list[DocBlock]: ...


def _blocks_from_text(text: str) -> list[DocBlock]:
    """Split plain text / markdown into heading / table / paragraph blocks."""
    blocks: list[DocBlock] = []
    table: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        if para:
            blocks.append(DocBlock("paragraph", "\n".join(para).strip()))
            para.clear()

    def flush_table() -> None:
        if table:
            blocks.append(DocBlock("table", "\n".join(table).strip()))
            table.clear()

    for line in text.splitlines():
        if _TABLE_ROW.match(line):
            flush_para()
            table.append(line)
            continue
        flush_table()
        if not line.strip():
            flush_para()
        elif _HEADING.match(line):
            flush_para()
            blocks.append(DocBlock("heading", line.strip()))
        else:
            para.append(line)
    flush_para()
    flush_table()
    return blocks


class TextParser:
    """Parser for .txt / .md (no heavy deps)."""

    def parse(self, path: str | Path) -> list[DocBlock]:
        return _blocks_from_text(Path(path).read_text(encoding="utf-8"))


class PdfParser:
    """Default PDF parser via pypdf (optional ``[documents]`` extra). Extracts text per
    page; PDF tables come through as text (structured-table extraction is MinerU's job)."""

    def parse(self, path: str | Path) -> list[DocBlock]:
        try:
            from pypdf import PdfReader
        except ImportError as e: # pragma: no cover
            raise RuntimeError(
                "PDF ingestion needs the 'documents' extra: pip install 'cogniflow-rag[documents]'"
            ) from e
        blocks: list[DocBlock] = []
        for page in PdfReader(str(path)).pages:
            blocks.extend(_blocks_from_text(page.extract_text() or ""))
        return blocks


class MinerUParser:
    """Production PDF parser adapter (optional ``[mineru]`` extra).

    MinerU performs layout-aware extraction (structured tables, figures, reading order)
    far beyond pypdf, but ships a multi-GB vision/layout stack, so it is opt-in. This
    adapter conforms to the same ``DocumentParser`` interface - take the parser, not the
    framework. (Wired as the documented production upgrade; pypdf is the default.)
    """

    def parse(self, path: str | Path) -> list[DocBlock]: # pragma: no cover - heavy optional
        try:
            import mineru  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "MinerU not installed. Install the 'mineru' extra, or use the default "
                "pypdf PdfParser. See docs/DOCUMENT_INGESTION.md."
            ) from e
        raise NotImplementedError(
            "MinerU adapter is a documented production seam; wire its parse() output to "
            "DocBlocks here. The default pypdf parser is used in this build."
        )


def get_parser(path: str | Path) -> DocumentParser:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        return PdfParser()
    return TextParser() # .txt, .md, and anything text-like


def chunk_blocks(blocks: list[DocBlock], max_chars: int = 1200) -> list[str]:
    """Pack blocks into Episode-sized chunks, preserving structure:

 - a ``table`` block is emitted whole, never split or merged into prose,
 - a ``heading`` stays attached to the block(s) that follow it,
 - prose accumulates up to ``max_chars`` before a new chunk starts.
    """
    chunks: list[str] = []
    buf: list[str] = []
    pending_heading: str | None = None

    def flush() -> None:
        if buf:
            chunks.append("\n\n".join(buf).strip())
            buf.clear()

    for block in blocks:
        if block.kind == "table":
            flush()
            table = f"{pending_heading}\n\n{block.text}" if pending_heading else block.text
            chunks.append(table.strip()) # whole table = one chunk
            pending_heading = None
            continue
        if block.kind == "heading":
            flush()
            pending_heading = block.text
            continue
        piece = f"{pending_heading}\n\n{block.text}" if pending_heading else block.text
        pending_heading = None
        current = sum(len(b) for b in buf)
        if buf and current + len(piece) > max_chars:
            flush()
        buf.append(piece)
    flush()
    return [c for c in chunks if c]


def _derive_valid_at(
    path: Path, reference_time: datetime | None
) -> tuple[datetime | None, str]:
    if reference_time is not None:
        return reference_time, "provided"
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc), "document:mtime"
    except OSError: # pragma: no cover
        return None, "none"


def document_to_episodes(
    path: str | Path,
    *,
    reference_time: datetime | None = None,
    parser: DocumentParser | None = None,
    max_chars: int = 1200,
) -> list[Episode]:
    """Parse + chunk a document into Episodes for the prose (``add_episode``) write path.

    No ``fact`` triple is asserted for raw documents; the engine extracts facts from the
    chunk text. ``valid_at`` is derived and labeled; document identity (the file stem +
    chunk index) flows into provenance via the Episode id.
    """
    path = Path(path)
    parser = parser or get_parser(path)
    valid_at, valid_src = _derive_valid_at(path, reference_time)
    doc_id = path.stem
    chunks = chunk_blocks(parser.parse(path), max_chars=max_chars)
    episodes: list[Episode] = []
    for i, chunk in enumerate(chunks):
        episodes.append(
            Episode(
                id=f"{doc_id}#chunk{i}", # identity -> provenance
                content=chunk,
                reference_time=valid_at or utc_now(),
                source="document",
                source_description=path.name,
                metadata={
                    "doc_id": doc_id,
                    "doc_path": str(path),
                    "chunk_index": i,
                    "valid_at_source": valid_src, # honesty label: derived, not authoritative
                },
            )
        )
    return episodes


async def ingest_document(
    substrate: AsyncSubstrate,
    path: str | Path,
    *,
    reference_time: datetime | None = None,
    parser: DocumentParser | None = None,
    max_chars: int = 1200,
) -> list[WriteReceipt]:
    """Ingest one document through the existing substrate write path.

    Cross-version supersession is free: re-ingesting an updated document whose facts
    changed triggers the engine's contradiction resolution (best-effort, via the engine's
    text extraction - reliable for concrete factual statements, see docs)."""
    episodes = document_to_episodes(
        path, reference_time=reference_time, parser=parser, max_chars=max_chars
    )
    receipts: list[WriteReceipt] = []
    for episode in episodes:
        receipts.append(await substrate.write(episode))
    return receipts
