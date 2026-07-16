from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from packages.contracts.events.run_events import RunEvent as ContractRunEvent
from packages.domain.redaction import redact as redact_diagnostic
from services.api.app.db.models import AuditLog, Investigation, ResearchRun, RunEvent, new_id


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    payload = value if isinstance(value, bytes) else canonical_json(value).encode()
    if isinstance(payload, str):
        payload = payload.encode()
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def text_digest(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def lock_investigation_lineage(
    db: Session, *, workspace_id: str, investigation_id: str
) -> Investigation:
    """Serialize mutations that can change a Decision Brief's authoritative lineage."""

    locked = db.scalar(
        select(Investigation)
        .where(
            Investigation.id == investigation_id,
            Investigation.workspace_id == workspace_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise ValueError("Investigation lineage root does not exist in the workspace")
    return locked


def redact(value: Any) -> Any:
    return redact_diagnostic(value)


def audit(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    request_id: str,
    before: Any = None,
    after: Any = None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    row = AuditLog(
        workspace_id=workspace_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_digest=digest(before) if before is not None else None,
        after_digest=digest(after) if after is not None else None,
        reason=redact(reason) if reason else None,
        request_id=request_id,
        details_json=redact(details or {}),
    )
    db.add(row)
    return row


def append_run_event(
    db: Session,
    *,
    workspace_id: str,
    investigation_id: str,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
    trace_id: str,
    event_idempotency_key: str | None = None,
) -> RunEvent:
    stable_key = event_idempotency_key or digest(
        {"event_type": event_type, "payload": payload, "run_id": run_id}
    )
    # A no-op update acquires the per-run database row lock before the idempotency check.
    locked = db.scalar(
        update(ResearchRun)
        .where(
            ResearchRun.id == run_id,
            ResearchRun.workspace_id == workspace_id,
        )
        .values(latest_sequence=ResearchRun.latest_sequence)
        .returning(ResearchRun.id)
    )
    if locked is None:
        raise ValueError("RunEvent owner does not exist in the workspace")
    existing = db.scalar(
        select(RunEvent).where(
            RunEvent.research_run_id == run_id,
            RunEvent.idempotency_key == stable_key,
        )
    )
    if existing is not None:
        return existing
    sequence = db.scalar(
        update(ResearchRun)
        .where(ResearchRun.id == run_id)
        .values(latest_sequence=ResearchRun.latest_sequence + 1)
        .returning(ResearchRun.latest_sequence)
    )
    if sequence is None:
        raise ValueError("Could not allocate a RunEvent sequence")
    event_id = new_id()
    occurred_at = utcnow()
    run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id))
    persistence = {
        "investigation_id": investigation_id,
        "research_run_id": run_id,
        "sequence": sequence,
        "event_id": event_id,
        "type": event_type,
        "payload_json": redact(payload),
        "trace_id": trace_id,
        "occurred_at": occurred_at,
    }
    if "data_authenticity" in ContractRunEvent.model_fields:
        persistence["data_authenticity"] = run.data_authenticity if run else "generated"
    ContractRunEvent.model_validate(persistence)
    event = RunEvent(
        workspace_id=workspace_id,
        investigation_id=investigation_id,
        research_run_id=run_id,
        sequence=sequence,
        event_id=event_id,
        idempotency_key=stable_key,
        type=event_type,
        payload_json=redact(payload),
        trace_id=trace_id,
        occurred_at=occurred_at,
        data_authenticity=run.data_authenticity if run else "generated",
    )
    db.add(event)
    db.flush()
    return event


def utcnow() -> datetime:
    return datetime.now(UTC)
