"""GraphitiFalkorDBBackend - the canonical async Substrate.

Wraps graphiti-core (bi-temporal knowledge graph) on a FalkorDB driver and adapts
it to the cogniflow ``AsyncSubstrate`` contract (write / read / falsify). The LLM
is configurable (any OpenAI-compatible endpoint); embeddings use a local
deterministic embedder so no embedding key is required.

This module imports graphiti-core and falkordb, so it is imported only when the
backend is actually used (never from ``cogniflow.backends.__init__``), keeping the
core import-free.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.driver.neo4j_driver import Neo4jDriver
from graphiti_core.edges import EntityEdge
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.nodes import EntityNode, EpisodeType
from graphiti_core.search.search_filters import ComparisonOperator, DateFilter, SearchFilters

from ..core.audit import bitemporal_query as _bitemporal_query
from ..core.audit import event_time_query as _event_time_query
from ..core.audit import system_time_replay as _system_time_replay
from ..core.policies import RetrievalPolicy, ValidityPolicy, rank_valid
from ..core.types import (
    Belief,
    Episode,
    FalsificationVerdict,
    ProvenanceTrace,
    RetrievalQuery,
    RetrievalResult,
    WriteReceipt,
)
from ..observability import log_read
from ..registry import create_policy
from ._local_embedder import LocalDeterministicEmbedder


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class GraphitiFalkorDBConfig:
    """Connection + model configuration for the backend."""

    host: str = "localhost"
    port: int = 6379
    group_id: str = "cogniflow"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    embedding_dim: int = 1024
    # L3 policy selection by name (fail-loud via the registry).
    validity_policy: str = "strict"
    validity_params: dict[str, Any] = field(default_factory=dict)
    # Reranking is OFF by default ("default" = passthrough). Opt in per deployment
    # (e.g. "recency"); validity-filtering always runs first (see read()).
    retrieval_policy: str = "default"
    retrieval_params: dict[str, Any] = field(default_factory=dict)
    # Backend driver selection (T1 multi-backend). "falkordb" (default) or "neo4j".
    backend_driver: str = "falkordb"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"

    @classmethod
    def from_env(cls, group_id: str = "cogniflow") -> GraphitiFalkorDBConfig:
        """Build config from environment (loads a local .env if present)."""
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except Exception:
            pass
        return cls(
            host=os.getenv("COGNIFLOW_FALKORDB_HOST", "localhost"),
            port=int(os.getenv("COGNIFLOW_FALKORDB_PORT", "6379")),
            group_id=group_id,
            llm_api_key=os.getenv("COGNIFLOW_LLM_API_KEY"),
            llm_base_url=os.getenv("COGNIFLOW_LLM_BASE_URL"),
            llm_model=os.getenv("COGNIFLOW_LLM_MODEL"),
        )


def _edge_to_belief(edge: EntityEdge) -> Belief:
    return Belief(
        id=edge.uuid,
        statement=edge.fact,
        created_at=edge.created_at,
        valid_at=edge.valid_at,
        invalid_at=edge.invalid_at,
        expired_at=edge.expired_at,
        predicate=edge.name,
        provenance=tuple(edge.episodes or ()),
        metadata={
            "group_id": edge.group_id,
            "source_node_uuid": edge.source_node_uuid,
            "target_node_uuid": edge.target_node_uuid,
        },
    )


class GraphitiFalkorDBBackend:
    """Async :class:`~cogniflow.core.contracts.AsyncSubstrate` over Graphiti+FalkorDB."""

    name = "graphiti-falkordb"

    # Over-fetch stopgap (G3): the FalkorDriver does not apply the date
    # SearchFilters, so a valid-at-T fact ranked outside top_k would be silently
    # dropped. Fetch a wider candidate set, validity-filter in-process, then
    # truncate to top_k.
    _OVERFETCH_FACTOR = 10
    _MIN_OVERFETCH = 50

    def __init__(
        self,
        config: GraphitiFalkorDBConfig,
        validity: ValidityPolicy | None = None,
    ) -> None:
        self.config = config
        self.group_id = config.group_id
        # The single shared validity instance, selected by config name via the
        # registry (fail-loud) unless an instance is injected directly.
        self._validity: ValidityPolicy = validity or create_policy(
            "validity", config.validity_policy, **config.validity_params
        )
        self._retrieval: RetrievalPolicy = create_policy(
            "retrieval", config.retrieval_policy, **config.retrieval_params
        )
        # Write listeners (e.g. a CachingAuditLedger.note_write) fire after each write
        # so current-knowledge cache entries for the group are invalidated.
        self._write_listeners: list[Any] = []
        if config.backend_driver == "neo4j":
            # Same graphiti GraphDriver abstraction; the audit Cypher is standard and
            # runs unchanged. group scoping is via the database name.
            self._driver = Neo4jDriver(
                config.neo4j_uri, config.neo4j_user, config.neo4j_password
            )
        else:
            self._driver = FalkorDriver(
                host=config.host, port=config.port, database=config.group_id
            )
        self._is_neo4j = config.backend_driver == "neo4j"
        llm_config = LLMConfig(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            model=config.llm_model,
        )
        self._graphiti = Graphiti(
            graph_driver=self._driver,
            llm_client=OpenAIGenericClient(config=llm_config),
            embedder=LocalDeterministicEmbedder(config.embedding_dim),
            cross_encoder=OpenAIRerankerClient(config=llm_config),
        )

    @property
    def validity(self) -> ValidityPolicy:
        """The shared validity policy instance (so the agent postprocessor can use
        the same object, not a second copy). One instance, not merely one class."""
        return self._validity

    def add_write_listener(self, listener: Any) -> None:
        """Register a callback ``listener(group_id)`` fired after each write (e.g. a
        CachingAuditLedger.note_write, to invalidate current-knowledge cache entries)."""
        self._write_listeners.append(listener)

    async def setup(self) -> None:
        """Create indices/constraints. Idempotent; call once before use."""
        await self._graphiti.build_indices_and_constraints()

    async def close(self) -> None:
        await self._graphiti.close()
        # Best-effort: close the underlying FalkorDB async client so its redis
        # connection does not emit "event loop is closed" on GC (Windows).
        client = getattr(self._driver, "client", None) or getattr(self._driver, "falkor_db", None)
        closer = getattr(client, "aclose", None) or getattr(client, "close", None)
        if closer is not None:
            try:
                result = closer()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                pass

    # --- AsyncSubstrate contract -------------------------------------------------

    async def write(self, episode: Episode) -> WriteReceipt:
        """Ingest an episode. If ``episode.metadata['triple']`` is present, inject it
        as a structured fact (``add_triplet``); otherwise extract via ``add_episode``.
        Both run Graphiti's dedup + temporal invalidation.
        """
        triple = (episode.metadata or {}).get("triple")
        receipt = (
            await self._write_triplet(episode, triple)
            if triple
            else await self._write_episode(episode)
        )
        for listener in self._write_listeners:
            try:
                listener(self.group_id)
            except Exception:
                pass
        return receipt

    async def _write_episode(self, episode: Episode) -> WriteReceipt:
        result = await self._graphiti.add_episode(
            name=episode.id,
            episode_body=episode.content,
            source_description=episode.source_description or episode.source,
            reference_time=episode.reference_time,
            source=EpisodeType.text,
            group_id=self.group_id,
        )
        created, invalidated = [], []
        for edge in result.edges:
            (invalidated if edge.expired_at is not None else created).append(edge.uuid)
        if invalidated and created:
            await self._persist_superseded_by(invalidated, created[0], episode.id)
        return WriteReceipt(
            episode_id=episode.id,
            created_belief_ids=tuple(created),
            invalidated_belief_ids=tuple(invalidated),
        )

    async def _write_triplet(self, episode: Episode, triple: dict) -> WriteReceipt:
        gid = self.group_id
        now = _utc_now()
        source = EntityNode(name=triple["source"], group_id=gid, labels=["Entity"], created_at=now)
        target = EntityNode(name=triple["target"], group_id=gid, labels=["Entity"], created_at=now)
        edge = EntityEdge(
            source_node_uuid=source.uuid,
            target_node_uuid=target.uuid,
            name=triple["predicate"],
            fact=triple.get("fact", triple["predicate"]),
            group_id=gid,
            created_at=now,
            valid_at=episode.reference_time,
            episodes=[episode.id],  # provenance always (G4): authoritative facts carry their source
        )
        result = await self._graphiti.add_triplet(source, edge, target)
        created = [e.uuid for e in result.edges if e.expired_at is None]
        invalidated = [e.uuid for e in result.edges if e.expired_at is not None]
        if invalidated and created:
            await self._persist_superseded_by(invalidated, created[0], episode.id)
        return WriteReceipt(
            episode_id=episode.id,
            created_belief_ids=tuple(created),
            invalidated_belief_ids=tuple(invalidated),
        )

    async def read(self, query: RetrievalQuery) -> RetrievalResult:
        overfetch = max(query.top_k * self._OVERFETCH_FACTOR, self._MIN_OVERFETCH)
        edges = await self._graphiti.search(
            query=query.text,
            group_ids=[self.group_id],
            num_results=overfetch,
            search_filter=self._as_of_filter(query.as_of),
        )
        beliefs = [_edge_to_belief(e) for e in edges]
        # Deterministic safety net (seam b): the FalkorDriver does not apply the
        # date SearchFilters, so enforce point-in-time validity in-process using
        # the single shared ValidityPolicy, then truncate to top_k. This is the
        # invariant the heartbeat depends on, and it recovers valid-at-T facts
        # that were ranked outside a naive top_k window.
        # Pipeline order (T4): validity-filter (deterministic) BEFORE rank (opt-in,
        # possibly expensive), then truncate. Reranking never runs on invalid facts.
        results = tuple(rank_valid(beliefs, query, self._validity, self._retrieval))
        log_read(query.text, query.as_of, len(beliefs), len(results))
        return RetrievalResult(query=query, results=results, as_of=query.as_of)

    async def falsify(
        self,
        target: Belief | str,
        against: Sequence[Belief] | None = None,
    ) -> FalsificationVerdict:
        """Report the stored falsification state of a belief (the explicit
        falsification engine is deferred; supersession happens at write time)."""
        target_id = target if isinstance(target, str) else target.id
        try:
            edge = await EntityEdge.get_by_uuid(self._driver, target_id)
        except Exception:
            return FalsificationVerdict(
                target_id=target_id, superseded=False, rationale="belief not found"
            )
        superseded = edge.expired_at is not None or edge.invalid_at is not None
        return FalsificationVerdict(
            target_id=target_id,
            superseded=superseded,
            invalid_at=edge.invalid_at,
            rationale="reflects stored bi-temporal invalidation state",
        )

    # --- AuditLedger (L5): read-only replay via DIRECT temporal queries ----------
    #
    # Replay is a temporal scan, not a relevance search, so it does NOT route through
    # graphiti.search (whose FalkorDriver search_filter is a no-op, see KNOWN_ISSUES).
    # We push the temporal predicate straight into Cypher. Dates are stored as ISO-8601
    # UTC strings, which sort chronologically under lexicographic comparison, so the
    # predicate is correct in the DB; the pure core functions re-apply the exact
    # (parsed-datetime) logic as the authoritative filter. The system-time predicate
    # (created_at <= S) bounds the scan to history-known-by-S; we never fetch the whole
    # graph into memory.

    _AUDIT_RETURN = (
        " RETURN r.uuid AS uuid, r.fact AS fact, r.name AS name, "
        "r.created_at AS created_at, r.valid_at AS valid_at, r.invalid_at AS invalid_at, "
        "r.expired_at AS expired_at, r.episodes AS episodes, r.group_id AS group_id, "
        "r.superseded_by AS superseded_by, r.superseded_by_episode AS superseded_by_episode, "
        "a.uuid AS src, b.uuid AS tgt"
    )

    async def _persist_superseded_by(
        self, invalidated_ids: list[str], by_belief_id: str, episode_id: str
    ) -> None:
        """SUP: stamp the back-link at write time so provenance is exact, not a temporal
        heuristic. Stored on the superseded edges in the same write."""
        await self._driver.execute_query(
            "MATCH ()-[r:RELATES_TO]->() WHERE r.uuid IN $ids "
            "SET r.superseded_by = $by, r.superseded_by_episode = $ep",
            ids=list(invalidated_ids),
            by=by_belief_id,
            ep=episode_id,
        )

    @staticmethod
    def _parse_dt(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        to_native = getattr(value, "to_native", None)  # neo4j.time.DateTime
        if to_native is not None:
            native = to_native()
            return native if native.tzinfo else native.replace(tzinfo=timezone.utc)
        return None

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    def _dt_param(self, value: datetime) -> Any:
        # Neo4j stores native temporals -> pass a datetime (the driver converts it);
        # FalkorDB stores ISO strings that sort lexicographically -> pass the ISO string.
        return value.astimezone(timezone.utc) if self._is_neo4j else self._iso(value)

    def _row_to_belief(self, rec: dict[str, Any]) -> Belief:
        return Belief(
            id=rec["uuid"],
            statement=rec["fact"],
            created_at=self._parse_dt(rec["created_at"]) or _utc_now(),
            valid_at=self._parse_dt(rec.get("valid_at")),
            invalid_at=self._parse_dt(rec.get("invalid_at")),
            expired_at=self._parse_dt(rec.get("expired_at")),
            predicate=rec.get("name"),
            provenance=tuple(rec.get("episodes") or ()),
            metadata={
                "group_id": rec.get("group_id"),
                "source_node_uuid": rec.get("src"),
                "target_node_uuid": rec.get("tgt"),
                "superseded_by": rec.get("superseded_by"),
                "superseded_by_episode": rec.get("superseded_by_episode"),
            },
        )

    async def _fetch(self, where: str, **params: Any) -> list[Belief]:
        query = "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) " + where + self._AUDIT_RETURN
        records, _, _ = await self._driver.execute_query(query, **params)
        return [self._row_to_belief(rec) for rec in records]

    async def event_time_query(
        self, as_of: datetime, group_id: str | None = None
    ) -> list[Belief]:
        # Push the event-time predicate to the DB (this is what graphiti.search failed
        # to do); the pure function is authoritative on the bounded set. The group
        # filter is required for backends with a shared DB (Neo4j); harmless on FalkorDB.
        gid = group_id or self.group_id
        rows = await self._fetch(
            "WHERE r.group_id = $gid AND (r.valid_at IS NULL OR r.valid_at <= $t)",
            gid=gid,
            t=self._dt_param(as_of),
        )
        return _event_time_query(rows, as_of)

    async def system_time_replay(
        self, system_time: datetime, group_id: str | None = None
    ) -> list[Belief]:
        gid = group_id or self.group_id
        rows = await self._fetch(
            "WHERE r.group_id = $gid AND r.created_at <= $s",
            gid=gid,
            s=self._dt_param(system_time),
        )
        return _system_time_replay(rows, system_time)

    async def bitemporal_query(
        self, system_time: datetime, event_time: datetime, group_id: str | None = None
    ) -> list[Belief]:
        gid = group_id or self.group_id
        rows = await self._fetch(
            "WHERE r.group_id = $gid AND r.created_at <= $s",
            gid=gid,
            s=self._dt_param(system_time),
        )
        return _bitemporal_query(rows, system_time, event_time)

    async def provenance_trace(
        self, belief_id: str, group_id: str | None = None
    ) -> ProvenanceTrace:
        rows = await self._fetch("WHERE r.uuid = $uuid", uuid=belief_id)
        if not rows:
            return ProvenanceTrace(belief_id=belief_id)
        belief = rows[0]
        superseded_belief = superseded_episode = None
        # SUP: prefer the back-link stamped at write time (exact, not a heuristic).
        stored_by = belief.metadata.get("superseded_by")
        if stored_by:
            return ProvenanceTrace(
                belief_id=belief_id,
                asserted_by=belief.provenance,
                superseded_by_belief=stored_by,
                superseded_by_episode=belief.metadata.get("superseded_by_episode"),
                invalid_at=belief.invalid_at,
                expired_at=belief.expired_at,
            )
        # Fallback (older data without the stamp): reconstruct by temporal join - the
        # belief whose validity began when this one ended (valid_at == this.invalid_at),
        # ingested around this.expired_at. Ambiguous if two facts share that boundary.
        if belief.invalid_at is not None:
            candidates = await self._fetch(
                "WHERE r.group_id = $gid AND r.valid_at = $iv AND r.uuid <> $uuid",
                gid=group_id or self.group_id,
                iv=self._dt_param(belief.invalid_at),
                uuid=belief_id,
            )
            if candidates:
                anchor = belief.expired_at or belief.created_at
                chosen = min(
                    candidates,
                    key=lambda c: abs((c.created_at - anchor).total_seconds()),
                )
                superseded_belief = chosen.id
                superseded_episode = chosen.provenance[0] if chosen.provenance else None
        return ProvenanceTrace(
            belief_id=belief_id,
            asserted_by=belief.provenance,
            superseded_by_belief=superseded_belief,
            superseded_by_episode=superseded_episode,
            invalid_at=belief.invalid_at,
            expired_at=belief.expired_at,
        )

    @staticmethod
    def _as_of_filter(as_of: datetime | None) -> SearchFilters:
        """Compile point-in-time semantics: valid_at <= T AND (invalid_at IS NULL OR
        invalid_at > T). Opt-in; an absent as_of returns everything."""
        if as_of is None:
            return SearchFilters()
        return SearchFilters(
            valid_at=[
                [DateFilter(date=as_of, comparison_operator=ComparisonOperator.less_than_equal)]
            ],
            invalid_at=[
                [DateFilter(comparison_operator=ComparisonOperator.is_null)],
                [DateFilter(date=as_of, comparison_operator=ComparisonOperator.greater_than)],
            ],
        )
