"""Investigation aggregate and bounded ResearchRun contracts."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from ..base import ContractModel, Digest, JsonObject, NonEmptyString, VersionString
from ..enums import (
    DataAuthenticity,
    InvestigationStatus,
    InvestigationTransition,
    ResearchRunState,
    WaitingForInputReason,
)
from .common import ImmutableResource, MutableResource


class TimeRange(ContractModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def validate_order(self) -> TimeRange:
        if self.end <= self.start:
            raise ValueError("time range end must be after start")
        return self


class ResearchBudget(ContractModel):
    max_cost_usd: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    max_duration_seconds: int = Field(gt=0, le=86_400)


class ResearchSourceScope(ContractModel):
    source_connection_ids: list[UUID] = Field(min_length=1)
    content_version_ids: list[UUID] = Field(default_factory=list)
    allow_cloud_model: bool = False


class InvestigationCreateRequest(ContractModel):
    signal_id: UUID
    decision_question: NonEmptyString
    source_scope: ResearchSourceScope
    time_range: TimeRange
    budget: ResearchBudget
    stop_conditions: list[NonEmptyString] = Field(min_length=1)


class InvestigationUpdateRequest(ContractModel):
    decision_question: NonEmptyString
    source_scope: ResearchSourceScope
    time_range: TimeRange
    budget: ResearchBudget
    stop_conditions: list[NonEmptyString] = Field(min_length=1)
    change_reason: NonEmptyString
    expected_row_version: int = Field(ge=1)


class InvestigationResponse(MutableResource):
    project_id: UUID
    signal_id: UUID
    current_scope_version_id: UUID
    status: InvestigationStatus
    owner_id: UUID
    current_synthesis_id: UUID | None = None
    decision_brief_id: UUID | None = None
    decision_question: NonEmptyString
    data_authenticity: DataAuthenticity


class InvestigationScopeVersionResponse(ImmutableResource):
    investigation_id: UUID
    version_number: int = Field(ge=1)
    decision_question: NonEmptyString
    source_scope_json: JsonObject
    time_range: TimeRange
    budget: ResearchBudget
    stop_conditions: list[NonEmptyString]
    created_by: UUID
    change_reason: NonEmptyString
    created_at: AwareDatetime
    data_authenticity: DataAuthenticity


class InvestigationTransitionRequest(ContractModel):
    action: InvestigationTransition
    expected_row_version: int = Field(ge=1)
    reason: NonEmptyString


class ResearchRunCreateRequest(ContractModel):
    investigation_id: UUID
    investigation_scope_version_id: UUID
    question: NonEmptyString
    source_scope: ResearchSourceScope
    time_range: TimeRange
    budget: ResearchBudget
    expected_investigation_row_version: int = Field(ge=1)


class ResearchRunResponse(MutableResource):
    investigation_id: UUID
    investigation_scope_version_id: UUID
    state: ResearchRunState
    waiting_for_input_reason: WaitingForInputReason | None = None
    graph_version: VersionString
    run_input_manifest_digest: Digest
    budget: ResearchBudget
    used_cost_usd: Decimal = Field(ge=0, max_digits=10, decimal_places=4)
    attempt_number: int = Field(ge=1)
    initiated_by: UUID
    latest_sequence: int = Field(ge=0)
    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_wait_reason(self) -> ResearchRunResponse:
        if self.state == ResearchRunState.WAITING_FOR_INPUT:
            if self.waiting_for_input_reason is None:
                raise ValueError("waiting_for_input requires a reason")
        elif self.waiting_for_input_reason is not None:
            raise ValueError("waiting reason is valid only in waiting_for_input")
        return self


class ResearchRunCancelRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    reason: NonEmptyString
