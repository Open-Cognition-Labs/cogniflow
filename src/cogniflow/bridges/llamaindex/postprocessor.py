"""TemporalValidityPostprocessor (seam b) - the agent-layer mirror of the
substrate's in-process validity net.

It calls the SAME ``cogniflow.core.policies`` definition of "valid at T" via
``filter_valid`` / ``DefaultValidityPolicy``. There is no second copy of the rule:
this is defense in depth (same definition, two call sites), not a fork.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from llama_index.core.bridge.pydantic import PrivateAttr
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle

from ...core.policies import ValidityPolicy
from ...core.types import Belief, utc_now


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _node_to_belief(node_with_score: NodeWithScore) -> Belief:
    node = node_with_score.node
    md = node.metadata or {}
    return Belief(
        id=str(md.get("belief_id", "")),
        statement=node.get_content(metadata_mode=MetadataMode.NONE),
        created_at=_parse(md.get("created_at")) or utc_now(),
        valid_at=_parse(md.get("valid_at")),
        invalid_at=_parse(md.get("invalid_at")),
        expired_at=_parse(md.get("expired_at")),
        provenance=tuple(md.get("provenance") or ()),
    )


class TemporalValidityPostprocessor(BaseNodePostprocessor):
    """Drop nodes not valid at the bound ``as_of``, using the shared ValidityPolicy.

    The policy is *injected and required* (P1/T2): pass the same instance the
    substrate uses, so there is one validity instance per wiring, not merely one
    class. There is NO silent default - a missing policy raises at construction time
    (fail-loud), because a component quietly using the default when a custom policy
    was intended is exactly the milestone fork.
    """

    as_of: datetime | None = None
    include_expired: bool = False

    _validity: Any = PrivateAttr(default=None)

    def __init__(self, validity_policy: ValidityPolicy | None = None, **data: Any) -> None:
        super().__init__(**data)
        if validity_policy is None:
            raise ValueError(
                "TemporalValidityPostprocessor requires an explicit validity_policy "
                "(fail-loud; no silent default). Pass the substrate's validity instance."
            )
        self._validity = validity_policy

    @property
    def validity(self) -> ValidityPolicy:
        return self._validity

    @classmethod
    def class_name(cls) -> str:
        return "TemporalValidityPostprocessor"

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: QueryBundle | None = None,
    ) -> list[NodeWithScore]:
        policy = self.validity
        return [
            n
            for n in nodes
            if policy.is_valid(_node_to_belief(n), self.as_of, self.include_expired)
        ]

    async def _apostprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: QueryBundle | None = None,
    ) -> list[NodeWithScore]:
        # Pure CPU filtering; safe to run inline on the async path.
        return self._postprocess_nodes(nodes, query_bundle)
