"""Substrate backends. milestone ships only the no-op backend.

The Graphiti/FalkorDB backend is deferred to milestone and will live alongside
``noop`` here, implementing ``AsyncSubstrate``.
"""

from __future__ import annotations

from .noop import AsyncNoOpBackend, NoOpBackend

__all__ = ["NoOpBackend", "AsyncNoOpBackend"]
