"""RunEvent payload validation before persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

ALLOWED_PAYLOAD_FIELDS = {
    "state",
    "waiting_reason",
    "task_id",
    "task_type",
    "tool_execution_id",
    "tool_name",
    "evidence_id",
    "evidence_review_id",
    "claim_id",
    "claim_version_id",
    "claim_review_id",
    "synthesis_version_id",
    "synthesis_review_id",
    "target_type",
    "target_id",
    "status",
    "reason_code",
    "safe_summary",
}


class RunEventContractError(ValueError):
    """Raised when worker code tries to emit a non-contract RunEvent payload."""


def validate_run_event_payload(event_type: str, payload: dict[str, object]) -> None:
    extra = sorted(set(payload) - ALLOWED_PAYLOAD_FIELDS)
    if extra:
        raise RunEventContractError(
            f"{event_type} payload has non-contract fields: {', '.join(extra)}"
        )
    if event_type.startswith("task.") and not payload.get("task_id"):
        raise RunEventContractError(f"{event_type} requires task_id")
    if event_type.startswith("tool.") and not payload.get("tool_name"):
        raise RunEventContractError(f"{event_type} requires tool_name")
    if event_type.startswith("evidence.") and not payload.get("evidence_id"):
        raise RunEventContractError(f"{event_type} requires evidence_id")
    if event_type.startswith("claim.") and (
        not payload.get("claim_id") or not payload.get("claim_version_id")
    ):
        raise RunEventContractError(f"{event_type} requires claim_id and claim_version_id")
    if event_type.startswith("synthesis.") and not payload.get("synthesis_version_id"):
        raise RunEventContractError(f"{event_type} requires synthesis_version_id")
    if event_type == "review.required" and (
        not payload.get("target_type") or not payload.get("target_id")
    ):
        raise RunEventContractError("review.required requires target_type and target_id")
    _validate_with_shared_contract_when_available(event_type, payload)


def _validate_with_shared_contract_when_available(
    event_type: str, payload: dict[str, object]
) -> None:
    try:
        from packages.contracts.events.run_events import RunEvent, RunEventPayload
    except Exception:
        return
    try:
        RunEvent(
            investigation_id=uuid4(),
            research_run_id=uuid4(),
            sequence=1,
            event_id=uuid4(),
            type=cast(Any, event_type),
            payload_json=RunEventPayload(**cast(Any, payload)),
            trace_id="worker-contract-validation",
            occurred_at=datetime.now(tz=UTC),
        )
    except Exception as exc:
        raise RunEventContractError(str(exc)) from exc
