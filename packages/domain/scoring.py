"""Versioned deterministic Evidence and Claim confidence helpers.

The scores are heuristic, deliberately labelled uncalibrated, and never exposed
as probabilities.  Inputs are retained so a score can be replayed exactly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from .canonical import canonical_digest
from .errors import InvariantViolation

_QUANT = Decimal("0.0001")


def _decimal(value: Decimal | float | int | str) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise InvariantViolation("Score inputs must be finite numbers.")
    return result


def _unit(value: Decimal | float | int | str, field: str) -> Decimal:
    result = _decimal(value)
    if result < 0 or result > 1:
        raise InvariantViolation(f"{field} must be between 0 and 1 inclusive.")
    return result


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(_QUANT, rounding=ROUND_HALF_UP)


class HeuristicLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CalibrationStatus(StrEnum):
    UNCALIBRATED = "uncalibrated"


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class DeterministicScore:
    numeric_score: Decimal
    level: HeuristicLevel
    policy_version: str
    calibration_status: CalibrationStatus = CalibrationStatus.UNCALIBRATED

    @property
    def as_float(self) -> float:
        return float(self.numeric_score)


@dataclass(frozen=True, slots=True)
class EvidenceFactors:
    relevance: Decimal | float
    reliability: Decimal | float
    independence: Decimal | float
    recency: Decimal | float
    specificity: Decimal | float

    def normalized(self) -> Mapping[str, Decimal]:
        return {
            "relevance": _unit(self.relevance, "relevance"),
            "reliability": _unit(self.reliability, "reliability"),
            "independence": _unit(self.independence, "independence"),
            "recency": _unit(self.recency, "recency"),
            "specificity": _unit(self.specificity, "specificity"),
        }


@dataclass(frozen=True, slots=True)
class EvidenceScorePolicy:
    version: str = "evidence-score-v1"
    relevance_weight: Decimal = Decimal("0.30")
    reliability_weight: Decimal = Decimal("0.25")
    independence_weight: Decimal = Decimal("0.20")
    recency_weight: Decimal = Decimal("0.10")
    specificity_weight: Decimal = Decimal("0.15")

    def weights(self) -> Mapping[str, Decimal]:
        weights = {
            "relevance": _unit(self.relevance_weight, "relevance_weight"),
            "reliability": _unit(self.reliability_weight, "reliability_weight"),
            "independence": _unit(self.independence_weight, "independence_weight"),
            "recency": _unit(self.recency_weight, "recency_weight"),
            "specificity": _unit(self.specificity_weight, "specificity_weight"),
        }
        if sum(weights.values(), Decimal(0)) != Decimal(1):
            raise InvariantViolation("Evidence score weights must sum exactly to 1.")
        if not self.version:
            raise InvariantViolation("Evidence score policy requires a version.")
        return weights


def _level(score: Decimal) -> HeuristicLevel:
    if score >= Decimal("0.75"):
        return HeuristicLevel.HIGH
    if score >= Decimal("0.50"):
        return HeuristicLevel.MEDIUM
    return HeuristicLevel.LOW


def compute_evidence_score(
    factors: EvidenceFactors,
    *,
    policy: EvidenceScorePolicy = EvidenceScorePolicy(),
) -> DeterministicScore:
    values = factors.normalized()
    weights = policy.weights()
    numeric = _rounded(sum((values[name] * weight for name, weight in weights.items()), Decimal(0)))
    return DeterministicScore(numeric, _level(numeric), policy.version)


@dataclass(frozen=True, slots=True)
class ClaimEvidenceScoreInput:
    evidence_id: str
    evidence_review_id: str
    content_version_id: str
    score: Decimal | float
    stance: EvidenceStance
    weight: Decimal | float = Decimal(1)
    independence_group_id: str | None = None
    duplicate_cluster_id: str | None = None
    source_connection_id: str | None = None

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "stance", EvidenceStance(self.stance))
        except ValueError as exc:
            raise InvariantViolation("Claim evidence has an unknown stance.") from exc
        if not self.evidence_id:
            raise InvariantViolation("Claim evidence score input requires an Evidence ID.")
        if not self.evidence_review_id:
            raise InvariantViolation("Claim evidence score input requires an EvidenceReview ID.")
        if not self.content_version_id:
            raise InvariantViolation("Claim evidence score input requires a ContentVersion ID.")

    def normalized_score(self) -> Decimal:
        return _unit(self.score, "evidence score")

    def normalized_weight(self) -> Decimal:
        return _unit(self.weight, "claim evidence weight")

    def replay_input(self) -> dict[str, str | None]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_review_id": self.evidence_review_id,
            "content_version_id": self.content_version_id,
            "stance": self.stance.value,
            "score": str(_rounded(self.normalized_score())),
            "weight": str(_rounded(self.normalized_weight())),
            "independence_group_id": self.independence_group_id,
            "duplicate_cluster_id": self.duplicate_cluster_id,
            "source_connection_id": self.source_connection_id,
        }


@dataclass(frozen=True, slots=True)
class ClaimConfidenceInputs:
    support_weight: Decimal
    opposition_weight: Decimal
    average_evidence_score: Decimal
    evidence_coverage: Decimal
    source_diversity: Decimal
    sample_factor: Decimal
    contradiction_penalty: Decimal

    def as_dict(self) -> dict[str, str]:
        # Decimal strings prevent a persistence layer from silently changing the
        # replay inputs through binary float conversion.
        return {
            "support_weight": str(self.support_weight),
            "opposition_weight": str(self.opposition_weight),
            "average_evidence_score": str(self.average_evidence_score),
            "evidence_coverage": str(self.evidence_coverage),
            "source_diversity": str(self.source_diversity),
            "sample_factor": str(self.sample_factor),
            "contradiction_penalty": str(self.contradiction_penalty),
        }


@dataclass(frozen=True, slots=True)
class ClaimScorePolicy:
    version: str = "claim-confidence-v2"
    target_evidence_count: int = 3
    target_independent_source_count: int = 3
    target_sample_count: int = 4

    def __post_init__(self) -> None:
        if not self.version:
            raise InvariantViolation("Claim score policy requires a version.")
        if (
            min(
                self.target_evidence_count,
                self.target_independent_source_count,
                self.target_sample_count,
            )
            < 1
        ):
            raise InvariantViolation("Claim score targets must be positive.")


def build_claim_confidence_inputs(
    evidence: Iterable[ClaimEvidenceScoreInput],
    *,
    policy: ClaimScorePolicy = ClaimScorePolicy(),
) -> ClaimConfidenceInputs:
    items = list(evidence)
    if not items:
        return ClaimConfidenceInputs(*(Decimal(0) for _ in range(7)))
    ids = [item.evidence_id for item in items]
    if any(not item_id for item_id in ids) or len(ids) != len(set(ids)):
        raise InvariantViolation("Claim score evidence IDs must be non-empty and unique.")

    effective: list[tuple[ClaimEvidenceScoreInput, Decimal, Decimal]] = []
    for item in items:
        effective.append((item, item.normalized_score(), item.normalized_weight()))

    support = sum(
        (
            score * weight
            for item, score, weight in effective
            if item.stance is EvidenceStance.SUPPORTS
        ),
        Decimal(0),
    )
    opposition = sum(
        (
            score * weight
            for item, score, weight in effective
            if item.stance is EvidenceStance.OPPOSES
        ),
        Decimal(0),
    )
    total_effective = sum((score * weight for _, score, weight in effective), Decimal(0))
    total_weight = sum((weight for _, _, weight in effective), Decimal(0))
    average = total_effective / total_weight if total_weight else Decimal(0)

    relevant_count = sum(1 for item, _, _ in effective if item.stance is not EvidenceStance.NEUTRAL)
    coverage = min(Decimal(1), Decimal(relevant_count) / Decimal(policy.target_evidence_count))
    independent_groups = {
        item.independence_group_id
        or item.source_connection_id
        or f"content:{item.content_version_id}"
        for item, _, _ in effective
        if item.stance is not EvidenceStance.NEUTRAL
    }
    duplicate_groups = {
        item.duplicate_cluster_id or f"content:{item.content_version_id}"
        for item, _, _ in effective
        if item.stance is not EvidenceStance.NEUTRAL
    }
    source_groups = {
        item.source_connection_id or f"content:{item.content_version_id}"
        for item, _, _ in effective
        if item.stance is not EvidenceStance.NEUTRAL
    }
    independent_count = min(len(independent_groups), len(duplicate_groups), len(source_groups))
    diversity = min(
        Decimal(1),
        Decimal(independent_count) / Decimal(policy.target_independent_source_count),
    )
    sample = min(Decimal(1), Decimal(len(items)) / Decimal(policy.target_sample_count))
    contested = support + opposition
    opposition_share = opposition / contested if contested else Decimal(0)
    contradiction_penalty = opposition_share * Decimal("0.25")
    return ClaimConfidenceInputs(
        *(
            _rounded(value)
            for value in (
                support,
                opposition,
                average,
                coverage,
                diversity,
                sample,
                contradiction_penalty,
            )
        )
    )


def compute_claim_score_from_inputs(
    inputs: ClaimConfidenceInputs,
    *,
    policy: ClaimScorePolicy = ClaimScorePolicy(),
) -> DeterministicScore:
    support = _decimal(inputs.support_weight)
    opposition = _decimal(inputs.opposition_weight)
    if support < 0 or opposition < 0:
        raise InvariantViolation("Claim support/opposition weights cannot be negative.")
    contested = support + opposition
    support_share = support / contested if contested else Decimal(0)
    average = _unit(inputs.average_evidence_score, "average_evidence_score")
    coverage = _unit(inputs.evidence_coverage, "evidence_coverage")
    diversity = _unit(inputs.source_diversity, "source_diversity")
    sample = _unit(inputs.sample_factor, "sample_factor")
    penalty = _unit(inputs.contradiction_penalty, "contradiction_penalty")

    raw = (
        support_share * Decimal("0.40")
        + average * Decimal("0.25")
        + coverage * Decimal("0.15")
        + diversity * Decimal("0.10")
        + sample * Decimal("0.10")
        - penalty
    )
    numeric = _rounded(min(Decimal(1), max(Decimal(0), raw)))
    # One source or one duplicate/origin group can never justify "high", even
    # when many rows repeat the same support. This is a scoring invariant rather
    # than a presenter hint so exact replays retain the same ceiling.
    minimum_high_diversity = Decimal(2) / Decimal(policy.target_independent_source_count)
    if diversity < minimum_high_diversity:
        numeric = min(numeric, Decimal("0.7499"))
    return DeterministicScore(numeric, _level(numeric), policy.version)


def compute_claim_score(
    evidence: Iterable[ClaimEvidenceScoreInput],
    *,
    policy: ClaimScorePolicy = ClaimScorePolicy(),
) -> tuple[ClaimConfidenceInputs, DeterministicScore]:
    inputs = build_claim_confidence_inputs(evidence, policy=policy)
    return inputs, compute_claim_score_from_inputs(inputs, policy=policy)


@dataclass(frozen=True, slots=True)
class ClaimConfidenceAssessment:
    score: DeterministicScore
    input_digest: str
    breakdown: dict[str, object]


def assess_claim_confidence(
    evidence: Iterable[ClaimEvidenceScoreInput],
    *,
    policy: ClaimScorePolicy = ClaimScorePolicy(),
) -> ClaimConfidenceAssessment:
    ordered = sorted(list(evidence), key=lambda item: item.evidence_id)
    inputs, score = compute_claim_score(ordered, policy=policy)
    replay_inputs = [item.replay_input() for item in ordered]
    digest_payload = {
        "policy_version": policy.version,
        "evidence": replay_inputs,
    }
    breakdown: dict[str, object] = {
        "policy_version": policy.version,
        "score": str(score.numeric_score),
        "level": score.level.value,
        "calibration_status": score.calibration_status.value,
        "effective_evidence_count": len(replay_inputs),
        "aggregate_inputs": inputs.as_dict(),
        "evidence_inputs": replay_inputs,
    }
    return ClaimConfidenceAssessment(
        score=score,
        input_digest=canonical_digest(digest_payload),
        breakdown=breakdown,
    )
