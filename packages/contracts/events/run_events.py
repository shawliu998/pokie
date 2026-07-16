"""The single persistence-to-wire RunEvent mapping and SSE encoder."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, AwareDatetime, Field, field_validator, model_validator

from ..base import ContractModel, NonEmptyString
from ..enums import (
    BusinessRunEventType,
    DataAuthenticity,
    ResearchRunState,
    StreamControlEventType,
    WaitingForInputReason,
)

RUN_EVENT_PERSISTENCE_TO_WIRE = MappingProxyType(
    {
        "research_run_id": "run_id",
        "type": "event_type",
        "payload_json": "payload",
        "occurred_at": "timestamp",
        "event_id": "event_id",
        "sequence": "sequence",
        "trace_id": "trace_id",
    }
)


class RunEventPayload(ContractModel):
    """Closed, secret-free union of fields allowed in durable business events."""

    state: ResearchRunState | None = None
    signal_id: UUID | None = None
    investigation_scope_version_id: UUID | None = None
    waiting_reason: WaitingForInputReason | None = None
    task_id: UUID | None = None
    task_type: str | None = None
    tool_execution_id: UUID | None = None
    tool_name: str | None = None
    evidence_id: UUID | None = None
    evidence_review_id: UUID | None = None
    claim_id: UUID | None = None
    claim_version_id: UUID | None = None
    claim_review_id: UUID | None = None
    synthesis_version_id: UUID | None = None
    synthesis_review_id: UUID | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    status: ResearchRunState | None = None
    reason_code: str | None = None
    safe_summary: str | None = Field(default=None, max_length=500)


class RunEvent(ContractModel):
    """Persistence-shaped fields serialize only through the canonical wire aliases."""

    investigation_id: UUID = Field(exclude=True)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED
    research_run_id: UUID = Field(
        validation_alias=AliasChoices("research_run_id", "run_id"),
        serialization_alias="run_id",
    )
    sequence: int = Field(ge=1)
    event_id: UUID
    type: BusinessRunEventType = Field(
        validation_alias=AliasChoices("type", "event_type"),
        serialization_alias="event_type",
    )
    payload_json: RunEventPayload = Field(
        default_factory=RunEventPayload,
        validation_alias=AliasChoices("payload_json", "payload"),
        serialization_alias="payload",
    )
    trace_id: NonEmptyString
    occurred_at: AwareDatetime = Field(
        validation_alias=AliasChoices("occurred_at", "timestamp"),
        serialization_alias="timestamp",
    )

    @field_validator("occurred_at")
    @classmethod
    def timestamp_must_be_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("timestamp must use the UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_event_payload(self) -> RunEvent:
        event_type = self.type.value
        payload = self.payload_json
        if self.type == BusinessRunEventType.INVESTIGATION_STARTED_FROM_SIGNAL and (
            payload.signal_id is None or payload.investigation_scope_version_id is None
        ):
            raise ValueError(
                "investigation.started_from_signal requires signal and scope version IDs"
            )
        if event_type.startswith("task.") and payload.task_id is None:
            raise ValueError("task events require task_id")
        if event_type.startswith("tool.") and not payload.tool_name:
            raise ValueError("tool events require tool_name")
        if event_type.startswith("evidence.") and payload.evidence_id is None:
            raise ValueError("evidence events require evidence_id")
        if event_type.startswith("claim.") and (
            payload.claim_id is None or payload.claim_version_id is None
        ):
            raise ValueError("claim events require claim_id and claim_version_id")
        if event_type.startswith("synthesis.") and payload.synthesis_version_id is None:
            raise ValueError("synthesis events require synthesis_version_id")
        if (
            self.type == BusinessRunEventType.RUN_WAITING_FOR_INPUT
            and payload.waiting_reason is None
        ):
            raise ValueError("run.waiting_for_input requires waiting_reason")
        if self.type == BusinessRunEventType.REVIEW_REQUIRED and (
            not payload.target_type or payload.target_id is None
        ):
            raise ValueError("review.required requires target_type and target_id")
        return self

    def to_wire_dict(self) -> dict[str, Any]:
        """Return the public event shape; persistence-only fields cannot leak."""

        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class StreamResetEvent(ContractModel):
    """Transport control. It deliberately has no business event ID or sequence."""

    event_type: StreamControlEventType = StreamControlEventType.RESET
    snapshot_url: NonEmptyString
    latest_sequence: int = Field(ge=0)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED

    @field_validator("snapshot_url")
    @classmethod
    def require_snapshot_route(cls, value: str) -> str:
        if not value.startswith("/v1/research-runs/") or "?" in value or "#" in value:
            raise ValueError("snapshot_url must be an unsigned ResearchRun API route")
        return value


def encode_sse(event: RunEvent | StreamResetEvent) -> str:
    """Encode a durable business event or reset control with deterministic JSON."""

    if isinstance(event, RunEvent):
        payload = event.to_wire_dict()
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return f"id: {event.event_id}\nevent: {event.type.value}\ndata: {data}\n\n"
    payload = event.model_dump(mode="json", exclude_none=True)
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"event: {event.event_type.value}\ndata: {data}\n\n"


def encode_heartbeat() -> str:
    """SSE heartbeat comments are not events and consume no sequence."""

    return ": heartbeat\n\n"
