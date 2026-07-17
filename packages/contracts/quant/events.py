"""Quant run event wire contracts and tolerant parsing helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from ..base import ContractModel, NonEmptyString
from ..enums import DataAuthenticity
from .enums import (
    QuantArtifactKind,
    QuantCandidateVerdict,
    QuantExperimentVerdict,
    QuantPlanDecision,
    QuantRunEventType,
    QuantRunState,
    QuantStreamControlEventType,
)

QUANT_EVENT_PERSISTENCE_TO_WIRE = MappingProxyType(
    {
        "quant_run_id": "run_id",
        "type": "event_type",
        "payload_json": "payload",
        "occurred_at": "timestamp",
        "event_id": "event_id",
        "sequence": "sequence",
        "trace_id": "trace_id",
    }
)

UNKNOWN_EVENT_SAFE_SUMMARY = "Run activity recorded."

QUANT_EVENT_SAFE_COPY = MappingProxyType(
    {
        QuantRunEventType.RUN_QUEUED: "The run was queued.",
        QuantRunEventType.PLAN_PROPOSED: "A plan revision was proposed for review.",
        QuantRunEventType.PLAN_AWAITING_APPROVAL: "The plan is waiting for approval.",
        QuantRunEventType.PLAN_APPROVED: "The pinned plan revision was approved.",
        QuantRunEventType.PLAN_CHANGES_REQUESTED: "Changes were requested for the plan.",
        QuantRunEventType.RUN_STARTED: "The approved run started.",
        QuantRunEventType.EXPERIMENT_PROPOSED: "An experiment candidate was proposed.",
        QuantRunEventType.EXPERIMENT_VERDICT_RECORDED: "An experiment verdict was recorded.",
        QuantRunEventType.ARTIFACT_PUBLISHED: "An artifact was published.",
        QuantRunEventType.RUN_COMPLETED: "The run completed.",
        QuantRunEventType.RUN_FAILED: "The run failed.",
        QuantRunEventType.RUN_CANCELLED: "The run was cancelled.",
    }
)


def safe_event_copy(event_type: str) -> str:
    try:
        return QUANT_EVENT_SAFE_COPY[QuantRunEventType(event_type)]
    except ValueError:
        return UNKNOWN_EVENT_SAFE_SUMMARY


class QuantRunEventPayload(ContractModel):
    state: QuantRunState | None = None
    run_state: QuantRunState | None = None
    plan_revision: int | None = Field(default=None, ge=1)
    plan_steps: list[NonEmptyString] | None = None
    candidate_id: UUID | None = None
    candidate_key: NonEmptyString | None = None
    experiment_id: UUID | None = None
    experiment_name: NonEmptyString | None = None
    verdict: QuantExperimentVerdict | QuantCandidateVerdict | None = None
    artifact_id: UUID | None = None
    artifact_kind: QuantArtifactKind | None = None
    attempt_number: int | None = Field(default=None, ge=1)
    repair_count: int | None = Field(default=None, ge=0)
    target_type: NonEmptyString | None = None
    target_id: UUID | None = None
    reason_code: NonEmptyString | None = None
    safe_summary: NonEmptyString | None = Field(default=None, max_length=500)


_PLAN_EVENT_TYPES = {
    QuantRunEventType.PLAN_PROPOSED,
    QuantRunEventType.PLAN_AWAITING_APPROVAL,
    QuantRunEventType.PLAN_APPROVED,
    QuantRunEventType.PLAN_CHANGES_REQUESTED,
}


class QuantRunEvent(ContractModel):
    quant_run_id: UUID = Field(
        validation_alias="run_id",
        serialization_alias="run_id",
    )
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED
    sequence: int = Field(ge=1)
    event_id: UUID
    type: QuantRunEventType = Field(
        validation_alias="event_type",
        serialization_alias="event_type",
    )
    payload_json: QuantRunEventPayload = Field(
        default_factory=QuantRunEventPayload,
        validation_alias="payload",
        serialization_alias="payload",
    )
    trace_id: NonEmptyString
    occurred_at: AwareDatetime = Field(validation_alias="timestamp", serialization_alias="timestamp")

    @model_validator(mode="after")
    def validate_event_payload(self) -> "QuantRunEvent":
        payload = self.payload_json
        if self.type in _PLAN_EVENT_TYPES and payload.plan_revision is None:
            raise ValueError(f"{self.type.value} requires plan_revision")
        if self.type == QuantRunEventType.PLAN_PROPOSED and payload.artifact_id is None:
            raise ValueError("plan.proposed requires artifact_id")
        if self.type in {
            QuantRunEventType.EXPERIMENT_PROPOSED,
            QuantRunEventType.EXPERIMENT_VERDICT_RECORDED,
        } and payload.experiment_id is None:
            raise ValueError(f"{self.type.value} requires experiment_id")
        if self.type == QuantRunEventType.EXPERIMENT_VERDICT_RECORDED and payload.verdict is None:
            raise ValueError("experiment.verdict_recorded requires verdict")
        if self.type == QuantRunEventType.ARTIFACT_PUBLISHED and (
            payload.artifact_id is None or payload.artifact_kind is None
        ):
            raise ValueError("artifact.published requires artifact_id and artifact_kind")
        if self.type == QuantRunEventType.RUN_FAILED and not payload.reason_code:
            raise ValueError("run.failed requires reason_code")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() != UTC.utcoffset(
            self.occurred_at
        ):
            raise ValueError("timestamp must use the UTC offset")
        return self

    def to_wire_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class UnknownQuantRunEvent(ContractModel):
    known: Literal[False] = False
    run_id: UUID | None = None
    sequence: int | None = Field(default=None, ge=1)
    event_id: UUID | None = None
    event_type: NonEmptyString
    trace_id: NonEmptyString | None = None
    timestamp: AwareDatetime | None = None
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED
    safe_summary: str = UNKNOWN_EVENT_SAFE_SUMMARY

    def to_wire_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


def decode_quant_event(data: dict[str, Any]) -> QuantRunEvent | UnknownQuantRunEvent:
    try:
        return QuantRunEvent.model_validate(data)
    except Exception:
        raw_type = data.get("event_type", data.get("type"))
        if not isinstance(raw_type, str) or not raw_type.strip():
            raise
        return UnknownQuantRunEvent(
            run_id=data.get("run_id", data.get("quant_run_id")),
            sequence=data.get("sequence"),
            event_id=data.get("event_id"),
            event_type=raw_type.strip(),
            trace_id=data.get("trace_id"),
            timestamp=data.get("timestamp", data.get("occurred_at")),
            data_authenticity=data.get("data_authenticity", DataAuthenticity.GENERATED),
        )


class QuantStreamResetEvent(ContractModel):
    event_type: QuantStreamControlEventType = QuantStreamControlEventType.RESET
    snapshot_url: NonEmptyString
    latest_sequence: int = Field(ge=0)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED

    @model_validator(mode="after")
    def validate_snapshot_url(self) -> "QuantStreamResetEvent":
        if not self.snapshot_url.startswith("/v1/quant/runs/") or "?" in self.snapshot_url:
            raise ValueError("snapshot_url must be an unsigned Quant run API route")
        return self


def encode_quant_sse(event: QuantRunEvent | UnknownQuantRunEvent | QuantStreamResetEvent) -> str:
    if isinstance(event, QuantRunEvent):
        payload = event.to_wire_dict()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return f"id: {event.event_id}\nevent: {event.type.value}\ndata: {encoded}\n\n"
    if isinstance(event, UnknownQuantRunEvent):
        payload = event.to_wire_dict()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return f"id: {event.event_id}\nevent: {event.event_type}\ndata: {encoded}\n\n"
    payload = event.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"event: {event.event_type.value}\ndata: {encoded}\n\n"


def encode_quant_heartbeat() -> str:
    return ": heartbeat\n\n"


# The deterministic fixture runtime uses the shorter name while the public
# run-event contract keeps the explicit name.  Both resolve to the same closed
# payload model rather than maintaining two subtly different payload schemas.
QuantEventPayload = QuantRunEventPayload
