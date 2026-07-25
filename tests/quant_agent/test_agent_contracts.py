from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.contracts.quant import (
    QuantAgentDecision,
    QuantAgentPlan,
    QuantStrategyScopeDecision,
    QuantToolObservation,
)


def test_decision_is_closed_and_single_action() -> None:
    decision = QuantAgentDecision.model_validate(
        {
            "action": "inspect_research_context",
            "arguments": {},
            "decision_summary": "Inspect context.",
            "expected_result": "A context summary.",
        }
    )
    assert decision.action.value == "inspect_research_context"
    with pytest.raises(ValidationError):
        QuantAgentDecision.model_validate({**decision.model_dump(), "extra": True})


def test_observation_is_closed() -> None:
    observation = QuantToolObservation(
        action="create_candidate", success=True, safe_summary="Created."
    )
    assert observation.artifact_ids == []


def test_agent_plan_rejects_duplicate_or_unknown_candidate_families() -> None:
    base = {
        "objective_summary": "Execute a bounded plan.",
        "steps": [
            {
                "key": "experiment",
                "title": "Run experiments",
                "owner": "agent",
                "description": "Use registered strategy tools.",
            }
        ],
        "strategy_scope": {
            "schema_version": "quant-strategy-scope-v1",
            "status": "supported",
            "reason": "The request fits one registered template.",
            "proxy_description": None,
            "excluded_behaviors": [],
        },
        "selection_objective": "risk_adjusted_return",
        "max_experiments": 3,
        "max_repairs": 1,
        "completion_criteria": ["Compare all completed candidates."],
    }
    with pytest.raises(ValidationError):
        QuantAgentPlan.model_validate(
            {**base, "candidate_families": ["sma_crossover", "sma_crossover"]}
        )
    with pytest.raises(ValidationError):
        QuantAgentPlan.model_validate({**base, "candidate_families": ["arbitrary_python"]})
    with pytest.raises(ValidationError):
        QuantAgentPlan.model_validate(
            {
                **base,
                "candidate_families": ["sma_crossover"],
                "selection_objective": "whatever_the_model_prefers",
            }
        )


@pytest.mark.parametrize(
    ("status", "candidate_families", "proxy", "excluded", "valid"),
    [
        ("supported", ["sma_crossover"], None, [], True),
        ("supported", [], None, [], False),
        ("supported", ["sma_crossover"], "Use SMA.", [], False),
        ("bounded_proxy", ["sma_crossover"], "Use SMA.", ["Exact MACD omitted."], True),
        ("bounded_proxy", ["sma_crossover"], None, ["Exact MACD omitted."], False),
        ("bounded_proxy", ["sma_crossover"], "Use SMA.", [], False),
        ("unsupported", [], None, ["Short exposure is unsupported."], True),
        ("unsupported", ["sma_crossover"], None, ["Short exposure is unsupported."], False),
        ("unsupported", [], "Use SMA.", ["Exact MACD omitted."], False),
    ],
)
def test_strategy_scope_cross_constraints(
    status: str,
    candidate_families: list[str],
    proxy: str | None,
    excluded: list[str],
    valid: bool,
) -> None:
    scope_payload = {
        "schema_version": "quant-strategy-scope-v1",
        "status": status,
        "reason": "Classify before execution.",
        "proxy_description": proxy,
        "excluded_behaviors": excluded,
    }
    base = {
        "objective_summary": "Execute a bounded plan.",
        "steps": [
            {
                "key": "scope",
                "title": "Review scope",
                "owner": "agent",
                "description": "Classify the request before execution.",
            }
        ],
        "candidate_families": candidate_families,
        "strategy_scope": scope_payload,
        "selection_objective": "risk_adjusted_return",
        "max_experiments": 3,
        "max_repairs": 1,
        "completion_criteria": ["Stop when the scope is unsupported."],
    }
    if valid:
        plan = QuantAgentPlan.model_validate(base)
        assert plan.strategy_scope.status == status
        QuantStrategyScopeDecision.model_validate(scope_payload)
    else:
        with pytest.raises(ValidationError):
            QuantAgentPlan.model_validate(base)
