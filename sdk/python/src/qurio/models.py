"""Stable public models selected from Qurio's checked OpenAPI contract."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QurioModel(BaseModel):
    """Forward-compatible SDK model with typed authoritative fields."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class QurioDataset(QurioModel):
    dataset_id: str
    workspace_id: UUID
    name: str
    symbol: str
    interval: Literal["1h", "4h", "1D"]
    covered_start: datetime
    covered_end: datetime
    bar_count: int = Field(ge=1)
    research_eligible: bool
    data_authenticity: str


class QurioRun(QurioModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    dataset_id: str
    dataset_digest: str
    research_start: date
    research_end: date
    state: str
    mode: Literal["plan", "auto"]
    question: str
    attempt_number: int = Field(ge=1)
    provider: str
    model: str | None = None
    data_authenticity: str
    created_at: datetime
    updated_at: datetime


class QurioArtifact(QurioModel):
    id: UUID
    workspace_id: UUID
    run_id: UUID
    ordinal: int = Field(ge=1)
    kind: str
    title: str
    digest: str
    review_status: str
    created_at: datetime
    data_authenticity: str


class StrategyExportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_type: Literal[
        "strategy_report_markdown", "strategy_evidence_bundle_json"
    ]
    run_id: UUID
    candidate_id: UUID


class StrategyExportPreviewResponse(QurioModel):
    export_type: Literal[
        "strategy_report_markdown", "strategy_evidence_bundle_json"
    ]
    run_id: UUID
    candidate_id: UUID
    data_authenticity: str
    filename: str
    media_type: Literal["text/markdown", "application/json"]
    rendered_content: str
    content_digest: str


JsonObject = dict[str, Any]
