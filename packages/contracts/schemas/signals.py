"""Explainable Signal projections and human-owned assessment commands."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from ..base import ContractModel, JsonObject, NonEmptyString, VersionString
from ..enums import (
    BusinessImpactLevel,
    CalibrationStatus,
    DataAuthenticity,
    DetectionConfidenceLevel,
    PriorityLevel,
    PriorityStatus,
    SignalAssessmentDimension,
    SignalDismissReason,
    SignalEvidenceRole,
    SignalStatus,
    SignalTransition,
    SourceFreshnessState,
    SuggestionOrigin,
    UrgencyLevel,
)
from .common import MutableResource


class PerSourceFreshness(ContractModel):
    source_connection_id: UUID
    state: SourceFreshnessState
    last_success_at: AwareDatetime | None = None


class SignalWindow(ContractModel):
    current_start: AwareDatetime
    current_end: AwareDatetime
    baseline_start: AwareDatetime
    baseline_end: AwareDatetime


class SignalMetrics(ContractModel):
    current_count: int = Field(ge=0)
    baseline_count: int = Field(ge=0)
    mention_count: int = Field(ge=0)
    independent_source_count: int = Field(ge=0)
    platform_count: int = Field(ge=0)
    growth_ratio: float = Field(ge=0)
    robust_z: float


class DetectionConfidence(ContractModel):
    level: DetectionConfidenceLevel
    calibration_status: CalibrationStatus
    explanation: NonEmptyString


class ImpactAssessment(ContractModel):
    suggested_level: BusinessImpactLevel | None = None
    suggested_explanation: str | None = None
    suggestion_origin: SuggestionOrigin
    suggestion_version: str | None = None
    confirmed_level: BusinessImpactLevel | None = None
    confirmed_by: UUID | None = None
    confirmed_at: AwareDatetime | None = None
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_confirmation(self) -> ImpactAssessment:
        values = (self.confirmed_level, self.confirmed_by, self.confirmed_at)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("confirmed_level, confirmed_by, and confirmed_at must appear together")
        return self


class UrgencyAssessment(ContractModel):
    suggested_level: UrgencyLevel | None = None
    suggested_explanation: str | None = None
    suggestion_origin: SuggestionOrigin
    suggestion_version: str | None = None
    confirmed_level: UrgencyLevel | None = None
    confirmed_by: UUID | None = None
    confirmed_at: AwareDatetime | None = None
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_confirmation(self) -> UrgencyAssessment:
        values = (self.confirmed_level, self.confirmed_by, self.confirmed_at)
        if any(value is not None for value in values) and not all(
            value is not None for value in values
        ):
            raise ValueError("confirmed_level, confirmed_by, and confirmed_at must appear together")
        return self


class SignalPriority(ContractModel):
    level: PriorityLevel | None = None
    status: PriorityStatus
    policy_version: VersionString
    explanation: NonEmptyString

    @model_validator(mode="after")
    def validate_level(self) -> SignalPriority:
        if self.status == PriorityStatus.DERIVED and self.level is None:
            raise ValueError("derived priority requires a level")
        if self.status != PriorityStatus.DERIVED and self.level is not None:
            raise ValueError("non-derived priority must not have a level")
        return self


class SignalDimensions(ContractModel):
    detection_confidence: DetectionConfidence
    business_impact: ImpactAssessment
    urgency: UrgencyAssessment
    priority: SignalPriority


class SignalDisposition(ContractModel):
    transition_id: UUID
    action: SignalTransition
    previous_status: SignalStatus
    session_id: UUID
    monitoring_snapshot: JsonObject | None = None
    cooldown_until: AwareDatetime | None = None
    dismiss_reason: SignalDismissReason | None = None
    note: NonEmptyString | None = None
    transitioned_by: UUID
    transitioned_at: AwareDatetime
    cooldown_broken_at: AwareDatetime | None = None
    cooldown_break_reason: NonEmptyString | None = None
    undone_at: AwareDatetime | None = None


class SignalResponse(MutableResource):
    watchlist_id: UUID
    title: NonEmptyString
    status: SignalStatus
    detector_version: VersionString
    trigger_rules: list[NonEmptyString]
    limitations: list[NonEmptyString]
    total_source_count: int = Field(ge=0)
    independent_source_count: int = Field(ge=0)
    cross_source_confirmation: bool
    per_source_freshness: list[PerSourceFreshness]
    window: SignalWindow
    metrics: SignalMetrics
    dimensions: SignalDimensions
    disposition: SignalDisposition | None = None
    data_authenticity: DataAuthenticity


class SignalEvidenceResponse(ContractModel):
    signal_id: UUID
    content_version_id: UUID
    role: SignalEvidenceRole
    independence_group_id: UUID | None = None
    contribution: float = Field(ge=-1, le=1)
    data_authenticity: DataAuthenticity


class ConfirmImpact(ContractModel):
    confirmed_level: BusinessImpactLevel
    reason: NonEmptyString
    expected_assessment_version: int = Field(ge=0)


class ConfirmUrgency(ContractModel):
    confirmed_level: UrgencyLevel
    reason: NonEmptyString
    expected_assessment_version: int = Field(ge=0)


class SignalTriageRequest(ContractModel):
    expected_signal_row_version: int = Field(ge=1)
    business_impact: ConfirmImpact
    urgency: ConfirmUrgency


class SignalAssessmentRequest(ContractModel):
    dimension: SignalAssessmentDimension
    confirmed_level: BusinessImpactLevel | UrgencyLevel
    reason: NonEmptyString
    expected_signal_row_version: int = Field(ge=1)
    expected_assessment_version: int = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def select_dimension_enum(cls, value: object) -> object:
        if isinstance(value, dict):
            normalized = dict(value)
            dimension = normalized.get("dimension")
            level = normalized.get("confirmed_level")
            if dimension == SignalAssessmentDimension.BUSINESS_IMPACT.value:
                normalized["confirmed_level"] = BusinessImpactLevel(level)
            elif dimension == SignalAssessmentDimension.URGENCY.value:
                normalized["confirmed_level"] = UrgencyLevel(level)
            return normalized
        return value

    @model_validator(mode="after")
    def validate_level_for_dimension(self) -> SignalAssessmentRequest:
        if self.dimension == SignalAssessmentDimension.BUSINESS_IMPACT and not isinstance(
            self.confirmed_level, BusinessImpactLevel
        ):
            raise ValueError("business_impact requires a BusinessImpactLevel")
        if self.dimension == SignalAssessmentDimension.URGENCY and not isinstance(
            self.confirmed_level, UrgencyLevel
        ):
            raise ValueError("urgency requires an UrgencyLevel")
        return self


class SignalTransitionRequest(ContractModel):
    action: SignalTransition
    expected_row_version: int = Field(ge=1)
    session_id: UUID
    cooldown_until: AwareDatetime | None = None
    dismiss_reason: SignalDismissReason | None = None
    note: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> SignalTransitionRequest:
        if self.action == SignalTransition.MONITOR and self.cooldown_until is None:
            raise ValueError("monitor requires cooldown_until")
        if self.action == SignalTransition.DISMISS and (
            self.dismiss_reason is None or self.note is None
        ):
            raise ValueError("dismiss requires dismiss_reason and note")
        if self.action not in {SignalTransition.MONITOR} and self.cooldown_until is not None:
            raise ValueError("cooldown_until is only valid for monitor")
        if self.action != SignalTransition.DISMISS and self.dismiss_reason is not None:
            raise ValueError("dismiss_reason is only valid for dismiss")
        return self
