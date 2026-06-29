"""Core contracts and types — standard library only, no third-party imports."""

from __future__ import annotations

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
)
from .types import (
    Belief,
    Episode,
    FalsificationVerdict,
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
