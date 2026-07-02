# Cogniflow Playground API

The live backend for the web app's real-world test: upload real documents → ingest through
the actual Cogniflow pipeline → ask with an as-of time → temporally-correct context + cited
answer + the audit/replay ledger. Each browser session is an isolated FalkorDB group.

## Run

```bash
# from the repo root, with the venv active
pip install -e ".[all,serve]" # graphiti + falkordb + fastapi + multipart + ...
# start FalkorDB (Docker): docker run -d -p 6379:6379 falkordb/falkordb:latest
python cogniflow-api/main.py # serves http://127.0.0.1:8000
```

Needs a `.env` (repo root) with `COGNIFLOW_LLM_*` and (for real semantic recall)
`COGNIFLOW_EMBEDDER_API_KEY`. Point the web app at it with
`NEXT_PUBLIC_API_URL=http://localhost:8000` (the default).

## Endpoints (prefix `/api`)

| method | path | purpose |
|---|---|---|
| GET | `/health` | falkordb / llm / embedder status |
| GET | `/plugins` | available embedders / rerankers / generators / backends |
| POST | `/session` | new isolated session |
| POST | `/config` | set session embedder / reranker |
| POST | `/ingest` | multipart file upload → ingest (PDF/md/text) |
| POST | `/ingest-text` | ingest a pasted fact/snippet with a valid-from date |
| POST | `/context` | temporally-correct context (facts) for a query + `as_of` |
| POST | `/answer` | cited, temporally-correct answer + confidence |
| GET | `/audit/current` `/audit/event` `/audit/replay` `/audit/provenance/{id}` | the ledger |
| POST | `/reset` | wipe the session's store |

Read-only for the serve/audit surfaces; ingestion is the only write path. CORS is limited to
the web origin (`COGNIFLOW_CORS_ORIGINS`, default `http://localhost:3000`).
