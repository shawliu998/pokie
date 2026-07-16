"""Workspace, project, and watchlist request/response contracts."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, Field

from ..base import ContractModel, NonEmptyString, VersionString
from ..enums import (
    DataAuthenticity,
    InitialBaselineStatus,
    MembershipStatus,
    ProjectStatus,
    WatchlistCadence,
    WatchlistStatus,
    WorkspaceRole,
    WorkspaceStatus,
)
from .common import MutableResource


class WorkspaceCreateRequest(ContractModel):
    name: NonEmptyString
    data_region: NonEmptyString = "default"
    retention_policy_version: VersionString = "retention-v1"


class WorkspaceUpdateRequest(ContractModel):
    name: NonEmptyString | None = None
    retention_policy_version: VersionString | None = None
    expected_row_version: int = Field(ge=1)


class WorkspaceResponse(MutableResource):
    name: NonEmptyString
    status: WorkspaceStatus
    data_region: NonEmptyString
    retention_policy_version: VersionString
    data_authenticity: DataAuthenticity


class WorkspaceMembershipResponse(ContractModel):
    workspace_id: UUID
    user_id: UUID
    workspace_name: NonEmptyString
    role: WorkspaceRole
    status: MembershipStatus
    data_authenticity: DataAuthenticity


class ProjectCreateRequest(ContractModel):
    name: NonEmptyString


class ProjectUpdateRequest(ContractModel):
    name: NonEmptyString | None = None
    status: ProjectStatus | None = None
    expected_row_version: int = Field(ge=1)


class ProjectResponse(MutableResource):
    name: NonEmptyString
    status: ProjectStatus
    data_authenticity: DataAuthenticity


class WatchlistQueryRules(ContractModel):
    include_terms: list[NonEmptyString] = Field(default_factory=list)
    exclude_terms: list[NonEmptyString] = Field(default_factory=list)
    languages: list[NonEmptyString] = Field(default_factory=list)
    regions: list[NonEmptyString] = Field(default_factory=list)


class WatchlistRuleSet(ContractModel):
    schema_version: VersionString = "watchlist-rules-v1"
    entities: list[NonEmptyString] = Field(min_length=1)
    topics: list[NonEmptyString] = Field(default_factory=list)
    query_rules: WatchlistQueryRules
    cadence: WatchlistCadence
    current_window_days: int = Field(ge=1, le=365)
    baseline_window_days: int = Field(ge=1, le=730)
    notification_intent: bool = False


class WatchlistCreateRequest(ContractModel):
    project_id: UUID
    name: NonEmptyString
    objective: NonEmptyString
    source_connection_ids: list[UUID] = Field(min_length=1)
    rules: WatchlistRuleSet


class WatchlistUpdateRequest(ContractModel):
    name: NonEmptyString | None = None
    objective: NonEmptyString | None = None
    source_connection_ids: list[UUID] | None = None
    rules: WatchlistRuleSet | None = None
    expected_row_version: int = Field(ge=1)


class InitialBaselineProjection(ContractModel):
    status: InitialBaselineStatus
    current_count: int = Field(ge=0)
    required_count: int = Field(ge=1)
    candidate_count: int = Field(ge=0)
    expected_detectable_at: AwareDatetime | None = None
    reason: NonEmptyString | None = None
    last_terminal_run_at: AwareDatetime | None = None


class WatchlistResponse(MutableResource):
    project_id: UUID
    name: NonEmptyString
    objective: NonEmptyString
    status: WatchlistStatus
    rules_version: int = Field(ge=1)
    owner_id: UUID
    source_connection_ids: list[UUID]
    rules: WatchlistRuleSet
    initial_baseline: InitialBaselineProjection
    data_authenticity: DataAuthenticity


class WatchlistStateCommand(ContractModel):
    expected_row_version: int = Field(ge=1)
    reason: NonEmptyString


class NavigationSummary(ContractModel):
    workspace_id: UUID
    unreviewed_signal_count: int = Field(ge=0)
    investigation_needs_input_count: int = Field(ge=0)
    draft_decision_brief_count: int = Field(ge=0)
    monitoring_health: NonEmptyString
    computed_at: AwareDatetime
    data_authenticity: DataAuthenticity
