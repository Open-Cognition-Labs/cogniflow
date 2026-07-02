"""record_observation agent tool (seam d).

The tool enqueues a write and returns immediately with an acknowledgement (an
observation id + status), never calling the backend synchronously and never awaiting
ingestion. The observation id is derived deterministically from the content, so a
retry of the same observation collapses via the backend's dedup (idempotency key).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from llama_index.core.tools import FunctionTool

from ...core.contracts import AsyncSubstrate
from ...core.policies import FalsificationPolicy
from ...core.types import Belief, RetrievalQuery, utc_now
from ...writeback import Observation, WriteBackQueue


def _parse_when(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        if len(value) == 4 and value.isdigit():
            return datetime(int(value), 1, 1, tzinfo=timezone.utc)
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _observation_id(group_id: str, parts: list[str]) -> str:
    key = "|".join([group_id, *parts])
    return "obs-" + hashlib.sha1(key.encode()).hexdigest()[:16]


def make_record_observation_tool(queue: WriteBackQueue, group_id: str) -> FunctionTool:
    """Build a ``record_observation`` tool bound to a queue + group_id."""

    async def record_observation(
        statement: str,
        subject: str = "",
        predicate: str = "",
        obj: str = "",
        valid_at: str = "",
    ) -> str:
        """Record a new time-stamped fact (for example, a company changing its
        headquarters). Enqueues the write and returns immediately; the fact becomes
        readable only after ingestion. Provide subject/predicate/obj and a valid_at
        date (a year like 2024 or an ISO date) whenever known."""
        triple = None
        if subject and predicate and obj:
            triple = {
                "source": subject,
                "predicate": predicate,
                "target": obj,
                "fact": statement,
            }
        obs_id = _observation_id(group_id, [statement, subject, predicate, obj, valid_at])
        ack = queue.enqueue(
            Observation(
                id=obs_id,
                group_id=group_id,
                statement=statement,
                triple=triple,
                reference_time=_parse_when(valid_at),
            )
        )
        if ack.status == "queued":
            return f"queued observation {obs_id} (ingested asynchronously)"
        return f"not recorded ({ack.reason})"

    return FunctionTool.from_defaults(
        fn=record_observation,
        name="record_observation",
        description=(
            "Record a new time-stamped fact. Enqueues a write and returns immediately; "
            "the fact becomes readable after ingestion."
        ),
    )


def make_verify_fact_tool(substrate: AsyncSubstrate, policy: FalsificationPolicy) -> FunctionTool:
    """Build a read-only ``verify_fact`` tool .

    It reads candidate beliefs and runs the (LLM) FalsificationPolicy to advise whether
    a stated fact is contradicted/superseded. It NEVER writes: to record a correction
    the agent must call ``record_observation`` (the queued write-back path). An
    indeterminate verdict is surfaced as such, never as "not contradicted".
    """

    async def verify_fact(
        statement: str,
        subject: str = "",
        predicate: str = "",
        obj: str = "",
        valid_at: str = "",
    ) -> str:
        """Check (read-only) whether a stated fact is contradicted or superseded by known
        beliefs. Advisory only; this does NOT record anything."""
        target = Belief(
            id="__verify__",
            statement=statement,
            created_at=utc_now(),
            valid_at=_parse_when(valid_at),
        )
        result = await substrate.read(
            RetrievalQuery(text=statement, as_of=None, top_k=10, include_expired=True)
        )
        candidates = [s.belief for s in result.results]
        verdict = policy.assess(target, candidates)
        if verdict.indeterminate:
            return f"indeterminate: {verdict.rationale}"
        if verdict.superseded:
            return f"contradicted (superseded_by={verdict.superseded_by}): {verdict.rationale}"
        return f"not contradicted: {verdict.rationale}"

    return FunctionTool.from_defaults(
        fn=verify_fact,
        name="verify_fact",
        description=(
            "Check (read-only) whether a stated fact is contradicted or superseded by "
            "known beliefs. Advisory; records nothing."
        ),
    )
