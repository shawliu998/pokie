"""Quant REST schemas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ConfigDict, Field, field_validator, model_validator

from ..base import ContractModel, Digest, NonEmptyString, VersionString
from ..enums import DataAuthenticity
from ..schemas.common import ImmutableResource, MutableResource
from .data import QuantDailyBarInterval
from .enums import (
    QuantArtifactKind,
    QuantArtifactReviewStatus,
    QuantExperimentVerdict,
    QuantPlanDecision,
    QuantProjectStatus,
    QuantRunMode,
    QuantRunState,
)
from .quality import QuantDatasetDataQuality

QuantMarketCalendar = Literal[
    "unknown", "weekday", "24x7", "XNYS", "XNAS", "XSHG", "XSHE"
]


def _validated_time_zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("time_zone must be a valid IANA time zone") from exc
    return value


class QuantDatasetImportRequest(ContractModel):
    name: NonEmptyString = Field(max_length=200)
    symbol: NonEmptyString = Field(pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,15}$")
    csv_text: NonEmptyString = Field(max_length=10_000_000)
    file_name: NonEmptyString | None = Field(default=None, max_length=255)
    source_name: NonEmptyString = Field(default="User-provided CSV", max_length=200)
    source_reference: NonEmptyString | None = Field(default=None, max_length=2000)
    market_calendar: QuantMarketCalendar = "unknown"
    time_zone: NonEmptyString = Field(default="UTC", max_length=100)
    price_adjustment: Literal[
        "unknown", "unadjusted", "split_adjusted", "total_return_adjusted"
    ] = "unknown"

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        return _validated_time_zone(value)


class QuantBinanceSpotFetchRequest(ContractModel):
    name: NonEmptyString | None = Field(default=None, max_length=200)
    symbol: NonEmptyString = Field(default="BTCUSDT", pattern=r"^[A-Z][A-Z0-9]{4,15}$")
    interval: Literal["1d"] = "1d"
    limit: int = Field(default=365, ge=252, le=1000)


class QuantDatasetSourceMetadata(ContractModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["csv_upload", "provider_fetch"] = "csv_upload"
    file_name: NonEmptyString | None = Field(default=None, max_length=255)
    source_name: NonEmptyString = Field(default="User-provided CSV", max_length=200)
    source_reference: NonEmptyString | None = Field(default=None, max_length=2000)
    submitted_csv_digest: Digest | None = None
    provider_id: Literal["binance_spot"] | None = None
    provider_response_digest: Digest | None = None
    retrieved_at: datetime | None = None
    requested_limit: int | None = Field(default=None, ge=1)
    returned_bar_count: int | None = Field(default=None, ge=1)
    dropped_incomplete_count: int | None = Field(default=None, ge=0)
    normalization_note: NonEmptyString | None = Field(default=None, max_length=1000)
    attestation_status: Literal["declared", "provider_retrieved"] = "declared"
    market_calendar: QuantMarketCalendar = "unknown"
    time_zone: NonEmptyString = Field(default="UTC", max_length=100)
    price_adjustment: Literal[
        "unknown", "unadjusted", "split_adjusted", "total_return_adjusted"
    ] = "unknown"

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        return _validated_time_zone(value)

    @model_validator(mode="after")
    def validate_provider_attestation(self) -> QuantDatasetSourceMetadata:
        provider_fields = (
            self.provider_id,
            self.provider_response_digest,
            self.retrieved_at,
            self.requested_limit,
            self.returned_bar_count,
            self.dropped_incomplete_count,
            self.normalization_note,
        )
        if self.kind == "provider_fetch":
            if any(value is None for value in provider_fields):
                raise ValueError("provider_fetch metadata requires provider attestation fields")
            if self.attestation_status != "provider_retrieved":
                raise ValueError("provider_fetch metadata requires provider_retrieved status")
        elif any(value is not None for value in provider_fields):
            raise ValueError("CSV metadata cannot contain provider attestation fields")
        elif self.attestation_status != "declared":
            raise ValueError("CSV metadata requires declared attestation status")
        return self


class QuantDatasetResponse(ContractModel):
    dataset_id: VersionString
    workspace_id: UUID
    name: NonEmptyString
    symbol: NonEmptyString
    interval: QuantDailyBarInterval
    covered_start: date
    covered_end: date
    bar_count: int = Field(ge=1)
    schema_version: VersionString
    parser_version: VersionString
    digest: Digest
    source_metadata: QuantDatasetSourceMetadata
    data_quality: QuantDatasetDataQuality
    data_authenticity: DataAuthenticity
    created_at: datetime


class QuantProjectCreateRequest(ContractModel):
    name: NonEmptyString = Field(max_length=200)
    objective: NonEmptyString = Field(max_length=2000)


class QuantProjectResponse(MutableResource):
    name: NonEmptyString
    objective: NonEmptyString
    status: QuantProjectStatus
    data_authenticity: DataAuthenticity


class QuantRunCreateRequest(ContractModel):
    project_id: UUID
    mode: QuantRunMode = QuantRunMode.PLAN
    question: NonEmptyString = Field(max_length=2000)
    expected_project_row_version: int = Field(ge=1)
    dataset_id: VersionString | None = None


class QuantRunResponse(MutableResource):
    project_id: UUID
    dataset_id: VersionString
    dataset_digest: Digest
    state: QuantRunState
    mode: QuantRunMode
    question: NonEmptyString
    plan_revision: int = Field(ge=0)
    attempt_number: int = Field(ge=1)
    retry_of_run_id: UUID | None = None
    latest_sequence: int = Field(ge=0)
    trace_id: NonEmptyString
    failure_reason: NonEmptyString | None = None
    agent_iteration: int = Field(default=0, ge=0)
    agent_status: NonEmptyString = "idle"
    max_agent_iterations: int = Field(default=12, ge=1)
    max_experiments: int = Field(default=3, ge=0)
    max_repairs: int = Field(default=2, ge=0)
    used_experiments: int = Field(default=0, ge=0)
    used_repairs: int = Field(default=0, ge=0)
    last_action: NonEmptyString | None = None
    last_observation: NonEmptyString | None = None
    final_conclusion: NonEmptyString | None = None
    provider: NonEmptyString = "mock"
    model: NonEmptyString | None = None
    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_state_fields(self) -> QuantRunResponse:
        if self.state == QuantRunState.FAILED:
            if self.failure_reason is None:
                raise ValueError("a failed Quant run requires failure_reason")
        elif self.failure_reason is not None:
            raise ValueError("failure_reason is valid only for a failed Quant run")
        if (
            self.state
            in {
                QuantRunState.WAITING_PLAN_APPROVAL,
                QuantRunState.RUNNING_EXPERIMENTS,
                QuantRunState.COMPLETED,
            }
            and self.plan_revision < 1
        ):
            raise ValueError(f"{self.state.value} requires a published plan revision")
        return self


class QuantPlanApproveRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    reason: NonEmptyString = Field(default="Plan approved.", max_length=500)


class QuantPlanChangesRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    change_request: NonEmptyString = Field(max_length=1000)


class QuantRunCancelRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    reason: NonEmptyString = Field(max_length=500)


class QuantRunRetryRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    reason: NonEmptyString = Field(max_length=500)


class QuantFixtureCommandRequest(ContractModel):
    command: Literal[
        "ask",
        "generate_plan",
        "start_auto_research",
        "approve_plan",
        "run_fixture",
        "request_plan_changes",
        "cancel_run",
        "retry_run",
        "complete_review",
    ]
    expected_row_version: int = Field(ge=1)
    payload: dict[str, object] = Field(default_factory=dict)


class QuantPlanDecisionResponse(ImmutableResource):
    run_id: UUID
    plan_revision: int = Field(ge=1)
    decision: QuantPlanDecision
    actor_id: UUID
    reason: NonEmptyString
    request_id: NonEmptyString
    occurred_at: datetime
    data_authenticity: DataAuthenticity


class QuantExperimentResponse(ImmutableResource):
    run_id: UUID
    ordinal: int = Field(ge=1)
    name: NonEmptyString
    hypothesis: NonEmptyString
    verdict: QuantExperimentVerdict
    summary: NonEmptyString
    template: NonEmptyString = "fixture"
    parameters: dict[str, object] = Field(default_factory=dict)
    state: NonEmptyString = "completed"
    metrics: dict[str, object] = Field(default_factory=dict)
    repair_count: int = Field(default=0, ge=0)
    candidate_key: NonEmptyString | None = None
    parent_experiment_id: NonEmptyString | None = None
    created_at: datetime
    data_authenticity: DataAuthenticity


class QuantArtifactResponse(ImmutableResource):
    run_id: UUID
    ordinal: int = Field(ge=1)
    kind: QuantArtifactKind
    title: NonEmptyString
    digest: NonEmptyString
    review_status: QuantArtifactReviewStatus
    created_at: datetime
    data_authenticity: DataAuthenticity
