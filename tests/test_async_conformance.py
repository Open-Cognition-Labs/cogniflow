"""milestone gate: the async conformance driver awaits an async backend, and the two
drivers refuse the wrong async-ness. This closes review finding #1 (a sync-only
harness that would falsely bless an async backend).
"""

from __future__ import annotations

import asyncio

import pytest

from cogniflow.backends.noop import AsyncNoOpBackend, NoOpBackend
from cogniflow.conformance.suite import (
    assert_conforms_async,
    run_conformance,
    run_conformance_async,
)
from cogniflow.core.contracts import AsyncSubstrate, Substrate


def test_async_noop_passes_async_conformance() -> None:
    results = asyncio.run(run_conformance_async(AsyncNoOpBackend()))
    assert all(r.passed for r in results), [r for r in results if not r.passed]


def test_assert_conforms_async_does_not_raise() -> None:
    asyncio.run(assert_conforms_async(AsyncNoOpBackend()))


def test_runtime_checkable_false_positive_is_guarded() -> None:
    # runtime_checkable checks method NAMES only, so an async backend wrongly
    # satisfies the *sync* Substrate protocol. That is the trap; the sync harness
    # must refuse it rather than silently producing un-awaited coroutines.
    assert isinstance(AsyncNoOpBackend(), Substrate) # the false positive
    with pytest.raises(TypeError):
        run_conformance(AsyncNoOpBackend()) # the guard catches it


def test_async_harness_refuses_sync_backend() -> None:
    # Symmetric guard: a sync backend also matches AsyncSubstrate by name, but its
    # write() is not awaitable, so the async harness must refuse it.
    assert isinstance(NoOpBackend(), AsyncSubstrate) # the symmetric false positive
    with pytest.raises(TypeError):
        asyncio.run(run_conformance_async(NoOpBackend()))


def test_sync_noop_still_passes_sync_harness() -> None:
    # Regression: the sync path is unchanged for genuinely sync backends.
    results = run_conformance(NoOpBackend())
    assert all(r.passed for r in results), [r for r in results if not r.passed]
