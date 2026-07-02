"""The audit/replay dashboard surface - the moat made visible.

A READ-ONLY window onto the belief ledger for a HUMAN (compliance/audit reader), distinct
from the context API (A.3, which serves context to models). It exposes the four AuditLedger
methods over HTTP and ships a dependency-free dashboard that renders:

 - current beliefs (what the system holds true now),
 - the event-time axis ("what was TRUE as of T" - the recognizable March=7-day/June=28-day),
 - the system-time replay ("what the system KNEW as of S") - the centerpiece, which must
    render the un-knowing correctly: scrubbed to before a supersession, a fact reads
    believed-then and un-superseded, NOT with its current invalid_at. The engine un-knows
    (system_time_replay -> reconstruct_as_of_system); this layer must only faithfully render
    what the engine returns and never recompute intervals client-side, or it re-leaks
    present knowledge into the past.
 - provenance, with human-readable names resolved from stored linkage (UUID shown, never
    guessed, when a name is unavailable).

Read-only by construction: no write verb is exposed. Behind the ``[serve]`` extra,
self-hostable (loopback by default), so the ledger never leaves the reader's environment.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..context import _normalize_source
from ..core.types import Belief, ProvenanceTrace
from ._dashboard import DASHBOARD_HTML

try:
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.responses import HTMLResponse
except ImportError as e: # pragma: no cover
    raise RuntimeError(
        "The audit dashboard needs the 'serve' extra: pip install 'cogniflow-rag[serve]'"
    ) from e


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _resolve_one(uuid: str, names: dict[str, str]) -> dict[str, Any]:
    name = names.get(uuid)
    # honesty: if stored linkage has no name, show the UUID - never guess a source name.
    return {"uuid": uuid, "name": name, "display": name or uuid, "resolved": name is not None}


def serialize_belief(belief: Belief, names: dict[str, str]) -> dict[str, Any]:
    raw = belief.metadata.get("valid_at_source")
    return {
        "belief_id": belief.id,
        "statement": belief.statement,
        "valid_at": _iso(belief.valid_at),
        "invalid_at": _iso(belief.invalid_at), # rendered verbatim; replay already un-knew it
        "expired_at": _iso(belief.expired_at),
        "created_at": _iso(belief.created_at),
        "valid_at_source": _normalize_source(raw), # T3/#6: confidence visible to the human
        "valid_at_source_raw": raw,
        "superseded_by": belief.metadata.get("superseded_by"),
        "provenance": [_resolve_one(u, names) for u in belief.provenance],
    }


def serialize_trace(trace: ProvenanceTrace, names: dict[str, str]) -> dict[str, Any]:
    return {
        "belief_id": trace.belief_id,
        "asserted_by": [_resolve_one(u, names) for u in trace.asserted_by],
        "superseded_by_belief": trace.superseded_by_belief,
        "superseded_by_episode": (
            _resolve_one(trace.superseded_by_episode, names)
            if trace.superseded_by_episode
            else None
        ),
        "invalid_at": _iso(trace.invalid_at),
        "expired_at": _iso(trace.expired_at),
    }


async def _resolve_names(ledger: Any, beliefs: list[Belief]) -> dict[str, str]:
    resolver = getattr(ledger, "resolve_episodes", None)
    if resolver is None:
        return {}
    uuids = [u for b in beliefs for u in b.provenance]
    return await resolver(uuids) if uuids else {}


def _parse_dt(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"invalid datetime: {value!r}") from e
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def create_audit_app(ledger: Any) -> FastAPI:
    """Build the read-only audit dashboard + API over ``ledger`` (an AuditLedger).

    ``ledger`` must provide the four AuditLedger coroutines; ``resolve_episodes`` and
    ``get_belief`` are used when present. The app exposes no write verb.
    """
    app = FastAPI(title="Cogniflow Audit Dashboard", version="0.1.0")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/audit/current")
    async def current() -> dict[str, Any]:
        beliefs = await ledger.event_time_query(datetime.now(timezone.utc))
        names = await _resolve_names(ledger, beliefs)
        return {"beliefs": [serialize_belief(b, names) for b in beliefs]}

    @app.get("/audit/event")
    async def event(as_of: str = Query(...)) -> dict[str, Any]:
        """Event-time axis: what was TRUE as of the given instant."""
        beliefs = await ledger.event_time_query(_parse_dt(as_of))
        names = await _resolve_names(ledger, beliefs)
        return {
            "as_of": as_of,
            "axis": "event_time",
            "beliefs": [serialize_belief(b, names) for b in beliefs],
        }

    @app.get("/audit/replay")
    async def replay(system_time: str = Query(...)) -> dict[str, Any]:
        """System-time axis (the centerpiece): what the system KNEW as of the instant, with
        the un-knowing applied by the engine. Intervals are rendered exactly as returned."""
        beliefs = await ledger.system_time_replay(_parse_dt(system_time))
        names = await _resolve_names(ledger, beliefs)
        return {
            "system_time": system_time,
            "axis": "system_time",
            "beliefs": [serialize_belief(b, names) for b in beliefs],
        }

    @app.get("/audit/bitemporal")
    async def bitemporal(
        system_time: str = Query(...), event_time: str = Query(...)
    ) -> dict[str, Any]:
        beliefs = await ledger.bitemporal_query(_parse_dt(system_time), _parse_dt(event_time))
        names = await _resolve_names(ledger, beliefs)
        return {
            "system_time": system_time,
            "event_time": event_time,
            "beliefs": [serialize_belief(b, names) for b in beliefs],
        }

    @app.get("/audit/provenance/{belief_id}")
    async def provenance(belief_id: str) -> dict[str, Any]:
        trace = await ledger.provenance_trace(belief_id)
        uuids = list(trace.asserted_by) + (
            [trace.superseded_by_episode] if trace.superseded_by_episode else []
        )
        resolver = getattr(ledger, "resolve_episodes", None)
        names = await resolver(uuids) if (resolver and uuids) else {}
        return serialize_trace(trace, names)

    @app.get("/audit/timeline/{belief_id}")
    async def timeline(belief_id: str) -> dict[str, Any]:
        getter = getattr(ledger, "get_belief", None)
        belief = await getter(belief_id) if getter else None
        if belief is None:
            raise HTTPException(status_code=404, detail="belief not found")
        names = await _resolve_names(ledger, [belief])
        trace = await ledger.provenance_trace(belief_id)
        return {"belief": serialize_belief(belief, names), "trace": serialize_trace(trace, names)}

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        return DASHBOARD_HTML

    return app


def run(ledger: Any, *, host: str = "127.0.0.1", port: int = 8078) -> None:
    """Serve the dashboard locally (loopback by default - the ledger never leaves)."""
    import uvicorn

    uvicorn.run(create_audit_app(ledger), host=host, port=port)

