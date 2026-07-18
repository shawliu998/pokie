"""Quant REST schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
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


class QuantNasdaqEquityFetchRequest(ContractModel):
    name: NonEmptyString | None = Field(default=None, max_length=200)
    symbol: NonEmptyString = Field(default="AAPL", pattern=r"^[A-Z][A-Z.\-]{0,9}$")
    lookback_days: int = Field(default=730, ge=370, le=3650)


class QuantProviderResponseAttestation(ContractModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["daily_bars", "instrument_info", "dividends", "splits"]
    digest: Digest
    source_reference: NonEmptyString = Field(max_length=2000)


class QuantSplitEventSummary(ContractModel):
    model_config = ConfigDict(frozen=True)

    effective_date: date
    ratio_numerator: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    ratio_denominator: Decimal = Field(gt=0, max_digits=18, decimal_places=8)


class QuantCorporateActionsAttestation(ContractModel):
    model_config = ConfigDict(frozen=True)

    dividends_status: Literal[
        "not_requested", "unavailable", "retrieved_unverified", "verified", "conflict"
    ]
    splits_status: Literal[
        "not_requested", "unavailable", "retrieved_unverified", "verified", "conflict"
    ]
    # Deprecated dividend aliases retained so Phase 1D records remain readable.
    coverage_start: date | None = None
    coverage_end: date | None = None
    dividend_coverage_start: date | None = None
    dividend_coverage_end: date | None = None
    split_coverage_start: date | None = None
    split_coverage_end: date | None = None
    split_snapshot_as_of: date | None = None
    split_completeness_status: Literal[
        "unknown", "current_snapshot_only", "partial_history", "historically_complete"
    ] = "unknown"
    split_reconciliation_status: Literal[
        "not_attempted", "consistent", "conflict", "unavailable"
    ] = "unavailable"
    dividend_event_count: int | None = Field(default=None, ge=0)
    split_event_count: int | None = Field(default=None, ge=0)
    split_events: tuple[QuantSplitEventSummary, ...] = Field(default=(), max_length=100)
    note: NonEmptyString = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_coverage(self) -> QuantCorporateActionsAttestation:
        coverage_pairs = (
            (self.coverage_start, self.coverage_end, "legacy dividend"),
            (self.dividend_coverage_start, self.dividend_coverage_end, "dividend"),
            (self.split_coverage_start, self.split_coverage_end, "split"),
        )
        for start, end, label in coverage_pairs:
            if start is not None and end is not None and start > end:
                raise ValueError(f"{label} coverage start must not exceed end")
        if (
            self.coverage_start is not None
            and self.dividend_coverage_start is not None
            and self.coverage_start != self.dividend_coverage_start
        ) or (
            self.coverage_end is not None
            and self.dividend_coverage_end is not None
            and self.coverage_end != self.dividend_coverage_end
        ):
            raise ValueError("legacy and explicit dividend coverage must agree")
        if self.split_completeness_status == "current_snapshot_only" and (
            self.splits_status != "retrieved_unverified"
            or self.split_snapshot_as_of is None
            or self.split_coverage_start is None
            or self.split_coverage_end is None
        ):
            raise ValueError(
                "current split snapshot requires retrieved evidence and bounded coverage"
            )
        if self.split_snapshot_as_of is not None and (
            self.split_coverage_start is None
            or self.split_coverage_end is None
            or not (
                self.split_coverage_start
                <= self.split_snapshot_as_of
                <= self.split_coverage_end
            )
        ):
            raise ValueError("split snapshot date must lie within split coverage")
        if self.split_events:
            if self.split_event_count != len(self.split_events):
                raise ValueError("split event count must match retained split events")
            if self.split_coverage_start is None or self.split_coverage_end is None:
                raise ValueError("retained split events require split coverage")
            if any(
                not self.split_coverage_start
                <= event.effective_date
                <= self.split_coverage_end
                for event in self.split_events
            ):
                raise ValueError("retained split events must lie within split coverage")
        elif (
            self.split_completeness_status == "current_snapshot_only"
            and self.split_event_count != 0
        ):
            raise ValueError("empty current split snapshot requires zero target events")
        return self


class QuantDatasetSourceMetadata(ContractModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["csv_upload", "provider_fetch"] = "csv_upload"
    file_name: NonEmptyString | None = Field(default=None, max_length=255)
    source_name: NonEmptyString = Field(default="User-provided CSV", max_length=200)
    source_reference: NonEmptyString | None = Field(default=None, max_length=2000)
    submitted_csv_digest: Digest | None = None
    provider_id: Literal["binance_spot", "nasdaq_equity"] | None = None
    provider_response_digest: Digest | None = None
    provider_response_attestations: tuple[QuantProviderResponseAttestation, ...] = ()
    corporate_actions_attestation: QuantCorporateActionsAttestation | None = None
    price_adjustment_verification_status: Literal[
        "not_applicable", "unverified", "verified", "conflict"
    ] = "unverified"
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
        if self.provider_response_attestations and not any(
            item.kind == "daily_bars" for item in self.provider_response_attestations
        ):
            raise ValueError("provider response attestations require daily_bars evidence")
        response_kinds = [item.kind for item in self.provider_response_attestations]
        if len(response_kinds) != len(set(response_kinds)):
            raise ValueError("provider response attestation kinds must be unique")
        daily_evidence = next(
            (
                item
                for item in self.provider_response_attestations
                if item.kind == "daily_bars"
            ),
            None,
        )
        if (
            daily_evidence is not None
            and daily_evidence.digest != self.provider_response_digest
        ):
            raise ValueError("daily-bars evidence must match provider response digest")
        if self.provider_id == "nasdaq_equity" and set(response_kinds) not in (
            {"daily_bars", "instrument_info", "dividends"},
            {"daily_bars", "instrument_info", "dividends", "splits"},
        ):
            raise ValueError(
                "Nasdaq equity metadata requires bars, listing, dividends, "
                "and optional split evidence"
            )
        actions = self.corporate_actions_attestation
        if actions is not None:
            if self.provider_id != "nasdaq_equity":
                raise ValueError("corporate-action evidence is only supported for Nasdaq equity")
            if actions.dividends_status in {
                "retrieved_unverified",
                "verified",
                "conflict",
            } and "dividends" not in response_kinds:
                raise ValueError("dividend status requires dividend response evidence")
            if actions.splits_status in {
                "retrieved_unverified",
                "verified",
                "conflict",
            } and "splits" not in response_kinds:
                raise ValueError("split status requires split response evidence")
            if (
                actions.split_completeness_status != "unknown"
                and "splits" not in response_kinds
            ):
                raise ValueError("split completeness requires split response evidence")
        if self.kind == "csv_upload" and (
            self.provider_response_attestations
            or self.corporate_actions_attestation is not None
        ):
            raise ValueError("CSV metadata cannot contain provider evidence")
        if self.price_adjustment == "unadjusted":
            if self.price_adjustment_verification_status not in {
                "not_applicable",
                "unverified",
            }:
                raise ValueError("unadjusted prices cannot claim adjustment verification")
        elif self.price_adjustment_verification_status == "verified":
            if actions is None or actions.splits_status != "verified":
                raise ValueError("verified adjusted prices require verified split evidence")
            if (
                self.price_adjustment == "total_return_adjusted"
                and actions.dividends_status != "verified"
            ):
                raise ValueError(
                    "verified total-return prices require verified dividend evidence"
                )
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
