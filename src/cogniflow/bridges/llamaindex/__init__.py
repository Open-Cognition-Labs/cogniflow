"""LlamaIndex bridge : adapters that put the cogniflow substrate behind a
LlamaIndex retriever, node-postprocessor, and agent.

This package imports ``llama-index-core`` (and, for ``agent``, an OpenAI-compatible
LLM), so it is imported only when used - never from ``cogniflow.bridges.__init__``,
which keeps the core import-free. Validity is never re-implemented here; the
postprocessor calls the same ``cogniflow.core.policies`` definition as the substrate.

Deferred to later phases: ``verify_fact`` / ``record_observation`` tools (seams c/d).
"""

from __future__ import annotations

from .agent import build_recording_agent, build_temporal_agent, make_llm
from .postprocessor import TemporalValidityPostprocessor
from .retriever import TemporalGraphRetriever
from .tools import make_record_observation_tool, make_verify_fact_tool

__all__ = [
    "TemporalGraphRetriever",
    "TemporalValidityPostprocessor",
    "build_temporal_agent",
    "build_recording_agent",
    "make_record_observation_tool",
    "make_verify_fact_tool",
    "make_llm",
]
