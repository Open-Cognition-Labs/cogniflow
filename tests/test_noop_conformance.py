"""milestone proof: a no-op backend passes the conformance stub."""

from __future__ import annotations

from cogniflow.backends.noop import NoOpBackend
from cogniflow.conformance.suite import assert_conforms, run_conformance
from cogniflow.core.contracts import Substrate


def test_noop_is_a_substrate() -> None:
    assert isinstance(NoOpBackend(), Substrate)


def test_noop_passes_every_conformance_check() -> None:
    failures = [r for r in run_conformance(NoOpBackend()) if not r.passed]
    assert not failures, failures


def test_assert_conforms_does_not_raise_for_noop() -> None:
    assert_conforms(NoOpBackend())
