from __future__ import annotations

from packages.domain.scoring import ClaimEvidenceScoreInput, assess_claim_confidence


def _input(
    ordinal: int,
    *,
    stance: str = "supports",
    source: str | None = None,
    duplicate: str | None = None,
    independence: str | None = None,
) -> ClaimEvidenceScoreInput:
    return ClaimEvidenceScoreInput(
        evidence_id=f"evidence-{ordinal}",
        evidence_review_id=f"review-{ordinal}",
        content_version_id=f"content-{ordinal}",
        score=0.9,
        stance=stance,
        weight=0.25,
        source_connection_id=source or f"source-{ordinal}",
        duplicate_cluster_id=duplicate or f"duplicate-{ordinal}",
        independence_group_id=independence or f"origin-{ordinal}",
    )


def test_repeated_same_source_or_duplicate_cluster_cannot_be_high_confidence() -> None:
    repeated = assess_claim_confidence(
        [
            _input(
                ordinal,
                source="source-one",
                duplicate="duplicate-one",
                independence="origin-one",
            )
            for ordinal in range(4)
        ]
    )
    independent = assess_claim_confidence([_input(ordinal) for ordinal in range(4)])
    assert repeated.score.level.value == "medium"
    assert repeated.score.as_float < 0.75
    assert independent.score.level.value == "high"
    assert independent.score.as_float > repeated.score.as_float


def test_opposition_lowers_score_and_persists_replayable_contradiction_breakdown() -> None:
    support_only = assess_claim_confidence([_input(ordinal) for ordinal in range(4)])
    contested = assess_claim_confidence(
        [
            _input(0),
            _input(1),
            _input(2),
            _input(3, stance="opposes"),
        ]
    )
    aggregate = contested.breakdown["aggregate_inputs"]
    assert isinstance(aggregate, dict)
    assert float(aggregate["opposition_weight"]) > 0
    assert float(aggregate["contradiction_penalty"]) > 0
    assert contested.score.as_float < support_only.score.as_float
    assert contested.input_digest.startswith("sha256:")


def test_coverage_and_sample_size_are_authoritative_versioned_inputs() -> None:
    one = assess_claim_confidence([_input(0)])
    four = assess_claim_confidence([_input(ordinal) for ordinal in range(4)])
    one_inputs = one.breakdown["aggregate_inputs"]
    four_inputs = four.breakdown["aggregate_inputs"]
    assert isinstance(one_inputs, dict) and isinstance(four_inputs, dict)
    assert float(one_inputs["evidence_coverage"]) < float(four_inputs["evidence_coverage"])
    assert float(one_inputs["sample_factor"]) < float(four_inputs["sample_factor"])
    assert one.score.policy_version == "claim-confidence-v2"
    assert four.score.policy_version == "claim-confidence-v2"
    assert one.score.as_float < four.score.as_float


def test_claim_confidence_digest_is_order_independent_but_input_sensitive() -> None:
    forward = [_input(ordinal) for ordinal in range(4)]
    reverse = list(reversed(forward))
    changed = [*forward[:3], _input(3, stance="opposes")]
    assert (
        assess_claim_confidence(forward).input_digest
        == assess_claim_confidence(reverse).input_digest
    )
    assert (
        assess_claim_confidence(forward).input_digest
        != assess_claim_confidence(changed).input_digest
    )
