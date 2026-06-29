"""Selecting policies by name - the L3 config surface.

No infra needed: this shows how config picks an implementation per family, and how
the same belief is judged differently under two validity policies selected by name.

Run:  python examples/policy_config.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from cogniflow import build_policies, create_policy
from cogniflow.core.types import Belief

# A config a deployment might load from YAML/env. Omitted families use named defaults.
CONFIG = {
    "validity": "grace_window",   # try "strict" to change behavior with no code edit
    "retrieval": "recency",
    "falsification": "interval_overlap",
    "writeback": "never",
}
PARAMS = {"validity": {"grace_days": 400}}


def main() -> None:
    policies = build_policies(CONFIG, PARAMS)
    print("selected policies:")
    for family, policy in policies.items():
        print(f"  {family:14s} -> {type(policy).__name__}")

    # A fact that was true 2019..2022, asked exactly at its invalid_at.
    fact = Belief(
        id="hq",
        statement="Acme Corp is headquartered in Denver",
        created_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
        valid_at=datetime(2019, 1, 1, tzinfo=timezone.utc),
        invalid_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
        expired_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
    )
    as_of = datetime(2022, 1, 1, tzinfo=timezone.utc)

    strict = create_policy("validity", "strict")
    grace = policies["validity"]
    print(f"\nat as_of={as_of.date()}  strict.valid={strict.is_valid(fact, as_of)} "
          f"grace_window.valid={grace.is_valid(fact, as_of)}")


if __name__ == "__main__":
    main()
