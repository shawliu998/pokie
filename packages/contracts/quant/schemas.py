"""Quant REST schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from ..base import ContractModel, NonEmptyString
from ..enums import DataAuthenticity
from ..schemas.common import ImmutableResource, MutableResource
from .enums import (
    QuantArtifactKind,
    QuantArtifactReviewStatus,
    QuantExperimentVerdict,
    QuantPlanDecision,
    QuantProjectStatus,
    QuantRunMode,
    QuantRunState,
)


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


class QuantRunResponse(MutableResource):
    project_id: UUID
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
