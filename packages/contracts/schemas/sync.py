from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, Field

from ..base import ContractModel
from ..enums import DataAuthenticity
from .decisions import DecisionBriefResponse
from .research import InvestigationResponse
from .signals import SignalResponse
from .sources import SourceConnectionResponse
from .workspaces import ProjectResponse, WatchlistResponse, WorkspaceResponse


class SyncBootstrapResponse(ContractModel):
    workspace_id: UUID
    workspace: WorkspaceResponse
    projects: list[ProjectResponse]
    watchlists: list[WatchlistResponse]
    sources: list[SourceConnectionResponse]
    signals: list[SignalResponse]
    investigations: list[InvestigationResponse]
    decision_briefs: list[DecisionBriefResponse]
    cursors: dict[str, str | None] = Field(default_factory=dict)
    computed_at: AwareDatetime
    data_authenticity: DataAuthenticity
