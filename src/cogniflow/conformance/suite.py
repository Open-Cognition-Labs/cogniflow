"""Conformance harness: the gate any Substrate / AsyncSubstrate must pass.

milestone shipped a sync stub. milestone adds the async driver, because the canonical
backend (Graphiti/FalkorDB) is asynchronous and ``runtime_checkable`` Protocols
only check method *names*, not async-ness: ``isinstance(async_backend, Substrate)``
returns True (a false positive). The harness therefore routes by
``inspect.iscoroutinefunction`` and refuses to push an async backend through the
sync checks (or a sync backend through the async checks), so a backend is always
graded by a driver that actually awaited it.

milestone checks are still structural/type-level. Behavioral conformance
(bi-temporal correctness, falsification semantics) lands with the FalkorDB backend.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from ..core.contracts import AsyncSubstrate, Substrate
from ..core.types import (
    Episode,
    FalsificationVerdict,
    RetrievalQuery,
    RetrievalResult,
    WriteReceipt,
    utc_now,
)


@dataclass
class CheckResult:
    """Outcome of a single conformance check."""

    name: str
    passed: bool
    detail: str = ""


def _write_is_async(substrate: Any) -> bool:
    """True if the substrate's ``write`` is a coroutine function.

    This is the real async discriminator. ``isinstance(.., AsyncSubstrate)`` is
    necessary but NOT sufficient: a runtime_checkable Protocol matches a sync
    backend too, because it only checks that the method names exist.
    """
    return inspect.iscoroutinefunction(getattr(substrate, "write", None))


def run_conformance(substrate: Any) -> list[CheckResult]:
    """Run the conformance stub against a SYNCHRONOUS substrate.

    Refuses an async backend: its ``write`` returns a coroutine that the sync
    checks would never await, which would surface as a silent RuntimeWarning
    instead of a failure.
    """
    if _write_is_async(substrate):
        raise TypeError(
            "run_conformance() is sync-only but received an async substrate "
            "(write() is a coroutine function). Use run_conformance_async()."
        )

    results: list[CheckResult] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        results.append(CheckResult(name=name, passed=bool(cond), detail=detail))

    check(
        "implements Substrate protocol",
        isinstance(substrate, Substrate),
        "object is missing write/read/falsify",
    )
    check(
        "operations are synchronous",
        not _write_is_async(substrate),
        "write() must not be a coroutine function for the sync harness",
    )

    now = utc_now()

    episode = Episode(id="conformance-ep", content="placeholder", reference_time=now)
    receipt = substrate.write(episode)
    check("write -> WriteReceipt", isinstance(receipt, WriteReceipt))
    check(
        "write echoes episode id",
        getattr(receipt, "episode_id", None) == "conformance-ep",
    )

    query = RetrievalQuery(text="placeholder", as_of=now, top_k=3)
    result = substrate.read(query)
    check("read -> RetrievalResult", isinstance(result, RetrievalResult))
    check("read echoes query", result.query == query)

    verdict = substrate.falsify("conformance-belief")
    check("falsify -> FalsificationVerdict", isinstance(verdict, FalsificationVerdict))
    check(
        "falsify echoes target id",
        verdict.target_id == "conformance-belief",
    )

    return results


async def run_conformance_async(substrate: Any) -> list[CheckResult]:
    """Run the conformance stub against an ASYNCHRONOUS substrate.

    Refuses a sync backend, and verifies each operation is actually a coroutine
    function. This closes the runtime_checkable false positive: presence of the
    method name is not enough; it must be awaitable.
    """
    if not _write_is_async(substrate):
        raise TypeError(
            "run_conformance_async() requires an async substrate (write() must be "
            "a coroutine function). Use run_conformance() for sync backends."
        )

    results: list[CheckResult] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        results.append(CheckResult(name=name, passed=bool(cond), detail=detail))

    check(
        "implements AsyncSubstrate protocol",
        isinstance(substrate, AsyncSubstrate),
        "object is missing write/read/falsify",
    )
    for op in ("write", "read", "falsify"):
        check(
            f"{op} is a coroutine function",
            inspect.iscoroutinefunction(getattr(substrate, op, None)),
            f"{op}() must be async for the async harness",
        )

    now = utc_now()

    episode = Episode(id="conformance-ep", content="placeholder", reference_time=now)
    receipt = await substrate.write(episode)
    check("await write -> WriteReceipt", isinstance(receipt, WriteReceipt))
    check(
        "write echoes episode id",
        getattr(receipt, "episode_id", None) == "conformance-ep",
    )

    query = RetrievalQuery(text="placeholder", as_of=now, top_k=3)
    result = await substrate.read(query)
    check("await read -> RetrievalResult", isinstance(result, RetrievalResult))
    check("read echoes query", result.query == query)

    verdict = await substrate.falsify("conformance-belief")
    check("await falsify -> FalsificationVerdict", isinstance(verdict, FalsificationVerdict))
    check(
        "falsify echoes target id",
        verdict.target_id == "conformance-belief",
    )

    return results


def assert_conforms(substrate: Any) -> None:
    """Raise ``AssertionError`` listing any failed sync conformance checks."""
    failures = [r for r in run_conformance(substrate) if not r.passed]
    if failures:
        lines = "\n".join(f" - {r.name}: {r.detail}" for r in failures)
        raise AssertionError(f"Substrate failed conformance:\n{lines}")


async def assert_conforms_async(substrate: Any) -> None:
    """Raise ``AssertionError`` listing any failed async conformance checks."""
    failures = [r for r in await run_conformance_async(substrate) if not r.passed]
    if failures:
        lines = "\n".join(f" - {r.name}: {r.detail}" for r in failures)
        raise AssertionError(f"AsyncSubstrate failed conformance:\n{lines}")
