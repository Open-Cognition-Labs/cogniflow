"""Cogniflow Playground API - the live backend for the web app's real-world test.

Upload real documents -> ingest through the ACTUAL Cogniflow pipeline (pypdf/markdown parse ->
Episodes -> temporal store) -> ask with an as-of time -> temporally-correct context + cited
answer + the audit/replay ledger. Each browser session is an isolated FalkorDB group.

Run (needs FalkorDB + .env with COGNIFLOW_LLM_* and COGNIFLOW_EMBEDDER_API_KEY):
    pip install -e ".[all,serve]"
    python cogniflow-api/main.py            # loopback + open (dev); warns loudly it is open

Baseline security (safe in a TRUSTED environment, NOT enterprise-ready - see SECURITY.md):
    COGNIFLOW_API_TOKENS=tok1,tok2          # require `Authorization: Bearer <tok>` on every route
                                           #   except /api/health; each session is scoped to the
                                           #   token that created it (no cross-tenant read/reset)
    COGNIFLOW_BIND_HOST=0.0.0.0            # expose off-host (refuses if open + non-loopback)
    COGNIFLOW_RATE_LIMIT_PER_MIN=30         # per-token/IP limit on the LLM/embedder endpoints
    COGNIFLOW_MAX_UPLOAD_BYTES=10485760     # upload cap; COGNIFLOW_PORT sets the port
"""

from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# make the src/ package importable when run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

from fastapi import (  # noqa: E402
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from cogniflow.backends.embedders import available_embedders  # noqa: E402
from cogniflow.backends.graphiti_falkordb import (  # noqa: E402
    GraphitiFalkorDBBackend,
    GraphitiFalkorDBConfig,
)
from cogniflow.context import serve_context  # noqa: E402
from cogniflow.documents import ingest_document  # noqa: E402
from cogniflow.generation import generate_answer  # noqa: E402
from cogniflow.generators import (  # noqa: E402
    OpenAICompatibleGenerator,
    available_generators,
    create_generator,
    create_generator_from_env,
)
from cogniflow.rerankers import available_rerankers  # noqa: E402
from cogniflow.serving.audit import serialize_belief, serialize_trace  # noqa: E402

DEFAULT_EMBEDDER = "bge-m3" if os.getenv("COGNIFLOW_EMBEDDER_API_KEY") else "hash"
# FalkorDB location for the raw admin pings (health/reset). The per-session backend reads the
# same env via config; keeping them consistent is what lets FalkorDB be a compose service.
_FALKOR_HOST = os.getenv("COGNIFLOW_FALKORDB_HOST", "localhost")
_FALKOR_PORT = int(os.getenv("COGNIFLOW_FALKORDB_PORT", "6379"))

app = FastAPI(title="Cogniflow Playground API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "COGNIFLOW_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# session_id -> {"config": {...}, "backend": GraphitiFalkorDBBackend | None, "owner": token|None}
_SESSIONS: dict[str, dict] = {}
_GENERATOR = None


# ---- security: baseline (Phase 4) ------------------------------------------
# "Safe to run in a TRUSTED ENVIRONMENT" - NOT enterprise-ready. This layer adds bearer-token
# auth, token-scoped session access (a caller touches only sessions its token owns), rate limits
# on the LLM/embedder endpoints, upload caps, and loopback-by-default binding. Enterprise controls
# (RBAC, access-audit logging, GDPR deletion, hardened multi-tenant isolation, SOC2) are OUT OF
# SCOPE by design; see SECURITY.md for the honest boundary.
_LOG = logging.getLogger("cogniflow.api")
_AUTH_TOKENS = {t.strip() for t in os.getenv("COGNIFLOW_API_TOKENS", "").split(",") if t.strip()}
_AUTH_OPEN = not _AUTH_TOKENS  # no tokens configured -> unauthenticated (dev) mode
_BIND_HOST = os.getenv("COGNIFLOW_BIND_HOST", "127.0.0.1")
_LOOPBACK = {"127.0.0.1", "localhost", "::1", ""}
_MAX_UPLOAD = int(os.getenv("COGNIFLOW_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))  # 10 MB
_ALLOWED_SUFFIXES = {".pdf", ".md", ".markdown", ".txt"}
_RATE_LIMIT = int(os.getenv("COGNIFLOW_RATE_LIMIT_PER_MIN", "30"))
_RATE_WINDOW = 60.0
_RATE: dict[str, list[float]] = {}
_SID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SECRET_KEYS = ("embedder_api_key", "reranker_api_key", "generator_api_key", "api_key")

# Fail-loud: an unauthenticated API on a non-loopback interface lets any caller read or wipe any
# session. Refuse to start unless explicitly overridden - never silently open on a public bind.
if _AUTH_OPEN and _BIND_HOST not in _LOOPBACK and os.getenv("COGNIFLOW_ALLOW_OPEN") != "1":
    raise RuntimeError(
        f"Refusing to start: no COGNIFLOW_API_TOKENS set AND binding non-loopback {_BIND_HOST!r}. "
        "An unauthenticated API on a public interface lets any caller read/wipe any session. Set "
        "COGNIFLOW_API_TOKENS, or bind 127.0.0.1, or (dev only, understood) COGNIFLOW_ALLOW_OPEN=1."
    )
if _AUTH_OPEN:
    _LOG.warning(
        "SECURITY: API running WITHOUT authentication (no COGNIFLOW_API_TOKENS). Anyone who can "
        "reach this port can read/reset any session. OK only on loopback for local dev - set "
        "COGNIFLOW_API_TOKENS before exposing beyond localhost."
    )
elif _BIND_HOST not in _LOOPBACK:
    _LOG.warning(
        "SECURITY: binding non-loopback %r - reachable off-host. Ensure network controls "
        "(firewall/VPC) in addition to the bearer token.", _BIND_HOST,
    )


async def require_auth(authorization: str = Header(default="")) -> str | None:
    """Bearer-token gate on every route except /api/health. Open (dev) mode returns None when no
    tokens are configured (startup warned loudly). With tokens set, a missing/invalid token is a
    401 - never silently open (fail-loud, like the embedder/generator plugs)."""
    if _AUTH_OPEN:
        return None
    scheme, _, tok = authorization.partition(" ")
    if scheme.lower() != "bearer" or tok not in _AUTH_TOKENS:
        raise HTTPException(
            401, "missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"}
        )
    return tok


def _guard(session_id: str, token: str | None) -> None:
    """Validate + authorize a session reference. Format-checks the id (prevents odd graph names),
    then enforces token-scoped ownership: a session is owned by the token that created it, and only
    that token may read/reset it. This closes the day-one hole (any caller wiping any tenant's
    graph). Open mode (token None) skips ownership - the whole API is unauthenticated there."""
    if not _SID_RE.match(session_id or ""):
        raise HTTPException(422, "invalid session_id (allowed: A-Za-z0-9_-, 1-64 chars)")
    if token is None:
        return
    sess = _SESSIONS.get(session_id)
    if sess is not None and sess.get("owner") not in (None, token):
        raise HTTPException(403, "forbidden: this session belongs to a different token")
    sess = _SESSIONS.setdefault(session_id, {"config": {}, "backend": None})
    sess.setdefault("owner", token)


def _rate_limit(request: Request, token: str | None) -> None:
    """Per-token (or per-IP) sliding-window limit on the endpoints that spend LLM/embedder money,
    so a burst is throttled (429) rather than a cost/availability bomb."""
    key = token or (request.client.host if request.client else "unknown")
    now = time.monotonic()
    hits = [t for t in _RATE.get(key, ()) if t > now - _RATE_WINDOW]
    if len(hits) >= _RATE_LIMIT:
        raise HTTPException(429, "rate limit exceeded; slow down", headers={"Retry-After": "60"})
    hits.append(now)
    _RATE[key] = hits


def _safe_config(config: dict) -> dict:
    """Config for a response with all secrets redacted - never echo a provider key back."""
    return {
        k: ("***" if (v and any(s in k for s in _SECRET_KEYS)) else v)
        for k, v in config.items()
        if k != "gen"
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    # accept ISO-8601 with a trailing "Z" (Python <3.11's fromisoformat rejects it)
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _generator():
    global _GENERATOR
    if _GENERATOR is None:
        _GENERATOR = create_generator_from_env()  # fail-loud if no key
    return _GENERATOR


def _build_generator(gen: dict) -> OpenAICompatibleGenerator:
    """Build a session generation model. A custom base_url (bring-your-own provider or a local
    model like Ollama/vLLM) goes straight to the OpenAI-compatible client - no preset and no key
    required (local endpoints ignore it). Otherwise use a named preset (fail-loud on bad name)."""
    base_url = (gen.get("base_url") or "").strip()
    if base_url:
        return OpenAICompatibleGenerator(
            api_key=(gen.get("api_key") or "").strip() or "local",
            model=(gen.get("model") or "").strip() or "local-model",
            base_url=base_url,
        )
    return create_generator(
        gen.get("name") or "nvidia",
        api_key=gen.get("api_key"),
        model=gen.get("model"),
    )


def _sess_generator(session_id: str):
    """The generation model for a session: a custom/selected plugin if configured, else the
    environment default. Built lazily and cached per session."""
    sess = _SESSIONS.get(session_id)
    gen = sess and sess["config"].get("gen")
    if sess and gen:
        if sess.get("generator") is None:
            sess["generator"] = _build_generator(gen)
        return sess["generator"]
    return _generator()


async def _backend(session_id: str) -> GraphitiFalkorDBBackend:
    if not session_id:
        raise HTTPException(422, "session_id required")
    sess = _SESSIONS.setdefault(session_id, {"config": {}, "backend": None})
    if sess["backend"] is None:
        c = sess["config"]
        cfg = GraphitiFalkorDBConfig.from_env(group_id=f"pg_{session_id}")
        # The seeded Acme hero + all audit/replay + hash retrieval are KEY-FREE, but graphiti's
        # OpenAI client requires *a* key at construction. Supply a placeholder when none is set so
        # those paths work with no .env; a real LLM CALL (ingest extraction, /answer generation)
        # still fails loud without a real key, so this never launders a missing credential.
        cfg.llm_api_key = cfg.llm_api_key or "unset-key-free-audit-and-seed-only"
        cfg.embedder = c.get("embedder", DEFAULT_EMBEDDER)
        if c.get("embedder_model"):
            cfg.embedder_model = c["embedder_model"]
        if c.get("embedder_base_url"):
            cfg.embedder_base_url = c["embedder_base_url"]
        if c.get("embedder_api_key"):
            cfg.embedder_api_key = c["embedder_api_key"]
        cfg.retrieval_policy = c.get("retrieval_policy", "default")
        cfg.retrieval_params = c.get("retrieval_params", {})
        backend = GraphitiFalkorDBBackend(cfg)
        await backend.setup()
        sess["backend"] = backend
    return sess["backend"]


async def _names(backend: GraphitiFalkorDBBackend, beliefs) -> dict[str, str]:
    uuids = [u for b in beliefs for u in b.provenance]
    return await backend.resolve_episodes(uuids) if uuids else {}


# ---- models ----------------------------------------------------------------
class Query(BaseModel):
    session_id: str
    query: str
    as_of: str | None = None
    top_k: int = 6


class TextIngest(BaseModel):
    session_id: str
    text: str
    title: str = "note"
    reference_time: str | None = None


class PluginConfig(BaseModel):
    session_id: str
    embedder: str | None = None
    reranker: str | None = None  # "" / None = off (default retrieval policy)
    # custom provider / local model (OpenAI-compatible base_url + model + key). Covers both
    # "bring your own API provider" and "point at a local model" (e.g. Ollama/vLLM).
    embedder_model: str | None = None
    embedder_base_url: str | None = None
    embedder_api_key: str | None = None
    reranker_model: str | None = None
    reranker_base_url: str | None = None
    reranker_api_key: str | None = None
    # generation model (AI model plugin) — selectable + custom/local endpoint
    generator: str | None = None
    generator_model: str | None = None
    generator_base_url: str | None = None
    generator_api_key: str | None = None


# ---- routes ----------------------------------------------------------------
@app.get("/api/health")
async def health() -> dict:
    falkordb = False
    try:
        from falkordb import FalkorDB

        FalkorDB(host=_FALKOR_HOST, port=_FALKOR_PORT).select_graph("__ping__").query("RETURN 1")
        falkordb = True
    except Exception:
        pass
    embedder_semantic = DEFAULT_EMBEDDER != "hash"
    warnings = []
    if not embedder_semantic:
        warnings.append(
            "Retrieval is non-semantic (hash embedder). Set COGNIFLOW_EMBEDDER=bge-m3 with "
            "COGNIFLOW_EMBEDDER_API_KEY (or bge-m3-local) for semantic recall - see the Quickstart."
        )
    return {
        "status": "ok",
        "falkordb": falkordb,
        "llm": bool(os.getenv("COGNIFLOW_LLM_API_KEY")),
        "embedder": DEFAULT_EMBEDDER,
        "embedder_semantic": embedder_semantic,
        "warnings": warnings,
    }


@app.get("/api/plugins", dependencies=[Depends(require_auth)])
async def plugins() -> dict:
    return {
        "embedders": available_embedders(),
        "rerankers": ["off", *available_rerankers()],
        "generators": available_generators(),
        "backends": ["falkordb", "neo4j"],
        "defaults": {"embedder": DEFAULT_EMBEDDER, "reranker": "off"},
    }


@app.post("/api/session")
async def new_session(token: str | None = Depends(require_auth)) -> dict:
    sid = uuid.uuid4().hex[:12]
    _SESSIONS[sid] = {"config": {}, "backend": None, "owner": token}
    return {"session_id": sid}


@app.post("/api/config")
async def set_config(cfg: PluginConfig, token: str | None = Depends(require_auth)) -> dict:
    _guard(cfg.session_id, token)
    sess = _SESSIONS.setdefault(cfg.session_id, {"config": {}, "backend": None})
    c = sess["config"]
    if cfg.embedder:
        c["embedder"] = cfg.embedder
        c["embedder_model"] = cfg.embedder_model
        c["embedder_base_url"] = cfg.embedder_base_url
        c["embedder_api_key"] = cfg.embedder_api_key
    if cfg.reranker is not None:
        if cfg.reranker in ("", "off", "default"):
            c["retrieval_policy"] = "default"
            c["retrieval_params"] = {}
        else:
            params: dict = {"reranker": cfg.reranker}
            if cfg.reranker_model:
                params["model"] = cfg.reranker_model
            if cfg.reranker_base_url:
                params["base_url"] = cfg.reranker_base_url
            if cfg.reranker_api_key:
                params["api_key"] = cfg.reranker_api_key
            c["retrieval_policy"] = "reranker"
            c["retrieval_params"] = params
    if cfg.generator == "managed":
        c.pop("gen", None)  # back to the platform default (env-configured)
        sess["generator"] = None
    elif cfg.generator:
        c["gen"] = {
            "name": cfg.generator,
            "model": cfg.generator_model,
            "base_url": cfg.generator_base_url,
            "api_key": cfg.generator_api_key,
        }
        sess["generator"] = None  # rebuild the generator on next answer
    # force rebuild with new config on next use
    if sess["backend"] is not None:
        await sess["backend"].close()
        sess["backend"] = None
    return {"ok": True, "config": _safe_config(sess["config"])}


@app.post("/api/ingest")
async def ingest(
    request: Request,
    session_id: str = Form(...),
    reference_time: str | None = Form(None),
    file: UploadFile = File(...),
    token: str | None = Depends(require_auth),
) -> dict:
    _guard(session_id, token)
    _rate_limit(request, token)
    # Validate BEFORE processing: reject wrong type / oversized upfront, before touching the
    # backend or spending parse/LLM resources.
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            415, f"unsupported file type {suffix or '(none)'}; allowed: {sorted(_ALLOWED_SUFFIXES)}"
        )
    data = await file.read(_MAX_UPLOAD + 1)  # bounded read (never load an unbounded file)
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(413, f"file too large; limit is {_MAX_UPLOAD} bytes")
    backend = await _backend(session_id)
    tmp = Path(tempfile.gettempdir()) / f"cf_{uuid.uuid4().hex}{suffix}"
    tmp.write_bytes(data)
    try:
        receipts = await ingest_document(backend, tmp, reference_time=_parse_dt(reference_time))
    finally:
        tmp.unlink(missing_ok=True)
    created = sum(len(r.created_belief_ids) for r in receipts)
    invalidated = sum(len(r.invalidated_belief_ids) for r in receipts)
    return {
        "document": file.filename,
        "chunks": len(receipts),
        "facts_created": created,
        "facts_superseded": invalidated,
    }


@app.post("/api/ingest-text")
async def ingest_text(
    body: TextIngest, request: Request, token: str | None = Depends(require_auth)
) -> dict:
    from cogniflow.core.types import Episode, utc_now

    _guard(body.session_id, token)
    _rate_limit(request, token)
    backend = await _backend(body.session_id)
    ref = _parse_dt(body.reference_time) or utc_now()
    ep = Episode(
        id=f"{body.title}-{uuid.uuid4().hex[:6]}",
        content=body.text,
        reference_time=ref,
        source="text",
        source_description=body.title,
        metadata={"valid_at_source": "provided" if body.reference_time else "none"},
    )
    receipt = await backend.write(ep)
    return {
        "document": body.title,
        "facts_created": len(receipt.created_belief_ids),
        "facts_superseded": len(receipt.invalidated_belief_ids),
    }


@app.post("/api/context")
async def context(q: Query, request: Request, token: str | None = Depends(require_auth)) -> dict:
    _guard(q.session_id, token)
    _rate_limit(request, token)
    backend = await _backend(q.session_id)
    res = await serve_context(backend, q.query, as_of=_parse_dt(q.as_of), top_k=q.top_k)
    return res.to_dict()


@app.post("/api/answer")
async def answer(q: Query, request: Request, token: str | None = Depends(require_auth)) -> dict:
    _guard(q.session_id, token)
    _rate_limit(request, token)
    backend = await _backend(q.session_id)
    res = await generate_answer(
        backend, q.query, _sess_generator(q.session_id), as_of=_parse_dt(q.as_of), top_k=q.top_k
    )
    return res.to_dict()


@app.get("/api/audit/current")
async def audit_current(session_id: str, token: str | None = Depends(require_auth)) -> dict:
    _guard(session_id, token)
    backend = await _backend(session_id)
    beliefs = await backend.event_time_query(datetime.now(timezone.utc))
    names = await _names(backend, beliefs)
    return {"beliefs": [serialize_belief(b, names) for b in beliefs]}


@app.get("/api/audit/event")
async def audit_event(
    session_id: str, as_of: str, token: str | None = Depends(require_auth)
) -> dict:
    _guard(session_id, token)
    backend = await _backend(session_id)
    beliefs = await backend.event_time_query(_parse_dt(as_of))
    names = await _names(backend, beliefs)
    return {"as_of": as_of, "beliefs": [serialize_belief(b, names) for b in beliefs]}


@app.get("/api/audit/replay")
async def audit_replay(
    session_id: str, system_time: str, token: str | None = Depends(require_auth)
) -> dict:
    _guard(session_id, token)
    backend = await _backend(session_id)
    beliefs = await backend.system_time_replay(_parse_dt(system_time))
    names = await _names(backend, beliefs)
    return {"system_time": system_time, "beliefs": [serialize_belief(b, names) for b in beliefs]}


@app.get("/api/audit/provenance/{belief_id}")
async def audit_provenance(
    belief_id: str, session_id: str, token: str | None = Depends(require_auth)
) -> dict:
    _guard(session_id, token)
    backend = await _backend(session_id)
    trace = await backend.provenance_trace(belief_id)
    uuids = list(trace.asserted_by) + (
        [trace.superseded_by_episode] if trace.superseded_by_episode else []
    )
    names = await backend.resolve_episodes(uuids) if uuids else {}
    return serialize_trace(trace, names)


@app.get("/api/audit/timeline/{belief_id}")
async def audit_timeline(
    belief_id: str, session_id: str, token: str | None = Depends(require_auth)
) -> dict:
    _guard(session_id, token)
    backend = await _backend(session_id)
    belief = await backend.get_belief(belief_id)
    if belief is None:
        raise HTTPException(404, "belief not found")
    trace = await backend.provenance_trace(belief_id)
    uuids = list(belief.provenance) + list(trace.asserted_by)
    if trace.superseded_by_episode:
        uuids.append(trace.superseded_by_episode)
    names = await backend.resolve_episodes(uuids) if uuids else {}
    return {"belief": serialize_belief(belief, names), "trace": serialize_trace(trace, names)}


# ---- guided demo: the Acme HQ bitemporal scenario --------------------------
# A seeded, deterministic fixture (no LLM, no network) so the system-time replay - the one
# thing plain RAG cannot do - is the first thing a visitor sees. The two facts are written
# with backdated created_at (system time = when the filing was learned), so replaying across a
# multi-year slider genuinely flips Boston->Denver at the 2022 correction. The REPLAY itself is
# the real engine (system_time_replay + reconstruct); only the fixture data is seeded.
_DEMO_SID = "demo_acme"
_C2019 = "2019-01-01T00:00:00+00:00"  # 2019 filing: learned + valid
_C2022 = "2022-01-01T00:00:00+00:00"  # 2022 filing: learned + valid; Boston ends here
_BOSTON_ID = "demo-belief-boston"
_DENVER_ID = "demo-belief-denver"
_EP_BOSTON = "demo-ep-boston-2019"
_EP_DENVER = "demo-ep-denver-2022"


async def _demo_payload(backend) -> dict:
    live = await backend.event_time_query(datetime.now(timezone.utc))
    names = await _names(backend, live)
    return {
        "session_id": _DEMO_SID,
        "boston_belief_id": _BOSTON_ID,
        "denver_belief_id": _DENVER_ID,
        "range": {"start": "2018-06-01", "end": "2024-06-01", "superseded_at": "2022-01-01"},
        "current": [serialize_belief(b, names) for b in live],
    }


@app.post("/api/demo/seed")
async def demo_seed(
    session_id: str = _DEMO_SID,
    force: bool = False,
    token: str | None = Depends(require_auth),
) -> dict:
    _guard(session_id, token)
    backend = await _backend(session_id)
    if not force:
        try:
            known = await backend.system_time_replay(datetime.now(timezone.utc))
            if any(b.id == _DENVER_ID for b in known):
                return await _demo_payload(backend)
        except Exception:
            pass
    # Seed onto a CLEAN graph so the hero is deterministic regardless of prior/partial state
    # (a container restart, a half-seed). Drop the group, then rebuild the backend on it.
    sess = _SESSIONS.get(session_id)
    if sess and sess["backend"] is not None:
        await sess["backend"].close()
        sess["backend"] = None
    try:
        from falkordb import FalkorDB

        FalkorDB(host=_FALKOR_HOST, port=_FALKOR_PORT).select_graph(f"pg_{session_id}").delete()
    except Exception:
        pass
    backend = await _backend(session_id)
    gid = backend.group_id
    drv = backend._driver
    for node_uuid, node_name in (
        ("demo-ent-acme", "Acme Corp"),
        ("demo-ent-boston", "Boston"),
        ("demo-ent-denver", "Denver"),
    ):
        await drv.execute_query(
            "MERGE (n:Entity {uuid:$u}) SET n.name=$name, n.group_id=$gid",
            u=node_uuid, name=node_name, gid=gid,
        )
    for ep_uuid, ep_name in (
        (_EP_BOSTON, "Acme Corp - 2019 annual report"),
        (_EP_DENVER, "Acme Corp - 2022 press release"),
    ):
        await drv.execute_query(
            "MERGE (n:Episodic {uuid:$u}) SET n.name=$name, n.group_id=$gid",
            u=ep_uuid, name=ep_name, gid=gid,
        )
    await drv.execute_query(
        "MATCH (a:Entity {uuid:$s}), (b:Entity {uuid:$t}) "
        "MERGE (a)-[r:RELATES_TO {uuid:$id}]->(b) "
        "SET r.fact=$fact, r.name=$pred, r.group_id=$gid, r.created_at=$c, r.valid_at=$v, "
        "r.invalid_at=$iv, r.expired_at=$ex, r.episodes=$eps, r.superseded_by=$sb, "
        "r.superseded_by_episode=$sbe, r.valid_at_source=$src",
        s="demo-ent-acme", t="demo-ent-boston", id=_BOSTON_ID,
        fact="Acme Corp is headquartered in Boston", pred="HEADQUARTERED_IN", gid=gid,
        c=_C2019, v=_C2019, iv=_C2022, ex=_C2022, eps=[_EP_BOSTON],
        sb=_DENVER_ID, sbe=_EP_DENVER, src="provided",
    )
    await drv.execute_query(
        "MATCH (a:Entity {uuid:$s}), (b:Entity {uuid:$t}) "
        "MERGE (a)-[r:RELATES_TO {uuid:$id}]->(b) "
        "SET r.fact=$fact, r.name=$pred, r.group_id=$gid, r.created_at=$c, r.valid_at=$v, "
        "r.episodes=$eps, r.valid_at_source=$src "
        "REMOVE r.invalid_at, r.expired_at, r.superseded_by, r.superseded_by_episode",
        s="demo-ent-acme", t="demo-ent-denver", id=_DENVER_ID,
        fact="Acme Corp is headquartered in Denver", pred="HEADQUARTERED_IN", gid=gid,
        c=_C2022, v=_C2022, eps=[_EP_DENVER], src="provided",
    )
    return await _demo_payload(backend)


@app.post("/api/reset")
async def reset(session_id: str, token: str | None = Depends(require_auth)) -> dict:
    _guard(session_id, token)
    sess = _SESSIONS.get(session_id)
    if sess and sess["backend"] is not None:
        await sess["backend"].close()
    try:
        from falkordb import FalkorDB

        FalkorDB(host=_FALKOR_HOST, port=_FALKOR_PORT).select_graph(f"pg_{session_id}").delete()
    except Exception:
        pass
    # keep config + OWNERSHIP across a reset (else another token could re-claim the session)
    _SESSIONS[session_id] = {
        "config": sess["config"] if sess else {},
        "backend": None,
        "owner": (sess.get("owner") if sess else None) or token,
    }
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    # Loopback by default; set COGNIFLOW_BIND_HOST to expose. The module-level guard above
    # refuses to start unauthenticated on a non-loopback interface unless COGNIFLOW_ALLOW_OPEN=1.
    uvicorn.run(app, host=_BIND_HOST, port=int(os.getenv("COGNIFLOW_PORT", "8000")))
