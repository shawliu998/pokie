from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.api.app.core.errors import ApiError, not_found, version_conflict
from services.api.app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimReview,
    ClaimVersion,
    ContentVersion,
    DecisionBriefFreshnessRecord,
    DecisionBriefVersion,
    Evidence,
    EvidenceReview,
    ResearchRun,
)
from services.api.app.modules.common import (
    append_run_event,
    audit,
    digest,
    lock_investigation_lineage,
    text_digest,
)
from services.api.app.modules.evidence.confidence import assess_frozen_claim_evidence


def latest_evidence_review(db: Session, evidence_id: str) -> EvidenceReview | None:
    return db.scalar(
        select(EvidenceReview)
        .where(EvidenceReview.evidence_id == evidence_id)
        .order_by(EvidenceReview.reviewed_at.desc(), EvidenceReview.id.desc())
    )


def evidence_status(db: Session, evidence_id: str) -> str:
    review = latest_evidence_review(db, evidence_id)
    return review.decision if review else "proposed"


def claim_version_status(db: Session, version_id: str) -> str:
    """Return the current projection without mutating an immutable review.

    A historical Verify remains in the ledger, but it stops projecting as
    verified as soon as one of its exact EvidenceReview snapshots is no longer
    the latest review or the Claim loses all currently accepted supporting
    evidence.
    """

    version = db.get(ClaimVersion, version_id)
    claim = db.get(Claim, version.claim_id) if version is not None else None
    if version is None or claim is None:
        return "needs_review"
    if claim.current_version_id != version.id:
        return "superseded"
    review = db.scalar(
        select(ClaimReview)
        .where(ClaimReview.claim_version_id == version_id)
        .order_by(ClaimReview.reviewed_at.desc(), ClaimReview.id.desc())
    )
    if review is None:
        return "needs_review"
    if review.decision == "reject":
        return "rejected"
    if review.decision != "verify":
        return "needs_review"
    links = db.scalars(
        select(ClaimEvidence)
        .where(ClaimEvidence.claim_version_id == version_id)
        .order_by(ClaimEvidence.id)
    ).all()
    if {row.id for row in links} != set(review.claim_evidence_snapshot_json):
        return "needs_review"
    snapshot_reviews = db.scalars(
        select(EvidenceReview).where(EvidenceReview.id.in_(review.evidence_review_snapshot_json))
    ).all()
    snapshot_by_evidence = {row.evidence_id: row for row in snapshot_reviews}
    current_by_evidence: dict[str, EvidenceReview] = {}
    for evidence_id in {row.evidence_id for row in links}:
        latest = latest_evidence_review(db, evidence_id)
        if latest is None:
            return "needs_review"
        current_by_evidence[evidence_id] = latest
        frozen = snapshot_by_evidence.get(evidence_id)
        if frozen is None or frozen.id != latest.id or latest.decision == "rejected":
            return "needs_review"
    if not any(
        row.stance == "supports"
        and current_by_evidence[row.evidence_id].decision in {"valid", "weak"}
        for row in links
    ):
        return "needs_review"
    return "verified"


def _append_brief_staleness_for_evidence(
    db: Session,
    *,
    evidence: Evidence,
    review: EvidenceReview,
) -> list[str]:
    stale_version_ids: list[str] = []
    versions = db.scalars(
        select(DecisionBriefVersion).where(
            DecisionBriefVersion.workspace_id == evidence.workspace_id
        )
    ).all()
    for version in versions:
        if evidence.id not in version.reference_snapshot_json.get("evidence_ids", []):
            continue
        db.add(
            DecisionBriefFreshnessRecord(
                workspace_id=evidence.workspace_id,
                decision_brief_version_id=version.id,
                status="evidence_stale",
                affected_reference_snapshot_json=[
                    {
                        "evidence_id": evidence.id,
                        "latest_evidence_review_id": review.id,
                        "decision": review.decision,
                    }
                ],
                reason="An exact EvidenceReview dependency changed after Brief readiness.",
                policy_version="brief-freshness-v1",
                data_authenticity=version.data_authenticity,
            )
        )
        stale_version_ids.append(version.id)
    return stale_version_ids


def _append_brief_staleness_for_claim_version(
    db: Session,
    *,
    workspace_id: str,
    superseded_claim_version_id: str | None,
    data_authenticity: str,
) -> list[str]:
    """Append an auditable stale projection when a Claim current pointer moves."""

    if superseded_claim_version_id is None:
        return []
    stale_version_ids: list[str] = []
    versions = db.scalars(
        select(DecisionBriefVersion).where(DecisionBriefVersion.workspace_id == workspace_id)
    ).all()
    for version in versions:
        if superseded_claim_version_id not in version.reference_snapshot_json.get(
            "claim_version_ids", []
        ):
            continue
        db.add(
            DecisionBriefFreshnessRecord(
                workspace_id=workspace_id,
                decision_brief_version_id=version.id,
                status="evidence_stale",
                affected_reference_snapshot_json=[
                    {
                        "reference_type": "claim_version",
                        "reference_id": superseded_claim_version_id,
                    }
                ],
                reason="A frozen ClaimVersion dependency was superseded after Brief readiness.",
                policy_version="brief-freshness-v1",
                data_authenticity=data_authenticity,
            )
        )
        stale_version_ids.append(version.id)
    return stale_version_ids


def _invalidate_claim_projections_for_evidence(db: Session, evidence_id: str) -> list[str]:
    affected_claim_ids: list[str] = []
    claims = db.scalars(
        select(Claim)
        .join(ClaimVersion, ClaimVersion.id == Claim.current_version_id)
        .join(ClaimEvidence, ClaimEvidence.claim_version_id == ClaimVersion.id)
        .where(ClaimEvidence.evidence_id == evidence_id)
    ).all()
    for claim in claims:
        if (
            claim.current_version_id
            and claim_version_status(db, claim.current_version_id) != "verified"
        ):
            claim.aggregate_status = "needs_review"
            claim.row_version += 1
            affected_claim_ids.append(claim.id)
    return affected_claim_ids


def review_evidence(
    db: Session,
    *,
    evidence: Evidence,
    actor_id: str,
    decision: str,
    reason: str,
    policy_version: str,
    request_id: str,
) -> EvidenceReview:
    lock_investigation_lineage(
        db,
        workspace_id=evidence.workspace_id,
        investigation_id=evidence.investigation_id,
    )
    db.refresh(evidence)
    version = db.scalar(
        select(ContentVersion).where(
            ContentVersion.id == evidence.content_version_id,
            ContentVersion.workspace_id == evidence.workspace_id,
        )
    )
    if version is None:
        raise ApiError(422, "LINEAGE_INTEGRITY_ERROR", "Evidence lost its ContentVersion.")
    quote = version.normalized_body[evidence.quote_start : evidence.quote_end]
    if quote != evidence.quote_text or text_digest(quote) != evidence.quote_text_digest:
        raise ApiError(
            422, "LINEAGE_INTEGRITY_ERROR", "Evidence quote no longer matches its version."
        )
    review = EvidenceReview(
        workspace_id=evidence.workspace_id,
        evidence_id=evidence.id,
        decision=decision,
        reviewer_id=actor_id,
        reason=reason,
        policy_version=policy_version,
        data_authenticity=evidence.data_authenticity,
    )
    db.add(review)
    db.flush()
    affected_claim_ids = _invalidate_claim_projections_for_evidence(db, evidence.id)
    stale_brief_version_ids = _append_brief_staleness_for_evidence(
        db, evidence=evidence, review=review
    )
    run = db.get(ResearchRun, evidence.research_run_id)
    if run:
        append_run_event(
            db,
            workspace_id=evidence.workspace_id,
            investigation_id=evidence.investigation_id,
            run_id=evidence.research_run_id,
            event_type="evidence.reviewed",
            payload={"evidence_id": evidence.id, "evidence_review_id": review.id},
            trace_id=run.trace_id,
            event_idempotency_key=f"evidence-review:{review.id}",
        )
    audit(
        db,
        workspace_id=evidence.workspace_id,
        actor_id=actor_id,
        action="evidence.reviewed",
        target_type="Evidence",
        target_id=evidence.id,
        request_id=request_id,
        after={
            "review_id": review.id,
            "decision": decision,
            "invalidated_claim_ids": affected_claim_ids,
            "stale_decision_brief_version_ids": stale_brief_version_ids,
        },
        reason=reason,
    )
    db.commit()
    return review


def create_claim_version(
    db: Session,
    *,
    claim: Claim,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> ClaimVersion:
    lock_investigation_lineage(
        db,
        workspace_id=claim.workspace_id,
        investigation_id=claim.investigation_id,
    )
    db.refresh(claim)
    if claim.row_version != payload["expected_claim_row_version"]:
        raise version_conflict(claim.id, claim.row_version)
    superseded_claim_version_id = claim.current_version_id
    evidence_ids = [link["evidence_id"] for link in payload["evidence_links"]]
    evidence = db.scalars(
        select(Evidence).where(
            Evidence.workspace_id == claim.workspace_id,
            Evidence.investigation_id == claim.investigation_id,
            Evidence.research_run_id == claim.research_run_id,
            Evidence.id.in_(evidence_ids),
        )
    ).all()
    if len(evidence) != len(set(evidence_ids)):
        raise ApiError(422, "LINEAGE_INTEGRITY_ERROR", "Claim Evidence must share the Run.")
    next_version = (
        int(
            db.scalar(
                select(func.coalesce(func.max(ClaimVersion.version_number), 0)).where(
                    ClaimVersion.claim_id == claim.id
                )
            )
            or 0
        )
        + 1
    )
    confidence = assess_frozen_claim_evidence(
        db,
        evidence_rows=evidence,
        links_by_evidence_id={str(link["evidence_id"]): link for link in payload["evidence_links"]},
    )
    version = ClaimVersion(
        workspace_id=claim.workspace_id,
        claim_id=claim.id,
        version_number=next_version,
        claim_type=payload["claim_type"],
        text=payload["text"],
        confidence_inputs_json=confidence.breakdown,
        confidence_score=confidence.score.as_float,
        confidence_level=confidence.score.level.value,
        confidence_policy_version=confidence.score.policy_version,
        confidence_input_digest=confidence.input_digest,
        limitations=payload["limitations"],
        generation_method="human",
        generator_version="human-claim-revision-v1",
        suggestion_origin="none",
        created_by=actor_id,
        data_authenticity=claim.data_authenticity,
    )
    db.add(version)
    db.flush()
    for link in payload["evidence_links"]:
        db.add(
            ClaimEvidence(
                workspace_id=claim.workspace_id,
                claim_version_id=version.id,
                evidence_id=link["evidence_id"],
                stance=link["stance"],
                weight=link["weight"],
                rationale=link.get("rationale") or "Human revision link.",
                linked_by=actor_id,
                data_authenticity=claim.data_authenticity,
            )
        )
    claim.current_version_id = version.id
    claim.aggregate_status = "needs_review"
    claim.row_version += 1
    stale_brief_version_ids = _append_brief_staleness_for_claim_version(
        db,
        workspace_id=claim.workspace_id,
        superseded_claim_version_id=superseded_claim_version_id,
        data_authenticity=claim.data_authenticity,
    )
    audit(
        db,
        workspace_id=claim.workspace_id,
        actor_id=actor_id,
        action="claim.version_created",
        target_type="ClaimVersion",
        target_id=version.id,
        request_id=request_id,
        after={
            "version_number": version.version_number,
            "stale_decision_brief_version_ids": stale_brief_version_ids,
        },
    )
    db.commit()
    return version


def review_claim_version(
    db: Session,
    *,
    claim: Claim,
    version: ClaimVersion,
    actor_id: str,
    payload: dict[str, Any],
    request_id: str,
) -> ClaimReview:
    lock_investigation_lineage(
        db,
        workspace_id=claim.workspace_id,
        investigation_id=claim.investigation_id,
    )
    db.refresh(claim)
    if claim.row_version != payload["expected_claim_row_version"]:
        raise version_conflict(claim.id, claim.row_version)
    if version.claim_id != claim.id:
        raise not_found("ClaimVersion")
    terminal = db.scalar(
        select(ClaimReview).where(
            ClaimReview.claim_version_id == version.id,
            ClaimReview.decision.in_(("verify", "reject")),
        )
    )
    if terminal:
        raise ApiError(409, "INVALID_STATE", "This ClaimVersion already has a terminal review.")
    links = db.scalars(
        select(ClaimEvidence)
        .where(ClaimEvidence.claim_version_id == version.id)
        .order_by(ClaimEvidence.id)
    ).all()
    link_ids = [row.id for row in links]
    evidence_ids = [row.evidence_id for row in links]
    reviews = db.scalars(
        select(EvidenceReview).where(
            EvidenceReview.id.in_(payload.get("evidence_review_ids", [])),
            EvidenceReview.workspace_id == claim.workspace_id,
        )
    ).all()
    snapshot = {
        "claim_version_id": version.id,
        "claim_evidence_ids": link_ids,
        "evidence_review_ids": sorted(row.id for row in reviews),
    }
    snapshot_digest = digest(snapshot)
    if payload["decision"] == "verify":
        if {row.evidence_id for row in reviews} != set(evidence_ids):
            raise ApiError(
                422, "VALIDATION_ERROR", "Verify requires one exact review per Evidence."
            )
        if any(row.decision == "rejected" for row in reviews):
            raise ApiError(
                422, "VALIDATION_ERROR", "Rejected Evidence cannot verify a ClaimVersion."
            )
        latest_review_ids = {
            latest.id
            for evidence_id in evidence_ids
            if (latest := latest_evidence_review(db, evidence_id)) is not None
        }
        if latest_review_ids != {row.id for row in reviews}:
            raise ApiError(
                412,
                "VERSION_CONFLICT",
                "Claim verification requires the latest exact EvidenceReview for each Evidence.",
            )
        if payload.get("expected_claim_evidence_snapshot_digest") != snapshot_digest:
            raise ApiError(412, "VERSION_CONFLICT", "The ClaimEvidence snapshot digest changed.")
    review = ClaimReview(
        workspace_id=claim.workspace_id,
        claim_version_id=version.id,
        decision=payload["decision"],
        claim_evidence_snapshot_json=link_ids,
        evidence_review_snapshot_json=sorted(row.id for row in reviews),
        snapshot_digest=snapshot_digest,
        reviewer_id=actor_id,
        reason=payload["reason"],
        policy_version="claim-review-v1",
        data_authenticity=claim.data_authenticity,
    )
    db.add(review)
    db.flush()
    if payload["decision"] == "verify":
        claim.aggregate_status = "verified"
    elif payload["decision"] == "reject":
        claim.aggregate_status = "rejected"
    else:
        claim.aggregate_status = "needs_review"
    claim.row_version += 1
    run = db.get(ResearchRun, claim.research_run_id)
    if run:
        append_run_event(
            db,
            workspace_id=claim.workspace_id,
            investigation_id=claim.investigation_id,
            run_id=run.id,
            event_type="claim.version_reviewed",
            payload={
                "claim_id": claim.id,
                "claim_version_id": version.id,
                "claim_review_id": review.id,
            },
            trace_id=run.trace_id,
            event_idempotency_key=f"claim-review:{review.id}",
        )
    audit(
        db,
        workspace_id=claim.workspace_id,
        actor_id=actor_id,
        action="claim.version_reviewed",
        target_type="ClaimVersion",
        target_id=version.id,
        request_id=request_id,
        after={
            "review_id": review.id,
            "decision": review.decision,
            "snapshot_digest": snapshot_digest,
        },
        reason=payload["reason"],
    )
    db.commit()
    return review
