"""Decision Brief grounding, readiness and terminal export invariants."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .canonical import canonical_digest, require_sha256_digest
from .errors import DigestMismatch, InvariantViolation


class BriefBlockType(StrEnum):
    FACT = "fact"
    SYNTHESIS = "synthesis"
    PM_JUDGMENT = "pm_judgment"
    RECOMMENDATION = "recommendation"


class GenerationMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL = "model"
    HUMAN = "human"


class RecommendationStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class BriefReadiness(StrEnum):
    DRAFT = "draft"
    DECISION_READY = "decision_ready"


class BriefFreshness(StrEnum):
    CURRENT = "current"
    EVIDENCE_STALE = "evidence_stale"


class ExportType(StrEnum):
    PRD_RESEARCH_INPUT_MARKDOWN = "prd_research_input_markdown"


class ExportDestination(StrEnum):
    LOCAL_DOWNLOAD = "local_download"
    COPY_MARKDOWN = "copy_markdown"


class ReviewDecision(StrEnum):
    VERIFY = "verify"
    REJECT = "reject"


def _ids(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise InvariantViolation(f"{field} must be a list of IDs.")
    result = tuple(str(item) for item in value)
    if any(not item for item in result):
        raise InvariantViolation(f"{field} cannot contain an empty ID.")
    if len(result) != len(set(result)):
        raise InvariantViolation(f"{field} cannot contain duplicate IDs.")
    return result


@dataclass(frozen=True, slots=True)
class SynthesisGrounding:
    investigation_id: str
    synthesis_version_id: str
    synthesis_investigation_id: str
    synthesis_review_id: str
    reviewed_synthesis_version_id: str
    review_decision: ReviewDecision

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "review_decision", ReviewDecision(self.review_decision))
        except ValueError as exc:
            raise InvariantViolation("Synthesis review has an unknown decision.") from exc


def assert_single_verified_synthesis(
    *,
    decision_investigation_id: str,
    candidates: Iterable[SynthesisGrounding],
) -> SynthesisGrounding:
    groundings = list(candidates)
    if len(groundings) != 1:
        raise InvariantViolation(
            "A DecisionBriefVersion must be grounded by exactly one synthesis version."
        )
    grounding = groundings[0]
    if not all(
        (
            decision_investigation_id,
            grounding.investigation_id,
            grounding.synthesis_version_id,
            grounding.synthesis_investigation_id,
            grounding.reviewed_synthesis_version_id,
        )
    ):
        raise InvariantViolation("Synthesis grounding identifiers cannot be empty.")
    if (
        grounding.investigation_id != decision_investigation_id
        or grounding.synthesis_investigation_id != decision_investigation_id
    ):
        raise InvariantViolation(
            "Decision Brief and synthesis must belong to the same Investigation."
        )
    if grounding.reviewed_synthesis_version_id != grounding.synthesis_version_id:
        raise InvariantViolation("SynthesisReview must pin the exact synthesis version.")
    if grounding.review_decision is not ReviewDecision.VERIFY:
        raise InvariantViolation("Decision Brief grounding requires a verified synthesis.")
    if not grounding.synthesis_review_id:
        raise InvariantViolation("Verified synthesis grounding requires its review ID.")
    return grounding


@dataclass(frozen=True, slots=True)
class FrozenReferenceSnapshot:
    synthesis_version_id: str
    synthesis_review_id: str
    claim_version_ids: tuple[str, ...]
    claim_review_ids: tuple[str, ...]
    claim_evidence_ids: tuple[str, ...]
    evidence_review_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    content_version_ids: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> FrozenReferenceSnapshot:
        allowed = {
            "synthesis_version_id",
            "synthesis_review_id",
            "claim_version_ids",
            "claim_review_ids",
            "claim_evidence_ids",
            "evidence_review_ids",
            "evidence_ids",
            "content_version_ids",
        }
        if set(value) - allowed:
            raise InvariantViolation("Reference snapshot contains unknown fields.")
        return cls(
            synthesis_version_id=str(value.get("synthesis_version_id", "")),
            synthesis_review_id=str(value.get("synthesis_review_id", "")),
            claim_version_ids=_ids(value.get("claim_version_ids"), "claim_version_ids"),
            claim_review_ids=_ids(value.get("claim_review_ids"), "claim_review_ids"),
            claim_evidence_ids=_ids(value.get("claim_evidence_ids"), "claim_evidence_ids"),
            evidence_review_ids=_ids(value.get("evidence_review_ids"), "evidence_review_ids"),
            evidence_ids=_ids(value.get("evidence_ids"), "evidence_ids"),
            content_version_ids=_ids(value.get("content_version_ids"), "content_version_ids"),
        )

    def __post_init__(self) -> None:
        if not self.synthesis_version_id or not self.synthesis_review_id:
            raise InvariantViolation(
                "Reference snapshot requires exact synthesis version and review IDs."
            )
        for field in (
            "claim_version_ids",
            "claim_review_ids",
            "claim_evidence_ids",
            "evidence_review_ids",
            "evidence_ids",
            "content_version_ids",
        ):
            _ids(getattr(self, field), field)

    def as_dict(self) -> dict[str, Any]:
        return {
            "synthesis_version_id": self.synthesis_version_id,
            "synthesis_review_id": self.synthesis_review_id,
            "claim_version_ids": list(self.claim_version_ids),
            "claim_review_ids": list(self.claim_review_ids),
            "claim_evidence_ids": list(self.claim_evidence_ids),
            "evidence_review_ids": list(self.evidence_review_ids),
            "evidence_ids": list(self.evidence_ids),
            "content_version_ids": list(self.content_version_ids),
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.as_dict())


@dataclass(frozen=True, slots=True)
class BriefBlock:
    id: str
    type: BriefBlockType
    body: str
    claim_version_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    content_version_ids: tuple[str, ...] = ()
    synthesis_version_id: str | None = None
    generation_method: GenerationMethod | None = None
    generator_version: str | None = None
    model_prompt_refs: tuple[str, ...] = ()
    actor_id: str | None = None
    recommendation_status: RecommendationStatus | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> BriefBlock:
        allowed = {
            "id",
            "type",
            "body",
            "claim_version_ids",
            "evidence_ids",
            "content_version_ids",
            "synthesis_version_id",
            "generation_method",
            "generator_version",
            "model_prompt_refs",
            "actor_id",
            "recommendation_status",
        }
        if set(value) - allowed:
            raise InvariantViolation("Decision Brief block contains unknown fields.")
        try:
            block_type = BriefBlockType(value.get("type"))
        except (TypeError, ValueError) as exc:
            raise InvariantViolation("Decision Brief block has an unknown type.") from exc
        generation_value = value.get("generation_method")
        generation = None
        if generation_value is not None:
            try:
                generation = GenerationMethod(generation_value)
            except ValueError as exc:
                raise InvariantViolation("Synthesis block has an unknown origin.") from exc
        recommendation_value = value.get("recommendation_status")
        recommendation = None
        if recommendation_value is not None:
            try:
                recommendation = RecommendationStatus(recommendation_value)
            except ValueError as exc:
                raise InvariantViolation("Recommendation has an unknown status.") from exc
        return cls(
            id=str(value.get("id", "")),
            type=block_type,
            body=str(value.get("body", "")),
            claim_version_ids=_ids(value.get("claim_version_ids"), "claim_version_ids"),
            evidence_ids=_ids(value.get("evidence_ids"), "evidence_ids"),
            content_version_ids=_ids(value.get("content_version_ids"), "content_version_ids"),
            synthesis_version_id=(
                str(value["synthesis_version_id"])
                if value.get("synthesis_version_id") is not None
                else None
            ),
            generation_method=generation,
            generator_version=(
                str(value["generator_version"])
                if value.get("generator_version") is not None
                else None
            ),
            model_prompt_refs=_ids(value.get("model_prompt_refs"), "model_prompt_refs"),
            actor_id=str(value["actor_id"]) if value.get("actor_id") is not None else None,
            recommendation_status=recommendation,
        )


def _subset(actual: tuple[str, ...], allowed: tuple[str, ...], field: str) -> None:
    foreign = set(actual) - set(allowed)
    if foreign:
        raise InvariantViolation(
            f"{field} must be a subset of the frozen synthesis provenance.",
            details={"field": field},
        )


def validate_brief_document(
    block_document: Mapping[str, Any],
    *,
    reference_snapshot: FrozenReferenceSnapshot,
    expected_schema_version: str = "decision-brief-blocks-v1",
) -> tuple[BriefBlock, ...]:
    if set(block_document) - {"schema_version", "blocks"}:
        raise InvariantViolation("Decision Brief document contains unknown fields.")
    if block_document.get("schema_version") != expected_schema_version:
        raise InvariantViolation("Decision Brief block schema version is not supported.")
    raw_blocks = block_document.get("blocks")
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise InvariantViolation("Decision Brief must contain at least one typed block.")
    if any(not isinstance(item, Mapping) for item in raw_blocks):
        raise InvariantViolation("Each Decision Brief block must be an object.")
    blocks = tuple(BriefBlock.from_mapping(item) for item in raw_blocks)
    ids = [block.id for block in blocks]
    if any(not block_id for block_id in ids) or len(ids) != len(set(ids)):
        raise InvariantViolation("Decision Brief block IDs must be non-empty and unique.")

    for block in blocks:
        if not block.body.strip():
            raise InvariantViolation(f"Decision Brief block {block.id!r} has an empty body.")
        if block.type is BriefBlockType.FACT:
            if not (block.claim_version_ids and block.evidence_ids and block.content_version_ids):
                raise InvariantViolation(
                    "Fact blocks require ClaimVersion, Evidence and ContentVersion references."
                )
            _subset(
                block.claim_version_ids,
                reference_snapshot.claim_version_ids,
                "claim_version_ids",
            )
            _subset(block.evidence_ids, reference_snapshot.evidence_ids, "evidence_ids")
            _subset(
                block.content_version_ids,
                reference_snapshot.content_version_ids,
                "content_version_ids",
            )
            if any(
                (
                    block.synthesis_version_id,
                    block.generation_method,
                    block.generator_version,
                    block.model_prompt_refs,
                    block.actor_id,
                    block.recommendation_status,
                )
            ):
                raise InvariantViolation("Fact block contains fields owned by another type.")
        elif block.type is BriefBlockType.SYNTHESIS:
            if block.synthesis_version_id != reference_snapshot.synthesis_version_id:
                raise InvariantViolation(
                    "Synthesis block must reference the Brief's exact grounding version."
                )
            if block.generation_method is None or not block.generator_version:
                raise InvariantViolation(
                    "Synthesis block must preserve generation method and version."
                )
            if (
                block.generation_method is GenerationMethod.DETERMINISTIC
                and block.model_prompt_refs
            ):
                raise InvariantViolation(
                    "Deterministic synthesis cannot carry model/prompt references."
                )
            if block.generation_method is GenerationMethod.MODEL and not block.model_prompt_refs:
                raise InvariantViolation("Model synthesis must pin model/prompt references.")
            if any(
                (
                    block.claim_version_ids,
                    block.evidence_ids,
                    block.content_version_ids,
                    block.actor_id,
                    block.recommendation_status,
                )
            ):
                raise InvariantViolation(
                    "Synthesis block contains fields owned by another block type."
                )
        elif block.type is BriefBlockType.PM_JUDGMENT:
            if not block.actor_id:
                raise InvariantViolation("PM Judgment must pin its human actor.")
            if any(
                (
                    block.claim_version_ids,
                    block.evidence_ids,
                    block.content_version_ids,
                    block.synthesis_version_id,
                    block.generation_method,
                    block.generator_version,
                    block.model_prompt_refs,
                    block.recommendation_status,
                )
            ):
                raise InvariantViolation("PM Judgment contains fields owned by another block type.")
        elif block.type is BriefBlockType.RECOMMENDATION:
            if block.recommendation_status is None:
                raise InvariantViolation("Recommendation must have an explicit status.")
            if any(
                (
                    block.claim_version_ids,
                    block.evidence_ids,
                    block.content_version_ids,
                    block.synthesis_version_id,
                    block.generation_method,
                    block.generator_version,
                    block.model_prompt_refs,
                    block.actor_id,
                )
            ):
                raise InvariantViolation(
                    "Recommendation contains fields owned by another block type."
                )
    return blocks


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    decision: BriefReadiness
    checklist_digest: str
    checklist: tuple[tuple[str, bool], ...]


def validate_brief_readiness(
    block_document: Mapping[str, Any],
    *,
    reference_snapshot: FrozenReferenceSnapshot,
    synthesis_verified: bool,
    exact_review_snapshots_complete: bool,
    limitations: Sequence[object],
    counter_evidence_handled: bool,
) -> ReadinessResult:
    if isinstance(limitations, str | bytes) or any(
        not isinstance(item, str) for item in limitations
    ):
        raise InvariantViolation("Brief limitations must be a list of strings.")
    normalized_limitations = tuple(item for item in limitations if isinstance(item, str))
    blocks = validate_brief_document(block_document, reference_snapshot=reference_snapshot)
    block_types = {block.type for block in blocks}
    accepted_recommendation = any(
        block.type is BriefBlockType.RECOMMENDATION
        and block.recommendation_status is RecommendationStatus.ACCEPTED
        for block in blocks
    )
    resolved_recommendations = all(
        block.recommendation_status is not RecommendationStatus.PROPOSED
        for block in blocks
        if block.type is BriefBlockType.RECOMMENDATION
    )
    checks = (
        ("verified_synthesis", synthesis_verified),
        (
            "exact_review_snapshots",
            exact_review_snapshots_complete
            and bool(reference_snapshot.claim_review_ids)
            and bool(reference_snapshot.claim_evidence_ids)
            and bool(reference_snapshot.evidence_review_ids),
        ),
        ("fact_present", BriefBlockType.FACT in block_types),
        ("synthesis_present", BriefBlockType.SYNTHESIS in block_types),
        ("pm_judgment_present", BriefBlockType.PM_JUDGMENT in block_types),
        ("accepted_recommendation", accepted_recommendation),
        ("recommendations_resolved", resolved_recommendations),
        (
            "limitations_recorded",
            bool([item for item in normalized_limitations if item.strip()]),
        ),
        ("counter_evidence_handled", counter_evidence_handled),
    )
    failed = [name for name, passed in checks if not passed]
    if failed:
        raise InvariantViolation(
            "Decision Brief is not ready: " + ", ".join(failed) + ".",
            code="APPROVAL_REQUIRED",
            details={"failed_checks": failed},
        )
    checklist_digest = canonical_digest({name: passed for name, passed in checks})
    return ReadinessResult(BriefReadiness.DECISION_READY, checklist_digest, checks)


@dataclass(frozen=True, slots=True)
class ExportSelection:
    block_ids: tuple[str, ...]
    include_citations: bool
    selection_digest: str
    reference_digest: str


def validate_export_selection(
    block_document: Mapping[str, Any],
    *,
    reference_snapshot: FrozenReferenceSnapshot,
    selected_block_ids: Sequence[str],
    include_citations: bool,
    readiness: BriefReadiness,
    freshness: BriefFreshness,
    supplied_reference_digest: str,
) -> ExportSelection:
    if readiness is not BriefReadiness.DECISION_READY:
        raise InvariantViolation("Only a DecisionReady Brief version may be exported.")
    if freshness is not BriefFreshness.CURRENT:
        raise InvariantViolation("An evidence-stale Brief version cannot be exported.")
    require_sha256_digest(supplied_reference_digest, field="reference_digest")
    if supplied_reference_digest != reference_snapshot.digest:
        raise DigestMismatch(
            "reference_snapshot", reference_snapshot.digest, supplied_reference_digest
        )
    selection = _ids(selected_block_ids, "block_ids")
    if not selection:
        raise InvariantViolation("Export selection cannot be empty.")
    blocks = validate_brief_document(block_document, reference_snapshot=reference_snapshot)
    by_id = {block.id: block for block in blocks}
    missing = [block_id for block_id in selection if block_id not in by_id]
    if missing:
        raise InvariantViolation(
            "Export selection refers to unknown blocks.", details={"block_ids": missing}
        )
    chosen = [by_id[block_id] for block_id in selection]
    if any(block.type is BriefBlockType.SYNTHESIS for block in chosen):
        raise InvariantViolation("PRD Research Input must exclude Synthesis blocks.")
    if any(
        block.type is BriefBlockType.RECOMMENDATION
        and block.recommendation_status is not RecommendationStatus.ACCEPTED
        for block in chosen
    ):
        raise InvariantViolation("Export may include only accepted Recommendations.")
    if any(block.type is BriefBlockType.FACT for block in chosen) and not include_citations:
        raise InvariantViolation("Exported Fact blocks require citations.")

    manifest = {"block_ids": list(selection), "include_citations": include_citations}
    return ExportSelection(
        selection,
        include_citations,
        canonical_digest(manifest),
        supplied_reference_digest,
    )


@dataclass(frozen=True, slots=True)
class BriefExportRecord:
    id: str
    workspace_id: str
    decision_brief_version_id: str
    export_type: ExportType
    destination: ExportDestination
    selection_manifest: Mapping[str, Any]
    reference_digest: str
    policy_version: str
    template_version: str
    rendered_snapshot_uri: str
    output_digest: str
    created_by: str
    created_at: datetime

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "export_type", ExportType(self.export_type))
            object.__setattr__(self, "destination", ExportDestination(self.destination))
        except ValueError as exc:
            raise InvariantViolation("BriefExport contains an unknown enum value.") from exc
        for field in ("reference_digest", "output_digest"):
            require_sha256_digest(getattr(self, field), field=field)
        if not all(
            (
                self.id,
                self.workspace_id,
                self.decision_brief_version_id,
                self.policy_version,
                self.template_version,
                self.rendered_snapshot_uri,
                self.created_by,
            )
        ):
            raise InvariantViolation("Terminal BriefExport fields cannot be empty.")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise InvariantViolation("BriefExport created_at must be timezone-aware.")
        if set(self.selection_manifest) - {"block_ids", "include_citations"}:
            raise InvariantViolation("BriefExport selection contains unknown fields.")
        block_ids = _ids(self.selection_manifest.get("block_ids"), "block_ids")
        if not block_ids or not isinstance(self.selection_manifest.get("include_citations"), bool):
            raise InvariantViolation(
                "BriefExport selection manifest must pin blocks and citation choice."
            )
