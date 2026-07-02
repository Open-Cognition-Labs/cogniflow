"""Bridges - framework-neutral contracts for adapting the substrate onto external
RAG/agent frameworks. milestone ships only the neutral contracts; concrete adapters
(e.g. the LlamaIndex bridge) are deferred.
"""

from __future__ import annotations

from .contracts import (
    BridgeNode,
    PostprocessorBridge,
    RetrieverBridge,
    ToolBridge,
    from_retrieval_result,
)

__all__ = [
    "BridgeNode",
    "RetrieverBridge",
    "PostprocessorBridge",
    "ToolBridge",
    "from_retrieval_result",
]
