"""milestone: the over-fetch depth is tunable via env, and the saturation flag defaults off.

Guarded by graphiti_core import: runs in the integration lane and locally (where the backend
deps are installed), skips cleanly in the contract-only CI job.
"""

from __future__ import annotations

import pytest

pytest.importorskip("graphiti_core")
pytest.importorskip("falkordb")

from cogniflow.backends.graphiti_falkordb import GraphitiFalkorDBConfig  # noqa: E402


def test_overfetch_depth_is_tunable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COGNIFLOW_OVERFETCH_FACTOR", "25")
    monkeypatch.setenv("COGNIFLOW_MIN_OVERFETCH", "200")
    cfg = GraphitiFalkorDBConfig.from_env(group_id="cfg_test")
    assert cfg.overfetch_factor == 25
    assert cfg.min_overfetch == 200


def test_overfetch_defaults_preserved() -> None:
    cfg = GraphitiFalkorDBConfig(group_id="cfg_test")
    assert cfg.overfetch_factor == 10 # unchanged default behavior (T5)
    assert cfg.min_overfetch == 50
