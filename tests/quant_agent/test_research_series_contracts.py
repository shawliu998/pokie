from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.contracts.quant import (
    FinishResearchArguments,
    QuantMarketPlanApproveRequest,
    QuantMarketRunV2CreateRequest,
    QuantResearchDecision,
    QuantResearchLoopPolicy,
    QuantResearchSeriesDecision,
)
from packages.contracts.quant.enums import QuantRunMode


def test_loop_policy_accepts_only_bounded_supported_shapes() -> None:
    policy = QuantResearchLoopPolicy(
        follow_up_mode="one_train_only_follow_up",
        max_versions=2,
        max_total_experiments=6,
        max_total_agent_actions=24,
    )

    assert policy.decision_partition == "train"
    assert policy.automatic_retry is False

    with pytest.raises(ValidationError):
        QuantResearchLoopPolicy(
            follow_up_mode="one_train_only_follow_up",
            max_versions=1,
            max_total_experiments=3,
            max_total_agent_actions=12,
        )


def test_series_decision_requires_complete_refinement_payload() -> None:
    decision = QuantResearchSeriesDecision(
        action="refine_selected",
        source_comparison_artifact_id="comparison-1",
        seed_candidate_id="candidate-b",
        focus="reduce_drawdown",
        refinement_reason="Test one bounded parameter change using training evidence only.",
    )
    finish = FinishResearchArguments(
        selected_candidate_id="candidate-b",
        conclusion="Candidate B leads the final training comparison.",
        next_step="run_more_research",
        series_decision=decision,
        research_decision=QuantResearchDecision(
            selected_candidate_id="candidate-b",
            source_comparison_artifact_id="comparison-1",
            decision_basis="approved_objective_rank",
        ),
    )

    assert finish.series_decision == decision
    assert finish.series_decision is not None
    assert finish.series_decision.evaluation_partition == "train"

    with pytest.raises(ValidationError):
        QuantResearchSeriesDecision(
            action="refine_selected",
            source_comparison_artifact_id="comparison-1",
            seed_candidate_id="candidate-b",
        )


def test_stop_decision_cannot_smuggle_refinement_context() -> None:
    with pytest.raises(ValidationError):
        QuantResearchSeriesDecision(
            action="stop",
            source_comparison_artifact_id="comparison-1",
            seed_candidate_id="candidate-b",
            focus="reduce_drawdown",
            refinement_reason="This must not be accepted.",
        )


def test_market_research_loop_is_root_auto_only() -> None:
    common = {
        "project_id": uuid4(),
        "question": "Test one bounded research series.",
        "expected_project_row_version": 1,
        "dataset_id": "market-v2-test",
        "research_start_utc": datetime(2024, 1, 1, tzinfo=UTC),
        "research_end_utc": datetime(2024, 3, 1, tzinfo=UTC),
        "research_loop": {
            "follow_up_mode": "one_train_only_follow_up",
            "max_versions": 2,
            "max_total_experiments": 6,
            "max_total_agent_actions": 24,
        },
    }
    request = QuantMarketRunV2CreateRequest.model_validate({"mode": QuantRunMode.AUTO, **common})
    assert request.research_loop is not None

    with pytest.raises(ValidationError):
        QuantMarketRunV2CreateRequest.model_validate({"mode": QuantRunMode.PLAN, **common})
    with pytest.raises(ValidationError):
        QuantMarketRunV2CreateRequest.model_validate(
            {
                "mode": QuantRunMode.AUTO,
                "parent_run_id": uuid4(),
                "seed_candidate_id": uuid4(),
                "refinement_reason": "Refine the source.",
                **common,
            }
        )


def test_market_plan_approval_can_attach_only_the_supported_bounded_loop() -> None:
    default_approval = QuantMarketPlanApproveRequest(
        expected_row_version=2,
        plan_revision=1,
    )
    assert default_approval.research_loop is None

    bounded_approval = QuantMarketPlanApproveRequest(
        expected_row_version=2,
        plan_revision=1,
        research_loop=QuantResearchLoopPolicy(
            follow_up_mode="one_train_only_follow_up",
            max_versions=2,
            max_total_experiments=6,
            max_total_agent_actions=24,
        ),
    )
    assert bounded_approval.research_loop is not None
    assert bounded_approval.research_loop.follow_up_mode == "one_train_only_follow_up"

    with pytest.raises(ValidationError):
        QuantMarketPlanApproveRequest(
            expected_row_version=2,
            plan_revision=1,
            research_loop=QuantResearchLoopPolicy(
                follow_up_mode="stop_after_run",
                max_versions=1,
                max_total_experiments=3,
                max_total_agent_actions=12,
            ),
        )
