"""Audit/replay dashboard API - CI-safe. The centerpiece un-knowing test uses
controlled beliefs + the REAL core audit functions (the system-time axis is degenerate on
live data, where everything is learned 'now'), so the invariant is asserted deterministically.
No infra.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cogniflow.core.audit import (
    bitemporal_query as _bitemporal,
)
from cogniflow.core.audit import (
    event_time_query as _event,
)
from cogniflow.core.audit import (
    system_time_replay as _replay,
)
from cogniflow.core.types import Belief, ProvenanceTrace

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from cogniflow.serving import create_audit_app  # noqa: E402


def _dt(y: int, m: int = 1) -> datetime:
    return datetime(y, m, 1, tzinfo=timezone.utc)


# Boston: valid 2019, superseded by Denver at event-time 2022, and that supersession was
# LEARNED (expired_at) in June 2022. Denver: learned/valid 2022.
BOSTON = Belief(
    id="boston",
    statement="Acme Corp is headquartered in Boston",
    created_at=_dt(2019),
    valid_at=_dt(2019),
    invalid_at=_dt(2022),
    expired_at=_dt(2022, 6), # the invalidation was learned in June 2022
    provenance=("ep-v1", "ep-missing"),
    metadata={"valid_at_source": "provided", "superseded_by": "denver"},
)
DENVER = Belief(
    id="denver",
    statement="Acme Corp is headquartered in Denver",
    created_at=_dt(2022, 6), # learned June 2022
    valid_at=_dt(2022),
    provenance=("ep-v2",),
    metadata={"valid_at_source": "document:mtime"},
)
BELIEFS = [BOSTON, DENVER]
NAMES = {"ep-v1": "acme_report_v1#chunk0", "ep-v2": "acme_report_v2#chunk0"} # ep-missing absent


class _FakeLedger:
    async def event_time_query(self, as_of, group_id=None):
        return _event(BELIEFS, as_of)

    async def system_time_replay(self, system_time, group_id=None):
        return _replay(BELIEFS, system_time)

    async def bitemporal_query(self, system_time, event_time, group_id=None):
        return _bitemporal(BELIEFS, system_time, event_time)

    async def provenance_trace(self, belief_id, group_id=None):
        if belief_id == "boston":
            return ProvenanceTrace(
                belief_id="boston",
                asserted_by=("ep-v1", "ep-missing"),
                superseded_by_belief="denver",
                superseded_by_episode="ep-v2",
                invalid_at=_dt(2022),
                expired_at=_dt(2022, 6),
            )
        return ProvenanceTrace(belief_id=belief_id, asserted_by=("ep-v2",))

    async def get_belief(self, belief_id, group_id=None):
        return next((b for b in BELIEFS if b.id == belief_id), None)

    async def resolve_episodes(self, uuids, group_id=None):
        return {u: NAMES[u] for u in uuids if u in NAMES}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_audit_app(_FakeLedger()))


def test_centerpiece_replay_un_knows_the_future(client: TestClient) -> None:
    # GROUND TRUTH: Boston really was superseded - the timeline shows its stored invalid_at.
    truth = client.get("/audit/timeline/boston").json()["belief"]
    assert truth["invalid_at"] is not None # the supersession is real, not absent data

    # S = 2021, BEFORE the supersession was LEARNED (June 2022): the future must not leak back.
    early = client.get("/audit/replay", params={"system_time": "2021-01-01"}).json()["beliefs"]
    boston = [b for b in early if b["belief_id"] == "boston"]
    assert boston, "Boston was the live truth at S=2021"
    assert boston[0]["invalid_at"] is None # UN-KNOWN: the stored invalid_at is hidden at S=2021
    assert not [b for b in early if b["belief_id"] == "denver"] # Denver not yet known at 2021

    # S = 2023, AFTER: Boston is no longer the system's LIVE truth (correctly dropped from the
    # live replay); Denver is. (The superseded fact still lives in the timeline/bitemporal view.)
    late = client.get("/audit/replay", params={"system_time": "2023-01-01"}).json()["beliefs"]
    ids = {b["belief_id"] for b in late}
    assert "denver" in ids and "boston" not in ids


def test_event_time_axis_changes_with_as_of(client: TestClient) -> None:
    at_2020 = client.get("/audit/event", params={"as_of": "2020-01-01"}).json()["beliefs"]
    at_2023 = client.get("/audit/event", params={"as_of": "2023-01-01"}).json()["beliefs"]
    assert [b["belief_id"] for b in at_2020] == ["boston"] # only Boston was true in 2020
    assert [b["belief_id"] for b in at_2023] == ["denver"] # Denver by 2023


def test_valid_at_source_visible_to_the_human(client: TestClient) -> None:
    facts = client.get("/audit/current").json()["beliefs"]
    denver = [b for b in facts if b["belief_id"] == "denver"][0]
    assert denver["valid_at_source"] == "derived" # confidence surfaced (#6)
    assert denver["valid_at_source_raw"] == "document:mtime"


def test_provenance_resolves_names_and_shows_uuid_when_unresolvable(client: TestClient) -> None:
    trace = client.get("/audit/provenance/boston").json()
    by = {p["uuid"]: p for p in trace["asserted_by"]}
    assert by["ep-v1"]["name"] == "acme_report_v1#chunk0" and by["ep-v1"]["resolved"] is True
    # G1 honesty: an unresolvable UUID is shown as the UUID, never guessed
    assert by["ep-missing"]["name"] is None
    assert by["ep-missing"]["display"] == "ep-missing" and by["ep-missing"]["resolved"] is False
    assert trace["superseded_by_episode"]["name"] == "acme_report_v2#chunk0"


def test_timeline_view_has_belief_and_trace(client: TestClient) -> None:
    body = client.get("/audit/timeline/boston").json()
    assert body["belief"]["statement"].endswith("Boston")
    assert body["belief"]["valid_at_source"] == "authoritative" # 'provided' -> authoritative
    assert body["trace"]["superseded_by_belief"] == "denver"
    assert client.get("/audit/timeline/nope").status_code == 404


def test_read_only_no_write_verbs(client: TestClient) -> None:
    assert client.post("/audit/current").status_code == 405
    assert client.put("/audit/current").status_code == 405
    assert client.delete("/audit/current").status_code == 405


def test_dashboard_is_served(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "Audit Dashboard" in r.text
    assert "/audit/replay" in r.text # the dashboard drives the centerpiece off replay
