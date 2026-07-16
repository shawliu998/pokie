"""Singly grounded Decision Brief, readiness, freshness, and export contracts."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, ConfigDict, Field, model_validator

from ..base import ContractModel, Digest, NonEmptyString, VersionString
from ..enums import (
    BriefExportDestination,
    BriefExportType,
    DataAuthenticity,
    DecisionBriefFreshnessStatus,
    DecisionBriefReadinessDecision,
    DecisionBriefReadinessProjection,
    DecisionBriefStatus,
    GenerationMethod,
    RecommendationStatus,
)
from .common import ImmutableResource, MutableResource


class FactBlock(ContractModel):
    id: NonEmptyString
    type: Literal["fact"] = "fact"
    body: NonEmptyString
    claim_version_ids: list[UUID] = Field(min_length=1)
    evidence_ids: list[UUID] = Field(min_length=1)
    content_version_ids: list[UUID] = Field(min_length=1)


class SynthesisBlock(ContractModel):
    id: NonEmptyString
    type: Literal["synthesis"] = "synthesis"
    body: NonEmptyString
    synthesis_version_id: UUID
    generation_method: GenerationMethod
    generator_version: VersionString
    model_prompt_refs: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_generation_provenance(self) -> SynthesisBlock:
        if self.generation_method == GenerationMethod.DETERMINISTIC and self.model_prompt_refs:
            raise ValueError("deterministic synthesis cannot have model prompt references")
        if self.generation_method == GenerationMethod.MODEL and not self.model_prompt_refs:
            raise ValueError("model synthesis requires pinned model prompt references")
        return self


class PMJudgmentBlock(ContractModel):
    id: NonEmptyString
    type: Literal["pm_judgment"] = "pm_judgment"
    body: NonEmptyString
    actor_id: UUID


class RecommendationBlock(ContractModel):
    id: NonEmptyString
    type: Literal["recommendation"] = "recommendation"
    body: NonEmptyString
    recommendation_status: RecommendationStatus


class NoCounterEvidenceSearchRecord(ContractModel):
    """Auditable scope used when a review found no counter-evidence.

    The record deliberately says *where the PM looked*, not that counter-evidence
    does not exist.  It is rendered as a limitation in every canonical export.
    """

    queries: list[NonEmptyString] = Field(min_length=1)
    source_connection_ids: list[UUID] = Field(min_length=1)
    window_start: AwareDatetime
    window_end: AwareDatetime
    exclusion_criteria: list[NonEmptyString] = Field(min_length=1)
    limitations: list[NonEmptyString] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_search_scope(self) -> NoCounterEvidenceSearchRecord:
        if self.window_end <= self.window_start:
            raise ValueError("counter-evidence search window_end must be after window_start")
        if len(self.source_connection_ids) != len(set(self.source_connection_ids)):
            raise ValueError("counter-evidence source IDs must be unique")
        return self


DecisionBriefBlock = Annotated[
    FactBlock | SynthesisBlock | PMJudgmentBlock | RecommendationBlock,
    Field(discriminator="type"),
]


class DecisionBriefBlockDocument(ContractModel):
    schema_version: VersionString
    blocks: list[DecisionBriefBlock] = Field(min_length=1)
    no_counter_evidence_search: NoCounterEvidenceSearchRecord | None = None

    @model_validator(mode="after")
    def unique_block_ids(self) -> DecisionBriefBlockDocument:
        ids = [block.id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("block IDs must be unique")
        return self


class DecisionBriefReferenceSnapshot(ContractModel):
    synthesis_version_id: UUID
    synthesis_review_id: UUID
    claim_version_ids: list[UUID]
    claim_review_ids: list[UUID]
    claim_evidence_ids: list[UUID]
    evidence_review_ids: list[UUID]
    evidence_ids: list[UUID]
    content_version_ids: list[UUID]


class DecisionBriefCreateRequest(ContractModel):
    synthesis_version_id: UUID
    template_version: VersionString


class DecisionBriefVersionUpdateRequest(ContractModel):
    block_document: DecisionBriefBlockDocument
    expected_row_version: int = Field(ge=1)
    human_edit_digest: Digest


class DecisionBriefVersionResponse(ContractModel):
    id: UUID
    decision_brief_id: UUID
    investigation_id: UUID
    version_number: int = Field(ge=1)
    synthesis_version_id: UUID
    synthesis_review_id: UUID
    block_document: DecisionBriefBlockDocument
    reference_snapshot_json: DecisionBriefReferenceSnapshot
    template_version: VersionString
    human_edit_digest: Digest
    readiness: DecisionBriefReadinessProjection
    freshness: DecisionBriefFreshnessStatus
    created_by: UUID
    created_at: AwareDatetime
    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_single_grounding(self) -> DecisionBriefVersionResponse:
        if self.reference_snapshot_json.synthesis_version_id != self.synthesis_version_id:
            raise ValueError("reference snapshot must use the grounding synthesis version")
        if self.reference_snapshot_json.synthesis_review_id != self.synthesis_review_id:
            raise ValueError("reference snapshot must use the grounding synthesis review")
        return self


class DecisionBriefResponse(MutableResource):
    investigation_id: UUID
    current_version: DecisionBriefVersionResponse
    status: DecisionBriefStatus
    owner_id: UUID
    decision_outcome: str | None = None
    next_checkpoint_at: AwareDatetime | None = None
    data_authenticity: DataAuthenticity


class DecisionBriefRevisionRequest(ContractModel):
    base_decision_brief_version_id: UUID
    synthesis_version_id: UUID
    expected_row_version: int = Field(ge=1)


class DecisionBriefReadinessRequest(ContractModel):
    decision_brief_version_id: UUID
    expected_row_version: int = Field(ge=1)
    decision: DecisionBriefReadinessDecision = DecisionBriefReadinessDecision.MARK_DECISION_READY
    reason: NonEmptyString
    policy_version: VersionString
    checklist_digest: Digest


class DecisionBriefReadinessReviewResponse(ContractModel):
    id: UUID
    decision_brief_version_id: UUID
    decision: DecisionBriefReadinessDecision
    reviewer_id: UUID
    reason: NonEmptyString
    policy_version: VersionString
    checklist_digest: Digest
    reviewed_at: AwareDatetime
    data_authenticity: DataAuthenticity


class DecisionBriefFreshnessRecordResponse(ContractModel):
    id: UUID
    decision_brief_version_id: UUID
    status: DecisionBriefFreshnessStatus
    affected_reference_snapshot_json: list[UUID]
    reason: NonEmptyString
    policy_version: VersionString
    assessed_at: AwareDatetime
    data_authenticity: DataAuthenticity


class DecisionBriefFreshnessRecheckRequest(ContractModel):
    reason: NonEmptyString


class BriefExportSelectionManifest(ContractModel):
    block_ids: list[NonEmptyString] = Field(min_length=1)
    include_citations: bool

    @model_validator(mode="after")
    def unique_blocks(self) -> BriefExportSelectionManifest:
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("selected block IDs must be unique")
        return self


class BriefExportPreviewRequest(ContractModel):
    decision_brief_version_id: UUID
    export_type: BriefExportType
    selection_manifest: BriefExportSelectionManifest


class BriefExportPreviewResponse(ContractModel):
    model_config = ConfigDict(str_strip_whitespace=False)

    decision_brief_version_id: UUID
    export_type: BriefExportType
    rendered_content: str
    reference_digest: Digest
    export_timestamp: AwareDatetime
    data_authenticity: DataAuthenticity


class BriefExportCreateRequest(BriefExportPreviewRequest):
    destination: BriefExportDestination
    reference_digest: Digest
    export_timestamp: AwareDatetime


class BriefExportResponse(ImmutableResource):
    decision_brief_version_id: UUID
    export_type: BriefExportType
    destination: BriefExportDestination
    selection_manifest_json: BriefExportSelectionManifest
    reference_digest: Digest
    policy_version: VersionString
    template_version: VersionString
    output_digest: Digest
    created_by: UUID
    created_at: AwareDatetime
    data_authenticity: DataAuthenticity
