"""Immutable Evidence/Claim/Synthesis and append-only review contracts."""

from __future__ import annotations

from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from ..base import ContractModel, Digest, JsonObject, NonEmptyString, VersionString
from ..enums import (
    CalibrationStatus,
    ClaimConfidenceLevel,
    ClaimReviewDecision,
    ClaimReviewProjection,
    ClaimType,
    DataAuthenticity,
    EvidenceReviewDecision,
    EvidenceReviewProjection,
    EvidenceStance,
    GenerationMethod,
    SuggestionOrigin,
    SynthesisReviewDecision,
    SynthesisReviewProjection,
)
from .common import ImmutableResource, MutableResource


class EvidenceProvenance(ContractModel):
    research_run_id: UUID
    extraction_method: NonEmptyString


class EvidenceReviewSummary(ContractModel):
    id: UUID
    decision: EvidenceReviewDecision
    policy_version: VersionString
    reviewed_at: AwareDatetime


class EvidenceResponse(ImmutableResource):
    investigation_id: UUID
    research_run_id: UUID
    content_version_id: UUID
    quote_start: int = Field(ge=0)
    quote_end: int = Field(gt=0)
    quote_text: NonEmptyString
    quote_text_digest: Digest
    stance: EvidenceStance
    status: EvidenceReviewProjection
    latest_review: EvidenceReviewSummary | None = None
    relevance: float = Field(ge=0, le=1)
    reliability: float = Field(ge=0, le=1)
    independence: float = Field(ge=0, le=1)
    recency: float = Field(ge=0, le=1)
    specificity: float = Field(ge=0, le=1)
    provenance: EvidenceProvenance
    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_quote_range(self) -> EvidenceResponse:
        if self.quote_end <= self.quote_start:
            raise ValueError("quote_end must be greater than quote_start")
        return self


class EvidenceReviewRequest(ContractModel):
    decision: EvidenceReviewDecision
    reason: NonEmptyString
    policy_version: VersionString


class EvidenceReviewResponse(ContractModel):
    id: UUID
    evidence_id: UUID
    decision: EvidenceReviewDecision
    reviewer_id: UUID
    reason: NonEmptyString
    policy_version: VersionString
    reviewed_at: AwareDatetime
    data_authenticity: DataAuthenticity


class ClaimEvidenceLink(ContractModel):
    id: UUID | None = None
    evidence_id: UUID
    stance: EvidenceStance
    weight: float = Field(ge=0, le=1)
    rationale: str | None = None


class ClaimVersionResponse(ContractModel):
    id: UUID
    claim_id: UUID
    version_number: int = Field(ge=1)
    claim_type: ClaimType
    text: NonEmptyString
    confidence_inputs_json: JsonObject
    confidence_score: float = Field(ge=0, le=1)
    confidence_level: ClaimConfidenceLevel
    confidence_policy_version: VersionString
    confidence_input_digest: Digest
    calibration_status: CalibrationStatus
    limitations: list[NonEmptyString]
    generation_method: GenerationMethod
    generator_version: VersionString
    suggestion_origin: SuggestionOrigin
    status: ClaimReviewProjection
    created_by: UUID
    created_at: AwareDatetime
    data_authenticity: DataAuthenticity


class ClaimResponse(MutableResource):
    investigation_id: UUID
    research_run_id: UUID
    current_version: ClaimVersionResponse
    evidence_links: list[ClaimEvidenceLink]
    owner_id: UUID
    data_authenticity: DataAuthenticity


class ClaimVersionCreateRequest(ContractModel):
    claim_type: ClaimType
    text: NonEmptyString
    limitations: list[NonEmptyString]
    evidence_links: list[ClaimEvidenceLink] = Field(min_length=1)
    expected_claim_row_version: int = Field(ge=1)


class ClaimReviewRequest(ContractModel):
    claim_version_id: UUID
    expected_claim_row_version: int = Field(ge=1)
    decision: ClaimReviewDecision
    evidence_review_ids: list[UUID] = Field(default_factory=list)
    expected_claim_evidence_snapshot_digest: Digest | None = None
    reason: NonEmptyString

    @model_validator(mode="after")
    def validate_verify_snapshot(self) -> ClaimReviewRequest:
        if self.decision == ClaimReviewDecision.VERIFY and (
            not self.evidence_review_ids or self.expected_claim_evidence_snapshot_digest is None
        ):
            raise ValueError("verify requires evidence review IDs and a snapshot digest")
        return self


class ClaimBatchReviewRequest(ContractModel):
    expected_run_row_version: int = Field(ge=1)
    decisions: list[ClaimReviewRequest] = Field(min_length=1)


class ClaimReviewResponse(ContractModel):
    id: UUID
    claim_version_id: UUID
    decision: ClaimReviewDecision
    claim_evidence_snapshot_json: list[UUID]
    evidence_review_snapshot_json: list[UUID]
    snapshot_digest: Digest
    reviewer_id: UUID
    reason: NonEmptyString
    policy_version: VersionString
    reviewed_at: AwareDatetime
    data_authenticity: DataAuthenticity


class SynthesisCreateRequest(ContractModel):
    verified_claim_version_ids: list[UUID] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_claim_versions(self) -> SynthesisCreateRequest:
        if len(self.verified_claim_version_ids) != len(set(self.verified_claim_version_ids)):
            raise ValueError("verified_claim_version_ids must be unique")
        return self


class SynthesisUpdateRequest(ContractModel):
    executive_summary: NonEmptyString
    business_implications: list[NonEmptyString]
    limitations: list[NonEmptyString]
    expected_row_version: int = Field(ge=1)
    change_reason: NonEmptyString


class InvestigationSynthesisVersionResponse(ContractModel):
    id: UUID
    synthesis_id: UUID
    investigation_id: UUID
    version_number: int = Field(ge=1)
    verified_claim_version_snapshot_json: list[UUID] = Field(min_length=1)
    claim_review_snapshot_json: list[UUID] = Field(min_length=1)
    generation_method: GenerationMethod
    generator_version: VersionString
    model_prompt_refs_json: list[NonEmptyString] = Field(default_factory=list)
    executive_summary: NonEmptyString
    business_implications: list[NonEmptyString]
    limitations: list[NonEmptyString]
    provenance_digest: Digest
    status: SynthesisReviewProjection
    created_by: UUID
    created_at: AwareDatetime
    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_generation_provenance(self) -> InvestigationSynthesisVersionResponse:
        if self.generation_method == GenerationMethod.DETERMINISTIC and self.model_prompt_refs_json:
            raise ValueError("deterministic synthesis cannot have model prompt references")
        if self.generation_method == GenerationMethod.MODEL and not self.model_prompt_refs_json:
            raise ValueError("model synthesis requires pinned model prompt references")
        return self


class InvestigationSynthesisResponse(MutableResource):
    investigation_id: UUID
    current_version: InvestigationSynthesisVersionResponse
    data_authenticity: DataAuthenticity


class SynthesisReviewRequest(ContractModel):
    synthesis_version_id: UUID
    expected_row_version: int = Field(ge=1)
    decision: SynthesisReviewDecision
    reason: NonEmptyString
    policy_version: VersionString


class SynthesisReviewResponse(ContractModel):
    id: UUID
    synthesis_version_id: UUID
    decision: SynthesisReviewDecision
    reviewer_id: UUID
    reason: NonEmptyString
    policy_version: VersionString
    reviewed_at: AwareDatetime
    data_authenticity: DataAuthenticity
