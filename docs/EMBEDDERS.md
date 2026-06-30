# Embedders - config-selected, fail-loud, bring-your-own

The embedder is a pluggable layer, like backends and policies: selected by config name, not
by editing code. The hash embedder stays the key-free default; a real embedder is opt-in.

## The contract (G1)

Every embedder is a Graphiti `EmbedderClient` that provides:
- `create(text) -> vector` and `create_batch(texts) -> vectors`, and
- **its dimension**, carried on the instance (`embedding_dim`), not assumed by the store.

The dimension-carrying is the contract detail that makes "any embedder" safe: the store
validates it at startup (safety property B) instead of trusting a hard-coded value.

## Selection (config-driven, not code-driven)

| config `embedder` | implementation | key needed |
|---|---|---|
| `hash` (default) | `LocalDeterministicEmbedder` - non-semantic, SHA-256-derived | none |
| `bge-m3` | NVIDIA API, model `baai/bge-m3` (1024-dim) | `COGNIFLOW_EMBEDDER_API_KEY` |
| `nvidia-e5` | NVIDIA API, model `nvidia/nv-embedqa-e5-v5` (1024-dim) | `COGNIFLOW_EMBEDDER_API_KEY` |

Set it via env (`COGNIFLOW_EMBEDDER=bge-m3`) or `GraphitiFalkorDBConfig(embedder="bge-m3")`.
Extensible to `openai`, `sentence-transformers`, or a self-hosted BGE-M3 later with no code
change to callers - just another registry entry. Override the model string with
`COGNIFLOW_EMBEDDER_MODEL` / the `embedder_model` config field.

## Safety property A - fail-loud, never silent fallback to hash

Selecting a real embedder with **no API key**, an **unknown name**, or an **excluded model**
raises `EmbedderError` at construction. It never quietly drops to the hash embedder, because a
silent fallback gives meaning-blind retrieval that still returns results - no error, just
silently wrong answers, the worst failure mode for a retrieval system.

## Safety property B - dimension validated, hard-crash on mismatch

The embedder carries its dimension; `check_embedding_dimension` compares it to the vectors
already in the store at `setup()` and raises `EmbedderDimensionMismatch` on a mismatch. Mixing
dimensions silently corrupts the vector space (cross-dimension comparisons are meaningless). An
empty or undetectable store is a no-op - there is nothing yet to corrupt.

## Model policy

**Default `baai/bge-m3`** - it is the self-hosted production target, so end-to-end results now
reflect what ships; later, swap the same `EmbedderClient` to a locally-hosted BGE-M3 with a
config change only (completing the in-VPC wedge). Dense + sparse + multi-vector retrieval fits
the hybrid (vector + BM25) story.

**Proven fallback `nvidia/nv-embedqa-e5-v5`** - purpose-built for QA retrieval; use if BGE-M3
shows latency/quality wobble.

**Excluded, deliberately:**
- `nvidia/nv-embed-v1` - **non-commercial license**; it would poison open-source/enterprise
  adoption, so it is never a default or a selectable option (selecting it raises).
- `llama-nemotron-embed-1b-v2` (multilingual-focused) and `embed-vl` (multimodal image) - the
  wrong shape for a text-fact temporal model (same reason ColPali is out: the engine needs
  text facts with validity, not image/multilingual-specialized vectors).

## Correctness tests stay on hash

The temporal-correctness / invariant tests do not depend on embeddings and stay pinned to the
hash embedder - deterministic and key-free. Real embedders are exercised only on the
end-to-end and demo paths.

## End-to-end finding: what the real embedder did and did not fix

Measured on the OKF path with BGE-M3 (same MiniMax-M3 extraction LLM, controlled
hash-vs-bge comparison):

- **Retrieval (fixed):** paraphrases with near-zero lexical overlap with the stored fact
  ("How do we count our recently engaged user base?") retrieve the right fact ranked #1.
  Under the hash embedder (BM25-lexical only) they do not match at all. Real semantic recall
  is the embedder's payoff.
- **Prose-extraction floor (NOT fixed - hypothesis falsified):** the abstract definitional
  sentence that extracted nothing in A.2 still extracts nothing under BGE-M3 (hash: 0 edges;
  bge-m3: 0 edges). The floor is the **extraction LLM**, not the embedder - embeddings only
  affect dedup/recall *after* the LLM proposes entities/edges. The lever for prose extraction
  is a stronger extraction model; the deterministic path for precise temporal facts remains
  structured input (OKF `fact` keys / triples), which works regardless of embedder.
