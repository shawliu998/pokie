from __future__ import annotations

import pytest
from pydantic import SecretStr

from packages.contracts.quant import QuantAgentBudget, QuantAgentContext
from services.worker.app.quant_agent.prompt import build_plan_messages
from services.worker.app.quant_agent.provider import (
    MockQuantAgentProvider,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    QuantAgentProviderError,
)


def _context() -> QuantAgentContext:
    return QuantAgentContext(
        run_id="r",
        project_id="p",
        research_goal="Reduce drawdown",
        mode="auto",
        run_state="running",
        dataset_summary={},
        benchmark_summary=None,
        available_templates=[],
        candidates=[],
        budget=QuantAgentBudget(
            max_iterations=8,
            used_iterations=0,
            remaining_iterations=8,
            max_experiments=3,
            used_experiments=0,
            remaining_experiments=3,
            max_repairs=2,
            used_repairs=0,
            remaining_repairs=2,
        ),
        recent_events=[],
        recent_observations=[],
        plan_summary=None,
        final_conclusion=None,
    )


def test_mock_starts_with_context_inspection() -> None:
    assert MockQuantAgentProvider().decide(_context()).action.value == "inspect_research_context"


def test_mock_finishes_when_iteration_budget_is_exhausted() -> None:
    context = _context().model_copy(
        update={
            "budget": QuantAgentBudget(
                max_iterations=8,
                used_iterations=7,
                remaining_iterations=1,
                max_experiments=3,
                used_experiments=3,
                remaining_experiments=0,
                max_repairs=2,
                used_repairs=0,
                remaining_repairs=2,
            ),
            "recent_observations": [
                {"action": "inspect_research_context", "success": True},
                {"action": "list_strategy_templates", "success": True},
            ],
        }
    )
    assert MockQuantAgentProvider().decide(context).action.value == "finish_research"


def test_model_provider_rejects_invalid_decision_json() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            SecretStr("test-key"), "https://api.example.com", "test-model"
        )
    )
    provider._complete = lambda _messages: "{}"  # type: ignore[method-assign]

    with pytest.raises(QuantAgentProviderError, match="closed validation"):
        provider.decide(_context())


def test_plan_prompt_uses_plan_contract_not_action_contract() -> None:
    messages = build_plan_messages("Reduce drawdown")
    assert "QuantAgentPlan" in messages[0]["content"]
    assert "Do not return an action decision" in messages[0]["content"]
    assert "objective_summary" in messages[1]["content"]
