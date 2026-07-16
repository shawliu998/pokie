"""Authoritative, replayable ClaimVersion confidence projection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.domain.scoring import (
    ClaimConfidenceAssessment,
    ClaimEvidenceScoreInput,
    EvidenceFactors,
    EvidenceStance,
    assess_claim_confidence,
    compute_evidence_score,
)
from services.api.app.db.models import ContentItem, ContentVersion, Evidence, EvidenceReview


def _latest_review(db: Session, evidence_id: str) -> EvidenceReview | None:
    return db.scalar(
        select(EvidenceReview)
        .where(EvidenceReview.evidence_id == evidence_id)
        .order_by(EvidenceReview.reviewed_at.desc(), EvidenceReview.id.desc())
    )


def assess_frozen_claim_evidence(
    db: Session,
    *,
    evidence_rows: Iterable[Evidence],
    links_by_evidence_id: Mapping[str, Mapping[str, Any]],
) -> ClaimConfidenceAssessment:
    """Score only currently valid reviews over immutable evidence/content rows.

    Proposed, weak, rejected, deleted, and unavailable inputs remain queryable as
    provenance but do not contribute to the confidence of a new ClaimVersion.
    """

    inputs: list[ClaimEvidenceScoreInput] = []
    for evidence in sorted(evidence_rows, key=lambda row: row.id):
        link = links_by_evidence_id.get(evidence.id)
        if link is None:
            continue
        review = _latest_review(db, evidence.id)
        if review is None or review.decision != "valid":
            continue
        version = db.get(ContentVersion, evidence.content_version_id)
        if version is None or version.availability != "captured":
            continue
        item = db.get(ContentItem, version.content_item_id)
        if item is None:
            continue
        evidence_score = compute_evidence_score(
            EvidenceFactors(
                relevance=evidence.relevance,
                reliability=evidence.reliability,
                independence=evidence.independence,
                recency=evidence.recency,
                specificity=evidence.specificity,
            )
        )
        inputs.append(
            ClaimEvidenceScoreInput(
                evidence_id=evidence.id,
                evidence_review_id=review.id,
                content_version_id=version.id,
                score=evidence_score.numeric_score,
                stance=EvidenceStance(str(link["stance"])),
                weight=float(link["weight"]),
                independence_group_id=item.independence_group_id,
                duplicate_cluster_id=item.duplicate_cluster_id,
                source_connection_id=version.source_connection_id,
            )
        )
    return assess_claim_confidence(inputs)
