# The generation layer - closing the RAG loop

Cogniflow serves context (A.3) so any model can answer. The generation layer is the
**optional** convenience that answers *itself*: documents in -> temporally-correct,
provenance-cited answer out. It sits **on** the context API - it does not replace it. A caller
picks the surface:

- **context out** (`serve_context` / `/context` / `get_context`) - bring your own model, or
- **answer out** (`generate_answer` / `/answer` / `get_answer`) - Cogniflow generates.

Thin and optional; the model-agnostic core survives. No core change; read-only.

## Two load-bearing properties

### A - Temporal correctness survives generation (the centerpiece)
The context is already as-of-filtered, so the answer is as-of-correct **by construction** -
*provided* the LLM answers only from the served context and is told to ignore its own
training. The prompt does exactly that ("Use ONLY the context facts", "TRUST THE CONTEXT",
"do not guess"). Proven live: Tesla HQ moved Palo Alto -> Austin (2021), the generation
model's training knows Austin, yet asked **as of 2018** the answer is **Palo Alto** (from the
2018 context), not Austin. The answer un-knows what the context un-knows - the milestone invariant at the generation step.

### B - The answer does not launder the extraction floor
The end-to-end run showed structured (OKF fact-key) extraction is deterministic while prose
extraction is LLM-bounded. So an answer built on prose-extracted facts inherits that
uncertainty. The generation response carries the `valid_at_source` confidence histogram
(`{"authoritative": n, "derived": m, "none": k}`) and the per-fact labels, so a confident
sentence on LLM-extracted prose is not mistaken for one on deterministic structured facts.

## The contract (G1)

`generate_answer(substrate, query, generator, *, as_of=None, top_k=5, ...) -> GenerationResult`:

| field | meaning |
|---|---|
| `answer` | the cited answer, generated ONLY from the served context |
| `facts` | the served facts it was built from (each with `valid_at_source` + provenance) |
| `as_of` | the instant the answer was resolved at |
| `generator_model` | which generation LLM produced it (model-agnostic) |
| `confidence` | the `valid_at_source` histogram (B: the floor, surfaced) |

`to_dict()` yields JSON; the `facts` carry provenance so the answer is **audit-traceable**
(T4) - answer -> facts -> documents.

## The generation-LLM plug (model-agnostic, fail-loud)

The answer-producing LLM is a plug, like the embedder:
`create_generator("nvidia" | "minimax" | "openai", api_key=..., model=..., base_url=...)`, or
`create_generator_from_env()` (reads `COGNIFLOW_GENERATOR*`, falling back to `COGNIFLOW_LLM_*`).
One OpenAI-compatible client covers NVIDIA/MiniMax/OpenAI and any compatible endpoint
(including a self-hosted/local model for the VPC wedge). **Fail-loud**: a missing key or an
unknown name raises at construction - never a silent no-op. Dependency-light (stdlib HTTP), so
the generation core carries no LLM-SDK dependency.

### Swapping the generation model requires re-running the centerpiece test

This is the one place the temporal guarantee becomes **model-dependent**, so read before you
swap. Temporal correctness has two halves with different guarantees:

- **As-of filtering is deterministic and guaranteed.** The wrong (future) fact is never in the
  served context - `serve_context` filtered it out. This half does not depend on the model.
- **Prompt adherence is probabilistic and model-dependent.** Whether the model honors the
  "answer only from context, ignore your training" constraint - instead of overriding the
  context with what its training knows - rides on the specific model. A weaker model may leak
  training knowledge into a past answer even though the wrong fact was never in the context.

Therefore: **swapping the generation model (via the plug) requires re-running the centerpiece
test** (`tests/integration/test_generation_live.py::test_temporal_correctness_survives_generation`)
against the new model. It is the adversarial case - a fact the model's training gets wrong for
a past date (Tesla HQ = Palo Alto as of 2018, not the training-known Austin). If the new model
still answers from the context, the guarantee holds for it; if not, it is not a safe generation
model for this product without prompt hardening. The centerpiece is not free with a new model.

## Faithfulness (T5)
The answer is grounded in the served context; asked something the context cannot answer, it
declines rather than inventing a fact (an invention would break the provenance chain). Tested
live.

## Both surfaces, self-hostable
```python
from cogniflow.serving import create_app, build_mcp_server
from cogniflow.generators import create_generator_from_env

gen = create_generator_from_env()
app = create_app(substrate, gen) # /context (always) + /answer (with a generator)
mcp = build_mcp_server(substrate, gen) # get_context (always) + get_answer (with a generator)
```
Without a generator, only the context surface is mounted - the model-agnostic core stands
alone. Read-only throughout; generation never writes to the store.
