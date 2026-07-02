# Document ingestion - parser decision 

Cogniflow's second front door ingests arbitrary documents (text, markdown, PDF) into the
temporal store via the same Episode/`write` path OKF uses. This records the parser
decisions, made deliberately.

## Decision A - ColPali / image-based indexing is OUT (a deliberate non-fit)

The 2026 frontier for visually-rich PDFs is **image-based indexing** (ColPali / ColQwen):
index page *images* with a vision-language model, skip OCR and chunking. It beats text
pipelines on plain document RAG. **It is incompatible with Cogniflow**, for a fundamental
reason: ColPali produces page-image embeddings, and **you cannot attach a validity
interval (`valid_at` / `invalid_at`) to an image embedding.** The engine operates on
*facts* - text statements carrying temporal validity and provenance. Facts require text.
So the text-extraction path is correct **for this architecture** - not because it is more
advanced (it isn't), but because the differentiator (the temporal layer) needs facts, and
facts need text. When the SOTA technique and the moat point in opposite directions, follow
the moat.

## Decision B - take the parser, not the framework

`RAG-Anything` is a complete RAG framework (its own storage, retrieval, cross-modal graph)
with **zero temporal awareness**; adopting its graph would undermine ours. Its value over
raw **MinerU** (which it wraps) is exactly the cross-modal graph - the part we would
discard. So: use a *parser* only, behind a pluggable `DocumentParser` interface, and never
adopt a framework's storage/retrieval/graph.

## Chosen parsers (pluggable, optional extras)

| Parser | Role | Dependency |
|---|---|---|
| `TextParser` | .txt / .md | none (stdlib) |
| `PdfParser` (pypdf) | **default** PDF text + tables-as-text | `[documents]` (pypdf) |
| `MinerUParser` | **production** layout-aware PDF (structured tables, figures, reading order) | `[mineru]` (multi-GB vision/layout stack) |

**Why pypdf is the default and MinerU is opt-in:** MinerU is the better production parser
for visually-rich enterprise PDFs, but it pulls a multi-GB model stack and is not
something an OKF-or-markdown-only user should carry. pypdf is small, pure-Python, and
competent for text-bearing PDFs, so it is the default behind the `[documents]` extra;
MinerU drops into the *same* `DocumentParser` interface as the documented production
upgrade. Heavy deps are never core.

**Validation note (honest):** MinerU's full stack was not run in this build environment
(multi-GB models); the interface, the pypdf default, and the MinerU adapter seam are in
place and the pypdf path is verified live on real PDFs. Run MinerU on representative
enterprise PDFs before relying on it in production, and compare against pypdf + the chunker
before reaching for RAG-Anything's heavier decomposition.

## Extraction reliability (honest, measured)

Raw documents go through the engine's prose extraction (`add_episode`), not an explicit
`fact` triple. Measured in this environment (MiniMax-M3 + a local deterministic embedder):
extraction is **reliable for concrete factual statements** (e.g. "Acme Corp is
headquartered in Boston" -> a `HEADQUARTERED_IN` fact that supersedes correctly across
document versions) and **weak for abstract definitional prose** (it may extract no fact).
This is the documented limit of the document front door; the deterministic path for
precise temporal facts remains structured input (OKF's `fact` extension key). A stronger
extraction model raises this floor without any core change.
