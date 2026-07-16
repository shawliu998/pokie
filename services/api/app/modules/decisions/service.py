from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.api.app.core.errors import ApiError, invalid_state, not_found, version_conflict
from services.api.app.core.object_store import get_object_store
from services.api.app.db.models import (
    BriefExport,
    Claim,
    ClaimEvidence,
    ClaimReview,
    ClaimVersion,
    DecisionBrief,
    DecisionBriefFreshnessRecord,
    DecisionBriefReadinessReview,
    DecisionBriefVersion,
    Evidence,
    Investigation,
    InvestigationSynthesis,
    InvestigationSynthesisVersion,
    SynthesisReview,
    new_id,
)
from services.api.app.modules.common import audit, digest, lock_investigation_lineage
from services.api.app.modules.evidence.service import claim_version_status, latest_evidence_review


def _verified_claim_review(db: Session, version_id: str) -> ClaimReview | None:
    if claim_version_status(db, version_id) != "verified":
        return None
    return db.scalar(
        select(ClaimReview)
        .where(ClaimReview.claim_version_id == version_id, ClaimReview.decision == "verify")
        .order_by(ClaimReview.reviewed_at.desc())
    )


def _verified_synthesis_review(db: Session, version_id: str) -> SynthesisReview | None:
    version = db.get(InvestigationSynthesisVersion, version_id)
    synthesis = db.get(InvestigationSynthesis, version.synthesis_id) if version else None
    if version is None or synthesis is None or synthesis.current_version_id != version.id:
        return None
    if any(
        _verified_claim_review(db, claim_version_id) is None
        for claim_version_id in version.verified_claim_version_snapshot_json
    ):
        return None
    return db.scalar(
        select(SynthesisReview)
        .where(
            SynthesisReview.synthesis_version_id == version_id, SynthesisReview.decision == "verify"
        )
        .order_by(SynthesisReview.reviewed_at.desc())
    )


def synthesis_status(db: Session, version_id: str) -> str:
    review = db.scalar(
        select(SynthesisReview)
        .where(SynthesisReview.synthesis_version_id == version_id)
        .order_by(SynthesisReview.reviewed_at.desc())
    )
    if review is None:
        return "needs_review"
    if review.decision != "verify":
        return "rejected"
    return "verified" if _verified_synthesis_review(db, version_id) is not None else "needs_review"


def create_synthesis(
    db: Session,
    *,
    investigation: Investigation,
    actor_id: str,
    claim_version_ids: list[str],
    request_id: str,
) -> InvestigationSynthesis:
    investigation = lock_investigation_lineage(
        db,
        workspace_id=investigation.workspace_id,
        investigation_id=investigation.id,
    )
    versions = db.scalars(
        select(ClaimVersion)
        .join(Claim, Claim.id == ClaimVersion.claim_id)
        .where(
            ClaimVersion.id.in_(claim_version_ids),
            Claim.workspace_id == investigation.workspace_id,
            Claim.investigation_id == investigation.id,
        )
    ).all()
    if len(versions) != len(set(claim_version_ids)):
        raise ApiError(
            422, "VALIDATION_ERROR", "All synthesis claims must share the Investigation."
        )
    reviews = [_verified_claim_review(db, version.id) for version in versions]
    if any(review is None for review in reviews):
        raise ApiError(409, "APPROVAL_REQUIRED", "Every ClaimVersion must be verified.")
    synthesis = db.scalar(
        select(InvestigationSynthesis).where(
            InvestigationSynthesis.investigation_id == investigation.id,
            InvestigationSynthesis.workspace_id == investigation.workspace_id,
        )
    )
    if synthesis is None:
        synthesis = InvestigationSynthesis(
            workspace_id=investigation.workspace_id,
            investigation_id=investigation.id,
            data_authenticity=investigation.data_authenticity,
        )
        db.add(synthesis)
        db.flush()
        investigation.current_synthesis_id = synthesis.id
        investigation.row_version += 1
    next_version = (
        int(
            db.scalar(
                select(
                    func.coalesce(func.max(InvestigationSynthesisVersion.version_number), 0)
                ).where(InvestigationSynthesisVersion.synthesis_id == synthesis.id)
            )
            or 0
        )
        + 1
    )
    sorted_versions = sorted(versions, key=lambda item: item.id)
    review_rows = [review for review in reviews if review is not None]
    limitations = sorted(
        {limitation for version in sorted_versions for limitation in version.limitations}
    )
    provenance = {
        "claim_version_ids": [row.id for row in sorted_versions],
        "claim_reviews": [
            {"id": row.id, "snapshot_digest": row.snapshot_digest}
            for row in sorted(review_rows, key=lambda item: item.id)
        ],
    }
    previous_version_id = synthesis.current_version_id
    version = InvestigationSynthesisVersion(
        workspace_id=investigation.workspace_id,
        synthesis_id=synthesis.id,
        version_number=next_version,
        verified_claim_version_snapshot_json=[row.id for row in sorted_versions],
        claim_review_snapshot_json=[
            row.id for row in sorted(review_rows, key=lambda item: item.id)
        ],
        generation_method="deterministic",
        generator_version="deterministic-synthesis-v1",
        model_prompt_refs_json=[],
        executive_summary=" ".join(row.text for row in sorted_versions),
        business_implications=[row.text for row in sorted_versions],
        limitations=limitations or ["No limitations were supplied; readiness requires PM review."],
        provenance_digest=digest(provenance),
        created_by=actor_id,
        data_authenticity=investigation.data_authenticity,
    )
    db.add(version)
    db.flush()
    synthesis.current_version_id = version.id
    synthesis.row_version += 1
    if previous_version_id:
        _append_reference_staleness(
            db,
            workspace_id=investigation.workspace_id,
            reference_type="synthesis_version",
            reference_id=previous_version_id,
            reason="A newer synthesis version superseded this Brief grounding.",
        )
    audit(
        db,
        workspace_id=investigation.workspace_id,
        actor_id=actor_id,
        action="synthesis.version_created",
        target_type="InvestigationSynthesisVersion",
        target_id=version.id,
        request_id=request_id,
        after=provenance,
    )
    db.commit()
    return synthesis


def revise_synthesis(
    db: Session,
    *,
    synthesis: InvestigationSynthesis,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> InvestigationSynthesis:
    lock_investigation_lineage(
        db,
        workspace_id=synthesis.workspace_id,
        investigation_id=synthesis.investigation_id,
    )
    db.refresh(synthesis)
    if synthesis.row_version != payload["expected_row_version"]:
        raise version_conflict(synthesis.id, synthesis.row_version)
    current = db.get(InvestigationSynthesisVersion, synthesis.current_version_id)
    if current is None:
        raise ApiError(500, "LINEAGE_INTEGRITY_ERROR", "Synthesis current version is missing.")
    version = InvestigationSynthesisVersion(
        workspace_id=synthesis.workspace_id,
        synthesis_id=synthesis.id,
        version_number=current.version_number + 1,
        verified_claim_version_snapshot_json=current.verified_claim_version_snapshot_json,
        claim_review_snapshot_json=current.claim_review_snapshot_json,
        generation_method="deterministic",
        generator_version="human-edit-v1",
        model_prompt_refs_json=[],
        executive_summary=payload["executive_summary"],
        business_implications=payload["business_implications"],
        limitations=payload["limitations"],
        provenance_digest=digest(
            {
                "base_version_id": current.id,
                "claims": current.verified_claim_version_snapshot_json,
                "claim_reviews": current.claim_review_snapshot_json,
                "content": {
                    "executive_summary": payload["executive_summary"],
                    "business_implications": payload["business_implications"],
                    "limitations": payload["limitations"],
                },
            }
        ),
        created_by=actor_id,
        data_authenticity=synthesis.data_authenticity,
    )
    db.add(version)
    db.flush()
    synthesis.current_version_id = version.id
    synthesis.row_version += 1
    _append_reference_staleness(
        db,
        workspace_id=synthesis.workspace_id,
        reference_type="synthesis_version",
        reference_id=current.id,
        reason="A human synthesis revision superseded this Brief grounding.",
    )
    audit(
        db,
        workspace_id=synthesis.workspace_id,
        actor_id=actor_id,
        action="synthesis.version_revised",
        target_type="InvestigationSynthesisVersion",
        target_id=version.id,
        request_id=request_id,
        reason=payload["change_reason"],
    )
    db.commit()
    return synthesis


def review_synthesis(
    db: Session,
    *,
    synthesis: InvestigationSynthesis,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> SynthesisReview:
    lock_investigation_lineage(
        db,
        workspace_id=synthesis.workspace_id,
        investigation_id=synthesis.investigation_id,
    )
    db.refresh(synthesis)
    if synthesis.row_version != payload["expected_row_version"]:
        raise version_conflict(synthesis.id, synthesis.row_version)
    if payload["synthesis_version_id"] != synthesis.current_version_id:
        raise ApiError(
            412, "VERSION_CONFLICT", "Only the current synthesis version can be reviewed."
        )
    version = db.get(InvestigationSynthesisVersion, payload["synthesis_version_id"])
    if version is None:
        raise not_found("Synthesis version")
    existing = db.scalar(
        select(SynthesisReview).where(SynthesisReview.synthesis_version_id == version.id)
    )
    if existing:
        raise invalid_state("This synthesis version already has a review.")
    review = SynthesisReview(
        workspace_id=synthesis.workspace_id,
        synthesis_version_id=version.id,
        decision=payload["decision"],
        reviewer_id=actor_id,
        reason=payload["reason"],
        policy_version=payload["policy_version"],
        data_authenticity=synthesis.data_authenticity,
    )
    db.add(review)
    synthesis.row_version += 1
    audit(
        db,
        workspace_id=synthesis.workspace_id,
        actor_id=actor_id,
        action="synthesis.reviewed",
        target_type="InvestigationSynthesisVersion",
        target_id=version.id,
        request_id=request_id,
        after={"review_id": review.id, "decision": review.decision},
        reason=review.reason,
    )
    db.commit()
    return review


def _reference_snapshot(
    db: Session, synthesis_version: InvestigationSynthesisVersion
) -> dict[str, Any]:
    claim_version_ids = synthesis_version.verified_claim_version_snapshot_json
    reviews = db.scalars(
        select(ClaimReview).where(ClaimReview.id.in_(synthesis_version.claim_review_snapshot_json))
    ).all()
    claim_evidence_ids = sorted(
        {item for review in reviews for item in review.claim_evidence_snapshot_json}
    )
    evidence_review_ids = sorted(
        {item for review in reviews for item in review.evidence_review_snapshot_json}
    )
    links = db.scalars(select(ClaimEvidence).where(ClaimEvidence.id.in_(claim_evidence_ids))).all()
    evidence_ids = sorted({row.evidence_id for row in links})
    evidence = db.scalars(select(Evidence).where(Evidence.id.in_(evidence_ids))).all()
    content_version_ids = sorted({row.content_version_id for row in evidence})
    synthesis_review = _verified_synthesis_review(db, synthesis_version.id)
    if synthesis_review is None:
        raise ApiError(409, "APPROVAL_REQUIRED", "Decision Brief requires a verified synthesis.")
    return {
        "synthesis_version_id": synthesis_version.id,
        "synthesis_review_id": synthesis_review.id,
        "claim_version_ids": claim_version_ids,
        "claim_review_ids": synthesis_version.claim_review_snapshot_json,
        "claim_evidence_ids": claim_evidence_ids,
        "evidence_review_ids": evidence_review_ids,
        "evidence_ids": evidence_ids,
        "content_version_ids": content_version_ids,
    }


def _current_reference_issues(db: Session, version: DecisionBriefVersion) -> list[dict[str, Any]]:
    """Compare a Brief's frozen approval graph with current ledger projections."""

    snapshot = version.reference_snapshot_json
    issues: list[dict[str, Any]] = []
    synthesis_review = _verified_synthesis_review(db, version.synthesis_version_id)
    if synthesis_review is None or synthesis_review.id != version.synthesis_review_id:
        issues.append(
            {
                "reference_type": "synthesis_version",
                "reference_id": version.synthesis_version_id,
                "reason": "verified synthesis projection changed",
            }
        )
    expected_claim_review_ids = set(snapshot.get("claim_review_ids", []))
    for claim_version_id in snapshot.get("claim_version_ids", []):
        review = _verified_claim_review(db, claim_version_id)
        if review is None or review.id not in expected_claim_review_ids:
            issues.append(
                {
                    "reference_type": "claim_version",
                    "reference_id": claim_version_id,
                    "reason": "verified claim projection changed",
                }
            )
    expected_evidence_review_ids = set(snapshot.get("evidence_review_ids", []))
    for evidence_id in snapshot.get("evidence_ids", []):
        latest = latest_evidence_review(db, evidence_id)
        if (
            latest is None
            or latest.id not in expected_evidence_review_ids
            or latest.decision not in {"valid", "weak"}
        ):
            issues.append(
                {
                    "reference_type": "evidence",
                    "reference_id": evidence_id,
                    "latest_evidence_review_id": latest.id if latest else None,
                    "reason": "exact EvidenceReview snapshot changed",
                }
            )
    return issues


def _append_reference_staleness(
    db: Session,
    *,
    workspace_id: str,
    reference_type: str,
    reference_id: str,
    reason: str,
) -> list[str]:
    stale: list[str] = []
    for version in db.scalars(
        select(DecisionBriefVersion).where(DecisionBriefVersion.workspace_id == workspace_id)
    ).all():
        snapshot = version.reference_snapshot_json
        matched = (
            reference_type == "synthesis_version"
            and snapshot.get("synthesis_version_id") == reference_id
        ) or (
            reference_type == "claim_version"
            and reference_id in snapshot.get("claim_version_ids", [])
        )
        if not matched:
            continue
        db.add(
            DecisionBriefFreshnessRecord(
                workspace_id=workspace_id,
                decision_brief_version_id=version.id,
                status="evidence_stale",
                affected_reference_snapshot_json=[
                    {"reference_type": reference_type, "reference_id": reference_id}
                ],
                reason=reason,
                policy_version="brief-freshness-v1",
                data_authenticity=version.data_authenticity,
            )
        )
        stale.append(version.id)
    return stale


def _initial_blocks(
    db: Session,
    *,
    synthesis: InvestigationSynthesisVersion,
    snapshot: dict[str, Any],
    actor_id: str,
) -> dict[str, Any]:
    versions = db.scalars(
        select(ClaimVersion).where(ClaimVersion.id.in_(snapshot["claim_version_ids"]))
    ).all()
    links = db.scalars(
        select(ClaimEvidence).where(ClaimEvidence.id.in_(snapshot["claim_evidence_ids"]))
    ).all()
    evidence = {
        row.id: row
        for row in db.scalars(
            select(Evidence).where(Evidence.id.in_(snapshot["evidence_ids"]))
        ).all()
    }
    blocks: list[dict[str, Any]] = []
    for index, version in enumerate(sorted(versions, key=lambda item: item.id), start=1):
        version_links = [row for row in links if row.claim_version_id == version.id]
        evidence_ids = sorted(row.evidence_id for row in version_links)
        blocks.append(
            {
                "id": f"fact-{index}",
                "type": "fact",
                "body": version.text,
                "claim_version_ids": [version.id],
                "evidence_ids": evidence_ids,
                "content_version_ids": sorted(
                    evidence[row_id].content_version_id for row_id in evidence_ids
                ),
            }
        )
    blocks.extend(
        [
            {
                "id": "synthesis-1",
                "type": "synthesis",
                "body": synthesis.executive_summary,
                "synthesis_version_id": synthesis.id,
                "generation_method": synthesis.generation_method,
                "generator_version": synthesis.generator_version,
                "model_prompt_refs": synthesis.model_prompt_refs_json,
            },
            {
                "id": "judgment-1",
                "type": "pm_judgment",
                "body": "PM judgment pending",
                "actor_id": actor_id,
            },
            {
                "id": "recommendation-1",
                "type": "recommendation",
                "body": "Recommendation pending",
                "recommendation_status": "proposed",
            },
        ]
    )
    return {
        "schema_version": "decision-brief-blocks-v1",
        "blocks": blocks,
        "no_counter_evidence_search": None,
    }


def create_decision_brief(
    db: Session,
    *,
    investigation: Investigation,
    actor_id: str,
    synthesis_version_id: str,
    template_version: str,
    request_id: str,
) -> DecisionBrief:
    investigation = lock_investigation_lineage(
        db,
        workspace_id=investigation.workspace_id,
        investigation_id=investigation.id,
    )
    existing = db.scalar(
        select(DecisionBrief).where(
            DecisionBrief.investigation_id == investigation.id,
            DecisionBrief.workspace_id == investigation.workspace_id,
        )
    )
    if existing:
        return existing
    synthesis_version = db.scalar(
        select(InvestigationSynthesisVersion)
        .join(
            InvestigationSynthesis,
            InvestigationSynthesis.id == InvestigationSynthesisVersion.synthesis_id,
        )
        .where(
            InvestigationSynthesisVersion.id == synthesis_version_id,
            InvestigationSynthesis.investigation_id == investigation.id,
            InvestigationSynthesis.workspace_id == investigation.workspace_id,
        )
    )
    if synthesis_version is None:
        raise not_found("Verified synthesis version")
    snapshot = _reference_snapshot(db, synthesis_version)
    brief = DecisionBrief(
        workspace_id=investigation.workspace_id,
        investigation_id=investigation.id,
        status="draft",
        owner_id=actor_id,
        data_authenticity=investigation.data_authenticity,
    )
    db.add(brief)
    db.flush()
    blocks = _initial_blocks(db, synthesis=synthesis_version, snapshot=snapshot, actor_id=actor_id)
    version = DecisionBriefVersion(
        workspace_id=investigation.workspace_id,
        decision_brief_id=brief.id,
        version_number=1,
        synthesis_version_id=synthesis_version.id,
        synthesis_review_id=snapshot["synthesis_review_id"],
        block_document=blocks,
        reference_snapshot_json=snapshot,
        template_version=template_version,
        human_edit_digest=digest(blocks),
        created_by=actor_id,
        data_authenticity=investigation.data_authenticity,
    )
    db.add(version)
    db.flush()
    brief.current_version_id = version.id
    investigation.decision_brief_id = brief.id
    investigation.row_version += 1
    audit(
        db,
        workspace_id=brief.workspace_id,
        actor_id=actor_id,
        action="decision_brief.created",
        target_type="DecisionBrief",
        target_id=brief.id,
        request_id=request_id,
        after={"version_id": version.id, "synthesis_version_id": synthesis_version.id},
    )
    db.commit()
    return brief


def _lock_brief_for_command(db: Session, brief: DecisionBrief) -> DecisionBrief:
    locked = db.scalar(
        select(DecisionBrief)
        .where(
            DecisionBrief.id == brief.id,
            DecisionBrief.workspace_id == brief.workspace_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise not_found("Decision Brief")
    return locked


def revise_brief(
    db: Session,
    *,
    brief: DecisionBrief,
    actor_id: str,
    block_document: dict[str, Any],
    expected_row_version: int,
    human_edit_digest: str,
    request_id: str,
) -> DecisionBrief:
    if digest(block_document) != human_edit_digest:
        raise ApiError(
            422, "VALIDATION_ERROR", "human_edit_digest does not match the block document."
        )
    lock_investigation_lineage(
        db,
        workspace_id=brief.workspace_id,
        investigation_id=brief.investigation_id,
    )
    brief = _lock_brief_for_command(db, brief)
    if brief.row_version != expected_row_version:
        raise version_conflict(brief.id, brief.row_version)
    if brief.status != "draft":
        raise invalid_state("A DecisionReady Brief requires an explicit revision command.")
    current = db.get(DecisionBriefVersion, brief.current_version_id)
    if current is None:
        raise ApiError(500, "LINEAGE_INTEGRITY_ERROR", "Brief current version is missing.")
    _validate_block_references(
        db,
        block_document,
        current.reference_snapshot_json,
        actor_id=actor_id,
    )
    version = DecisionBriefVersion(
        workspace_id=brief.workspace_id,
        decision_brief_id=brief.id,
        version_number=current.version_number + 1,
        synthesis_version_id=current.synthesis_version_id,
        synthesis_review_id=current.synthesis_review_id,
        block_document=block_document,
        reference_snapshot_json=current.reference_snapshot_json,
        template_version=current.template_version,
        human_edit_digest=human_edit_digest,
        created_by=actor_id,
        data_authenticity=brief.data_authenticity,
    )
    db.add(version)
    db.flush()
    brief.current_version_id = version.id
    brief.row_version += 1
    audit(
        db,
        workspace_id=brief.workspace_id,
        actor_id=actor_id,
        action="decision_brief.version_revised",
        target_type="DecisionBriefVersion",
        target_id=version.id,
        request_id=request_id,
        after={"base_version_id": current.id},
    )
    db.commit()
    return brief


def start_brief_revision(
    db: Session,
    *,
    brief: DecisionBrief,
    actor_id: str,
    base_version_id: str,
    synthesis_version_id: str,
    expected_row_version: int,
    request_id: str,
) -> DecisionBrief:
    lock_investigation_lineage(
        db,
        workspace_id=brief.workspace_id,
        investigation_id=brief.investigation_id,
    )
    locked = db.scalar(
        select(DecisionBrief)
        .where(
            DecisionBrief.id == brief.id,
            DecisionBrief.workspace_id == brief.workspace_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise not_found("Decision Brief")
    brief = locked
    if brief.row_version != expected_row_version:
        raise version_conflict(brief.id, brief.row_version)
    if brief.current_version_id != base_version_id:
        raise ApiError(
            412,
            "VERSION_CONFLICT",
            "The revision base is no longer the current Decision Brief version.",
            {
                "resource_id": brief.id,
                "current_row_version": brief.row_version,
                "current_version_id": brief.current_version_id,
            },
        )
    if brief.status != "decision_ready":
        raise invalid_state("A revision must start from the current DecisionReady version.")
    base = db.scalar(
        select(DecisionBriefVersion).where(
            DecisionBriefVersion.id == base_version_id,
            DecisionBriefVersion.decision_brief_id == brief.id,
            DecisionBriefVersion.workspace_id == brief.workspace_id,
        )
    )
    if base is None:
        raise not_found("Decision Brief base version")
    readiness = db.scalar(
        select(DecisionBriefReadinessReview).where(
            DecisionBriefReadinessReview.decision_brief_version_id == base.id,
            DecisionBriefReadinessReview.workspace_id == brief.workspace_id,
            DecisionBriefReadinessReview.decision == "mark_decision_ready",
        )
    )
    if readiness is None:
        raise ApiError(409, "APPROVAL_REQUIRED", "The revision base is not DecisionReady.")
    synthesis_version = db.scalar(
        select(InvestigationSynthesisVersion)
        .join(
            InvestigationSynthesis,
            InvestigationSynthesis.id == InvestigationSynthesisVersion.synthesis_id,
        )
        .where(
            InvestigationSynthesisVersion.id == synthesis_version_id,
            InvestigationSynthesisVersion.workspace_id == brief.workspace_id,
            InvestigationSynthesis.investigation_id == brief.investigation_id,
            InvestigationSynthesis.workspace_id == brief.workspace_id,
        )
    )
    if synthesis_version is None:
        raise not_found("Verified synthesis version")
    if synthesis_version.data_authenticity != brief.data_authenticity:
        raise ApiError(
            422,
            "LINEAGE_INTEGRITY_ERROR",
            "Revision grounding must preserve the Brief data authenticity.",
        )
    snapshot = _reference_snapshot(db, synthesis_version)
    grounded_blocks = _initial_blocks(
        db,
        synthesis=synthesis_version,
        snapshot=snapshot,
        actor_id=actor_id,
    )
    preserved_human_blocks = [
        deepcopy(block)
        for block in base.block_document["blocks"]
        if block["type"] in {"pm_judgment", "recommendation"}
    ]
    used_ids = {block["id"] for block in preserved_human_blocks}
    rebased_grounding: list[dict[str, Any]] = []
    for block in grounded_blocks["blocks"]:
        if block["type"] not in {"fact", "synthesis"}:
            continue
        candidate = deepcopy(block)
        if candidate["id"] in used_ids:
            candidate["id"] = f"grounding-{candidate['id']}"
        used_ids.add(candidate["id"])
        rebased_grounding.append(candidate)
    blocks = {
        "schema_version": base.block_document["schema_version"],
        "blocks": [*rebased_grounding, *preserved_human_blocks],
        "no_counter_evidence_search": deepcopy(
            base.block_document.get("no_counter_evidence_search")
        ),
    }
    # Human blocks are copied only from an immutable, previously ready base;
    # their original actor remains their provenance. Grounded blocks are rebuilt
    # from the newly verified synthesis and must match its exact snapshot.
    _validate_block_references(db, blocks, snapshot)
    version = DecisionBriefVersion(
        workspace_id=brief.workspace_id,
        decision_brief_id=brief.id,
        version_number=base.version_number + 1,
        synthesis_version_id=synthesis_version.id,
        synthesis_review_id=snapshot["synthesis_review_id"],
        block_document=blocks,
        reference_snapshot_json=snapshot,
        template_version=base.template_version,
        human_edit_digest=digest(blocks),
        created_by=actor_id,
        data_authenticity=brief.data_authenticity,
    )
    db.add(version)
    db.flush()
    brief.current_version_id = version.id
    brief.status = "draft"
    brief.row_version += 1
    audit(
        db,
        workspace_id=brief.workspace_id,
        actor_id=actor_id,
        action="decision_brief.revision_started",
        target_type="DecisionBriefVersion",
        target_id=version.id,
        request_id=request_id,
        after={
            "base_version_id": base.id,
            "synthesis_version_id": synthesis_version.id,
            "synthesis_review_id": snapshot["synthesis_review_id"],
        },
    )
    db.commit()
    return brief


def _validate_block_references(
    db: Session,
    document: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    actor_id: str | None = None,
) -> None:
    links = db.scalars(
        select(ClaimEvidence).where(ClaimEvidence.id.in_(snapshot["claim_evidence_ids"]))
    ).all()
    evidence = {
        row.id: row
        for row in db.scalars(
            select(Evidence).where(Evidence.id.in_(snapshot["evidence_ids"]))
        ).all()
    }
    evidence_by_claim: dict[str, set[str]] = {}
    for link in links:
        evidence_by_claim.setdefault(link.claim_version_id, set()).add(link.evidence_id)
    synthesis = db.get(InvestigationSynthesisVersion, snapshot["synthesis_version_id"])
    if synthesis is None:
        raise ApiError(422, "LINEAGE_INTEGRITY_ERROR", "Synthesis grounding is missing.")
    ids: set[str] = set()
    synthesis_count = 0
    for block in document["blocks"]:
        if block["id"] in ids:
            raise ApiError(422, "VALIDATION_ERROR", "Brief block IDs must be unique.")
        ids.add(block["id"])
        if block["type"] == "fact":
            if not set(block["claim_version_ids"]).issubset(snapshot["claim_version_ids"]):
                raise ApiError(
                    422, "LINEAGE_INTEGRITY_ERROR", "Fact ClaimVersion escaped the synthesis."
                )
            claim_ids = set(block["claim_version_ids"])
            evidence_ids = set(block["evidence_ids"])
            allowed_evidence = set().union(
                *(evidence_by_claim.get(claim_id, set()) for claim_id in claim_ids)
            )
            if not evidence_ids.issubset(allowed_evidence):
                raise ApiError(
                    422,
                    "LINEAGE_INTEGRITY_ERROR",
                    "Fact Evidence is not linked to its ClaimVersion.",
                )
            if any(
                not (evidence_by_claim.get(claim_id, set()) & evidence_ids)
                for claim_id in claim_ids
            ):
                raise ApiError(
                    422,
                    "LINEAGE_INTEGRITY_ERROR",
                    "Every Fact ClaimVersion requires one of its own Evidence records.",
                )
            expected_content = {
                evidence[evidence_id].content_version_id
                for evidence_id in evidence_ids
                if evidence_id in evidence
            }
            if set(block["content_version_ids"]) != expected_content:
                raise ApiError(
                    422,
                    "LINEAGE_INTEGRITY_ERROR",
                    "Fact content must exactly match its selected Evidence lineage.",
                )
        if block["type"] == "synthesis":
            synthesis_count += 1
            expected = {
                "synthesis_version_id": synthesis.id,
                "body": synthesis.executive_summary,
                "generation_method": synthesis.generation_method,
                "generator_version": synthesis.generator_version,
                "model_prompt_refs": synthesis.model_prompt_refs_json,
            }
            if any(block[field] != value for field, value in expected.items()):
                raise ApiError(
                    422,
                    "LINEAGE_INTEGRITY_ERROR",
                    "Synthesis block text and generation provenance are immutable.",
                )
        if (
            block["type"] == "pm_judgment"
            and actor_id is not None
            and block["actor_id"] != actor_id
        ):
            raise ApiError(403, "FORBIDDEN", "PM judgment actor must be the current principal.")
    if synthesis_count != 1:
        raise ApiError(422, "LINEAGE_INTEGRITY_ERROR", "Brief requires one synthesis block.")


_PLACEHOLDER_MARKERS = ("pending", "tbd", "todo", "placeholder", "to be determined")


def _is_placeholder(value: str) -> bool:
    normalized = " ".join(value.lower().split())
    return not normalized or any(marker in normalized for marker in _PLACEHOLDER_MARKERS)


def _readiness_context(
    db: Session,
    *,
    brief: DecisionBrief,
    version: DecisionBriefVersion,
    actor_id: str | None = None,
) -> dict[str, Any]:
    _validate_block_references(
        db,
        version.block_document,
        version.reference_snapshot_json,
        actor_id=actor_id,
    )
    issues = _current_reference_issues(db, version)
    if issues:
        raise ApiError(
            409,
            "APPROVAL_REQUIRED",
            "Brief references no longer match the exact reviewed lineage.",
            {"affected_references": issues},
        )
    blocks = version.block_document["blocks"]
    facts = [block for block in blocks if block["type"] == "fact"]
    judgments = [block for block in blocks if block["type"] == "pm_judgment"]
    recommendations = [block for block in blocks if block["type"] == "recommendation"]
    if not facts:
        raise ApiError(422, "VALIDATION_ERROR", "Readiness requires at least one cited Fact.")
    if not judgments or any(_is_placeholder(block["body"]) for block in judgments):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Readiness requires a substantive PM Judgment authored by the current PM.",
        )
    if (
        not recommendations
        or any(
            block["recommendation_status"] not in {"accepted", "rejected"}
            for block in recommendations
        )
        or not any(
            block["recommendation_status"] == "accepted" and not _is_placeholder(block["body"])
            for block in recommendations
        )
        or any(
            block["recommendation_status"] == "accepted" and _is_placeholder(block["body"])
            for block in recommendations
        )
    ):
        raise ApiError(
            422,
            "VALIDATION_ERROR",
            "Every Recommendation must be accepted or rejected and one complete action accepted.",
        )
    synthesis = db.get(InvestigationSynthesisVersion, version.synthesis_version_id)
    if (
        synthesis is None
        or not synthesis.limitations
        or any(_is_placeholder(item) for item in synthesis.limitations)
    ):
        raise ApiError(422, "VALIDATION_ERROR", "Readiness requires explicit limitations.")
    investigation = db.get(Investigation, brief.investigation_id)
    if investigation is None or investigation.current_scope_version_id is None:
        raise ApiError(422, "LINEAGE_INTEGRITY_ERROR", "Investigation scope is missing.")
    from services.api.app.db.models import InvestigationScopeVersion

    scope = db.get(InvestigationScopeVersion, investigation.current_scope_version_id)
    if scope is None or _is_placeholder(scope.decision_question):
        raise ApiError(422, "VALIDATION_ERROR", "Decision Question requires PM confirmation.")
    snapshot_link_ids = version.reference_snapshot_json.get("claim_evidence_ids", [])
    opposing_links = db.scalars(
        select(ClaimEvidence).where(
            ClaimEvidence.id.in_(snapshot_link_ids), ClaimEvidence.stance == "opposes"
        )
    ).all()
    counter_evidence_ids = [
        link.evidence_id
        for link in opposing_links
        if (latest := latest_evidence_review(db, link.evidence_id)) is not None
        and latest.decision in {"valid", "weak"}
    ]
    no_counter = version.block_document.get("no_counter_evidence_search")
    if not counter_evidence_ids:
        if no_counter is None:
            raise ApiError(
                422,
                "VALIDATION_ERROR",
                "Readiness requires counter-evidence or an explicit no-counter search record.",
            )
        scoped_sources = set(scope.source_scope_json.get("source_connection_ids", []))
        if set(no_counter["source_connection_ids"]) != scoped_sources:
            raise ApiError(
                422,
                "LINEAGE_INTEGRITY_ERROR",
                "No-counter search sources must exactly match the confirmed Investigation scope.",
            )
        scoped_window = scope.time_range_json
        if no_counter["window_start"] != scoped_window.get("start") or no_counter[
            "window_end"
        ] != scoped_window.get("end"):
            raise ApiError(
                422,
                "LINEAGE_INTEGRITY_ERROR",
                "No-counter search window must exactly match the confirmed Investigation scope.",
            )
        if any(_is_placeholder(item) for item in no_counter["limitations"]):
            raise ApiError(
                422, "VALIDATION_ERROR", "No-counter search limitations must be substantive."
            )
    return {
        "decision_question": scope.decision_question,
        "limitations": synthesis.limitations,
        "counter_evidence_ids": sorted(counter_evidence_ids),
        "no_counter_evidence_search": no_counter,
    }


def _assert_exportable_exact_version(
    db: Session, *, brief: DecisionBrief, version: DecisionBriefVersion
) -> dict[str, Any]:
    if brief.current_version_id != version.id or brief.status != "decision_ready":
        raise ApiError(
            409, "APPROVAL_REQUIRED", "Export requires the current DecisionReady version."
        )
    readiness = db.scalar(
        select(DecisionBriefReadinessReview).where(
            DecisionBriefReadinessReview.decision_brief_version_id == version.id,
            DecisionBriefReadinessReview.decision == "mark_decision_ready",
        )
    )
    freshness = latest_freshness(db, version.id)
    if readiness is None or freshness is None or freshness.status != "current":
        raise ApiError(409, "APPROVAL_REQUIRED", "Export requires a ready, current exact version.")
    return _readiness_context(db, brief=brief, version=version)


def mark_ready(
    db: Session,
    *,
    brief: DecisionBrief,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> DecisionBriefReadinessReview:
    lock_investigation_lineage(
        db,
        workspace_id=brief.workspace_id,
        investigation_id=brief.investigation_id,
    )
    brief = _lock_brief_for_command(db, brief)
    if brief.row_version != payload["expected_row_version"]:
        raise version_conflict(brief.id, brief.row_version)
    if brief.current_version_id != payload["decision_brief_version_id"] or brief.status != "draft":
        raise invalid_state("Only the current Draft version can become DecisionReady.")
    version = db.get(DecisionBriefVersion, brief.current_version_id)
    if version is None:
        raise not_found("Decision Brief version")
    _readiness_context(db, brief=brief, version=version, actor_id=actor_id)
    if (
        digest(
            {
                "decision_brief_version_id": version.id,
                "block_document": version.block_document,
                "reference_snapshot": version.reference_snapshot_json,
                "policy_version": payload["policy_version"],
            }
        )
        != payload["checklist_digest"]
    ):
        raise ApiError(412, "VERSION_CONFLICT", "Readiness checklist digest changed.")
    review = DecisionBriefReadinessReview(
        workspace_id=brief.workspace_id,
        decision_brief_version_id=version.id,
        decision=payload["decision"],
        reviewer_id=actor_id,
        reason=payload["reason"],
        policy_version=payload["policy_version"],
        checklist_digest=payload["checklist_digest"],
        data_authenticity=brief.data_authenticity,
    )
    freshness = DecisionBriefFreshnessRecord(
        workspace_id=brief.workspace_id,
        decision_brief_version_id=version.id,
        status="current",
        affected_reference_snapshot_json=[],
        reason="All exact-version references match the readiness snapshot.",
        policy_version="brief-freshness-v1",
        data_authenticity=brief.data_authenticity,
    )
    db.add_all([review, freshness])
    brief.status = "decision_ready"
    brief.row_version += 1
    audit(
        db,
        workspace_id=brief.workspace_id,
        actor_id=actor_id,
        action="decision_brief.marked_ready",
        target_type="DecisionBriefVersion",
        target_id=version.id,
        request_id=request_id,
        after={"readiness_review_id": review.id, "freshness_record_id": freshness.id},
        reason=review.reason,
    )
    db.commit()
    return review


def freshness_recheck(
    db: Session,
    *,
    version: DecisionBriefVersion,
    actor_id: str,
    reason: str,
    request_id: str,
) -> DecisionBriefFreshnessRecord:
    brief = db.get(DecisionBrief, version.decision_brief_id)
    if brief is None or brief.workspace_id != version.workspace_id:
        raise not_found("Decision Brief")
    lock_investigation_lineage(
        db,
        workspace_id=brief.workspace_id,
        investigation_id=brief.investigation_id,
    )
    db.refresh(version)
    affected = _current_reference_issues(db, version)
    record = DecisionBriefFreshnessRecord(
        workspace_id=version.workspace_id,
        decision_brief_version_id=version.id,
        status="evidence_stale" if affected else "current",
        affected_reference_snapshot_json=affected,
        reason=reason,
        policy_version="brief-freshness-v1",
        data_authenticity=version.data_authenticity,
    )
    db.add(record)
    audit(
        db,
        workspace_id=version.workspace_id,
        actor_id=actor_id,
        action="decision_brief.freshness_rechecked",
        target_type="DecisionBriefVersion",
        target_id=version.id,
        request_id=request_id,
        after={"status": record.status, "affected_count": len(affected)},
    )
    db.commit()
    return record


def latest_freshness(db: Session, version_id: str) -> DecisionBriefFreshnessRecord | None:
    return db.scalar(
        select(DecisionBriefFreshnessRecord)
        .where(DecisionBriefFreshnessRecord.decision_brief_version_id == version_id)
        .order_by(
            DecisionBriefFreshnessRecord.assessed_at.desc(),
            DecisionBriefFreshnessRecord.id.desc(),
        )
    )


def _render_export_markdown(
    *,
    version: DecisionBriefVersion,
    export_type: str,
    selection_manifest: dict[str, Any],
    readiness_context: dict[str, Any],
) -> tuple[str, str]:
    if export_type != "prd_research_input_markdown":
        raise ApiError(422, "VALIDATION_ERROR", "Phase 1 exports Markdown only.")
    selected = set(selection_manifest["block_ids"])
    blocks = [block for block in version.block_document["blocks"] if block["id"] in selected]
    if len(blocks) != len(selected):
        raise ApiError(422, "VALIDATION_ERROR", "The selection contains an unknown block.")
    forbidden = [
        block
        for block in blocks
        if block["type"] == "synthesis"
        or (block["type"] == "recommendation" and block["recommendation_status"] != "accepted")
    ]
    if forbidden:
        raise ApiError(
            422, "POLICY_BLOCKED", "Synthesis or unaccepted content cannot enter PRD input."
        )
    authenticity_label = version.data_authenticity.replace("_", " ").title()
    lines = [
        "# PRD Research Input",
        "",
        f"> Data authenticity: {authenticity_label}",
        "",
        "## Decision Context",
        "",
        readiness_context["decision_question"],
        "",
        "## Limitations and counter-evidence",
        "",
    ]
    lines.extend(f"- {item}" for item in readiness_context["limitations"])
    no_counter = readiness_context["no_counter_evidence_search"]
    if readiness_context["counter_evidence_ids"]:
        lines.extend(
            [
                "- Counter-evidence reviewed: "
                + ", ".join(
                    f"evidence:{value}" for value in readiness_context["counter_evidence_ids"]
                )
            ]
        )
    elif no_counter is not None:
        lines.extend(
            [
                "- No counter-evidence found within the recorded search scope; this is not "
                "evidence that none exists.",
                "- Queries: " + "; ".join(no_counter["queries"]),
                "- Sources: " + ", ".join(no_counter["source_connection_ids"]),
                f"- Window: {no_counter['window_start']} to {no_counter['window_end']}",
                "- Exclusions: " + "; ".join(no_counter["exclusion_criteria"]),
            ]
        )
        lines.extend(f"- Search limitation: {item}" for item in no_counter["limitations"])
    lines.append("")
    for block in blocks:
        title = {
            "fact": "Fact",
            "pm_judgment": "PM Judgment",
            "recommendation": "Recommendation",
        }[block["type"]]
        lines.extend([f"## {title}", "", block["body"], ""])
        if block["type"] == "fact" and selection_manifest["include_citations"]:
            lines.extend(
                [
                    "Citations: "
                    + ", ".join(
                        f"content-version:{value}" for value in block["content_version_ids"]
                    ),
                    "",
                ]
            )
    rendered = "\n".join(lines).rstrip() + "\n"
    reference_digest = digest(
        {
            "decision_brief_version_id": version.id,
            "export_type": export_type,
            "selection_manifest": selection_manifest,
            "selected_blocks": blocks,
            "reference_snapshot": version.reference_snapshot_json,
            "readiness_context": readiness_context,
            "data_authenticity": version.data_authenticity,
        }
    )
    return rendered, reference_digest


def render_export_preview(
    db: Session,
    *,
    brief: DecisionBrief,
    version: DecisionBriefVersion,
    export_type: str,
    selection_manifest: dict[str, Any],
) -> tuple[str, str]:
    lock_investigation_lineage(
        db,
        workspace_id=brief.workspace_id,
        investigation_id=brief.investigation_id,
    )
    db.refresh(brief)
    db.refresh(version)
    readiness_context = _assert_exportable_exact_version(db, brief=brief, version=version)
    return _render_export_markdown(
        version=version,
        export_type=export_type,
        selection_manifest=selection_manifest,
        readiness_context=readiness_context,
    )


def create_export(
    db: Session,
    *,
    brief: DecisionBrief,
    version: DecisionBriefVersion,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> BriefExport:
    rendered, reference_digest = render_export_preview(
        db,
        brief=brief,
        version=version,
        export_type=payload["export_type"],
        selection_manifest=payload["selection_manifest"],
    )
    if payload["reference_digest"] != reference_digest:
        raise ApiError(412, "VERSION_CONFLICT", "Export preview digest changed.")
    output_digest = digest(rendered.encode())
    export_id = new_id()
    relative = f"workspaces/{brief.workspace_id}/brief-exports/{export_id}.md"
    export = BriefExport(
        id=export_id,
        workspace_id=brief.workspace_id,
        decision_brief_version_id=version.id,
        export_type=payload["export_type"],
        destination=payload["destination"],
        selection_manifest_json=payload["selection_manifest"],
        reference_digest=reference_digest,
        policy_version="export-policy-v1",
        template_version="prd-research-input-v1",
        rendered_snapshot_uri=f"object://{relative}",
        output_digest=output_digest,
        created_by=actor_id,
        data_authenticity=brief.data_authenticity,
    )
    db.add(export)
    db.flush()
    get_object_store().put(relative, rendered.encode(), "text/markdown")
    audit(
        db,
        workspace_id=brief.workspace_id,
        actor_id=actor_id,
        action="brief_export.created",
        target_type="BriefExport",
        target_id=export.id,
        request_id=request_id,
        after={
            "decision_brief_version_id": version.id,
            "reference_digest": reference_digest,
            "output_digest": output_digest,
        },
    )
    db.commit()
    return export


def readiness_checklist_digest(version: DecisionBriefVersion, policy_version: str) -> str:
    return digest(
        {
            "decision_brief_version_id": version.id,
            "block_document": version.block_document,
            "reference_snapshot": version.reference_snapshot_json,
            "policy_version": policy_version,
        }
    )
