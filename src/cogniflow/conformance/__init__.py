"""The plugin conformance-test harness.

Any backend claiming to be a cogniflow ``Substrate`` or ``AsyncSubstrate`` must
pass this suite. It routes by async-ness so a backend is graded by a driver that
actually ran it. milestone checks are structural/type-level; behavioral conformance
(bi-temporal correctness, falsification semantics) is added with the FalkorDB
backend.
"""

from __future__ import annotations

from .policy_suites import (
    assert_policy_conforms,
    check_falsification_determinism,
    run_policy_conformance,
)
from .suite import (
    CheckResult,
    assert_conforms,
    assert_conforms_async,
    run_conformance,
    run_conformance_async,
)

__all__ = [
    "CheckResult",
    "run_conformance",
    "assert_conforms",
    "run_conformance_async",
    "assert_conforms_async",
    "run_policy_conformance",
    "assert_policy_conforms",
    "check_falsification_determinism",
]
