"""The substrate contract: write / read / falsify.

Both a synchronous ``Substrate`` and an ``AsyncSubstrate`` are defined because the
canonical backend (Graphiti) is async, while the no-op backend and conformance stub
are simplest to express synchronously. A backend implements exactly one of them.

Both are ``runtime_checkable`` Protocols, so ``isinstance(obj, Substrate)`` checks
structural conformance (method presence) at runtime - used by the conformance harness.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .types import (
    Belief,
    Episode,
    FalsificationVerdict,
    RetrievalQuery,
    RetrievalResult,
    WriteReceipt,
)


@runtime_checkable
class Substrate(Protocol):
    """Synchronous belief substrate."""

    def write(self, episode: Episode) -> WriteReceipt:
        """Ingest a source episode, returning what was created/invalidated."""
        ...

    def read(self, query: RetrievalQuery) -> RetrievalResult:
        """Retrieve beliefs relevant to a point-in-time query."""
        ...

    def falsify(
        self,
        target: Belief | str,
        against: Sequence[Belief] | None = None,
    ) -> FalsificationVerdict:
        """Decide whether ``target`` is superseded (optionally by ``against``)."""
        ...


@runtime_checkable
class AsyncSubstrate(Protocol):
    """Asynchronous belief substrate (canonical for I/O-bound backends)."""

    async def write(self, episode: Episode) -> WriteReceipt: ...

    async def read(self, query: RetrievalQuery) -> RetrievalResult: ...

    async def falsify(
        self,
        target: Belief | str,
        against: Sequence[Belief] | None = None,
    ) -> FalsificationVerdict: ...
