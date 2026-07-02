"""cogniflow - temporal, self-falsifying belief substrate for agentic RAG.

milestone exposes only the stable contracts and core types. Backends and bridges
are imported explicitly from their submodules so that the top-level import stays
dependency-free.
"""

from __future__ import annotations

from .core.audit import (
    AuditLedger,
    bitemporal_query,
    event_time_query,
    reconstruct_as_of_system,
    system_time_replay,
)
from .core.contracts import AsyncSubstrate, Substrate
from .core.types import (
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
from .registry import (
    FAMILIES,
    PolicyNotFoundError,
    available_policies,
    build_policies,
    create_policy,
    register_policy,
)

__version__ = "0.1.0"

__all__ = [
    "Substrate",
    "AsyncSubstrate",
    "Belief",
    "Episode",
    "RetrievalQuery",
    "ScoredBelief",
    "RetrievalResult",
    "FalsificationVerdict",
    "WriteReceipt",
    "utc_now",
    # audit / replay (L5)
    "AuditLedger",
    "ProvenanceTrace",
    "system_time_replay",
    "event_time_query",
    "bitemporal_query",
    "reconstruct_as_of_system",
    # policy registry (L3 plugin seam)
    "FAMILIES",
    "PolicyNotFoundError",
    "register_policy",
    "create_policy",
    "available_policies",
    "build_policies",
    "__version__",
]
