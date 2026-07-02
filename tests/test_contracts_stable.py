"""Freeze the public contract surface. If a field set changes, this test fails - 
forcing a deliberate, reviewed decision rather than silent contract drift.
"""

from __future__ import annotations

import dataclasses

from cogniflow.bridges import contracts as bridges
from cogniflow.core import policies, types
from cogniflow.core.contracts import AsyncSubstrate, Substrate


def _fields(dc: type) -> set[str]:
    return {f.name for f in dataclasses.fields(dc)}


def test_belief_field_surface_is_stable() -> None:
    assert _fields(types.Belief) == {
        "id",
        "statement",
        "created_at",
        "valid_at",
        "invalid_at",
        "expired_at",
        "subject",
        "predicate",
        "object",
        "confidence",
        "provenance",
        "metadata",
    }


def test_episode_field_surface_is_stable() -> None:
    assert _fields(types.Episode) == {
        "id",
        "content",
        "reference_time",
        "source",
        "source_description",
        "metadata",
    }


def test_io_type_field_surfaces_are_stable() -> None:
    assert _fields(types.RetrievalQuery) == {"text", "as_of", "top_k", "include_expired", "filters"}
    assert _fields(types.ScoredBelief) == {"belief", "score"}
    assert _fields(types.RetrievalResult) == {"query", "results", "as_of"}
    assert _fields(types.FalsificationVerdict) == {
        "target_id",
        "superseded",
        "invalid_at",
        "superseded_by",
        "rationale",
        "indeterminate",
    }
    assert _fields(types.WriteReceipt) == {
        "episode_id",
        "created_belief_ids",
        "invalidated_belief_ids",
    }


def test_substrate_contracts_expose_three_operations() -> None:
    for op in ("write", "read", "falsify"):
        assert hasattr(Substrate, op)
        assert hasattr(AsyncSubstrate, op)


def test_four_policy_interfaces_exist() -> None:
    for name in ("RetrievalPolicy", "ValidityPolicy", "FalsificationPolicy", "WritebackPolicy"):
        assert hasattr(policies, name), name


def test_bridge_contracts_exist() -> None:
    assert dataclasses.is_dataclass(bridges.BridgeNode)
    for name in ("RetrieverBridge", "PostprocessorBridge", "ToolBridge"):
        assert hasattr(bridges, name), name
