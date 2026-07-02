"""Core contracts and types - standard library only, no third-party imports."""

from __future__ import annotations

from .archive import (
    ArchiveStore,
    InMemoryArchive,
    bitemporal_query_archived,
    system_time_replay_archived,
)
from .audit import (
    AuditLedger,
    believed_at,
    bitemporal_query,
    event_time_query,
    known_at,
    reconstruct_as_of_system,
    system_time_replay,
)
from .contracts import AsyncSubstrate, Substrate
from .policies import (
    AlwaysWritebackPolicy,
    DefaultRetrievalPolicy,
    DefaultValidityPolicy,
    FalsificationPolicy,
    GraceWindowValidityPolicy,
    IntervalOverlapFalsificationPolicy,
    NeverWritebackPolicy,
    NoFalsificationPolicy,
    RecencyRetrievalPolicy,
    RetrievalPolicy,
    ValidityPolicy,
    WritebackPolicy,
    filter_valid,
    rank_valid,
)
from .types import (
    Belief,
    Episode,
    FalsificationVerdict,
    ProvenanceTrace,
    RetrievalQuery,
    RetrievalResult,
    ScoredBelief,
    WriteReceipt,
    utc_now,
)

__all__ = [
    # contracts
    "Substrate",
    "AsyncSubstrate",
    # audit / replay (L5)
    "AuditLedger",
    "believed_at",
    "known_at",
    "reconstruct_as_of_system",
    "system_time_replay",
    "event_time_query",
    "bitemporal_query",
    "ProvenanceTrace",
    # archive (L5 scale)
    "ArchiveStore",
    "InMemoryArchive",
    "system_time_replay_archived",
    "bitemporal_query_archived",
    # policies (interfaces)
    "RetrievalPolicy",
    "ValidityPolicy",
    "FalsificationPolicy",
    "WritebackPolicy",
    # policies (reference implementations)
    "DefaultRetrievalPolicy",
    "RecencyRetrievalPolicy",
    "DefaultValidityPolicy",
    "GraceWindowValidityPolicy",
    "NoFalsificationPolicy",
    "IntervalOverlapFalsificationPolicy",
    "NeverWritebackPolicy",
    "AlwaysWritebackPolicy",
    "filter_valid",
    "rank_valid",
    # types
    "Belief",
    "Episode",
    "RetrievalQuery",
    "ScoredBelief",
    "RetrievalResult",
    "FalsificationVerdict",
    "WriteReceipt",
    "utc_now",
]
