from __future__ import annotations

import json
from typing import cast

import pytest
from pydantic import SecretStr

from packages.contracts.quant import (
    QuantAgentAction,
    QuantAgentBudget,
    QuantAgentCandidateContext,
    QuantAgentComparisonCandidateEvidence,
    QuantAgentComparisonContext,
    QuantAgentContext,
    QuantAgentDecision,
    QuantAgentPlan,
)
from services.worker.app.quant_agent.prompt import build_decision_messages, build_plan_messages
from services.worker.app.quant_agent.provider import (
    MockQuantAgentProvider,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    QuantAgentProviderError,
)
from services.worker.app.quant_agent.runner import QuantAgentRunner


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


@pytest.mark.parametrize(
    ("goal", "status", "families"),
    [
        ("Test an SMA crossover trend rule.", "supported", ["sma_crossover"]),
        ("Research RSI mean reversion.", "supported", ["rsi_mean_reversion"]),
        ("Test a 20-day breakout.", "supported", ["breakout"]),
        ("Use MACD with a volume filter.", "bounded_proxy", ["sma_crossover"]),
        ("Combine RSI with an SMA200 filter.", "bounded_proxy", ["rsi_mean_reversion"]),
        ("Test a breakout with an ATR stop.", "bounded_proxy", ["breakout"]),
        ("Run exact MACD with no proxy.", "unsupported", []),
        ("Build a long/short market-neutral strategy.", "unsupported", []),
        ("Use continuous sizing from signal strength.", "unsupported", []),
        ("Run multiasset ranking across a market universe.", "unsupported", []),
        ("Create a pairs trading strategy.", "unsupported", []),
        ("Train XGBoost on order-book features.", "unsupported", []),
    ],
)
def test_mock_plan_frozen_strategy_scope_probes(
    goal: str,
    status: str,
    families: list[str],
) -> None:
    plan = MockQuantAgentProvider().plan(goal)

    assert plan.strategy_scope.status == status
    assert plan.candidate_families == families
    if status == "supported":
        assert plan.strategy_scope.proxy_description is None
        assert plan.strategy_scope.excluded_behaviors == []
    elif status == "bounded_proxy":
        assert plan.strategy_scope.proxy_description
        assert plan.strategy_scope.excluded_behaviors
    else:
        assert plan.strategy_scope.proxy_description is None
        assert plan.strategy_scope.excluded_behaviors


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


def test_budget_finish_selects_a_completed_candidate_for_holdout() -> None:
    context = _context().model_copy(
        update={
            "candidates": [
                QuantAgentCandidateContext(
                    candidate_id="candidate-1",
                    name="Completed candidate",
                    template="sma_crossover",
                    hypothesis="Retain holdout evidence.",
                    parameters={"fast_window": 20, "slow_window": 100},
                    state="completed",
                    repair_count=0,
                    verdict="viable",
                    metrics={"maximum_drawdown_pct": -10.0},
                    latest_observation="Backtest completed.",
                )
            ],
            "latest_comparison": QuantAgentComparisonContext(
                artifact_id="comparison-1",
                candidate_ids=["candidate-1"],
                ranking=["candidate-1"],
            ),
        }
    )

    decision = QuantAgentRunner._budget_finish_decision(  # pyright: ignore[reportPrivateUsage]
        context
    )

    assert decision.arguments["selected_candidate_id"] == "candidate-1"


def test_budget_finish_requires_a_fresh_final_comparison() -> None:
    candidates = [
        QuantAgentCandidateContext(
            candidate_id=f"candidate-{index}",
            name=name,
            template="sma_crossover",
            hypothesis="Retain holdout evidence.",
            parameters=cast(dict[str, int | float | str | bool], parameters),
            state="completed",
            repair_count=0,
            verdict="viable",
            metrics={"sharpe_ratio": float(index), "total_return_pct": float(index)},
            latest_observation="Backtest completed.",
        )
        for index, (name, parameters) in enumerate(
            (
                ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
                ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
                ("200-day breakout", {"lookback_window": 200}),
            ),
            start=1,
        )
    ]
    stale = _context().model_copy(
        update={
            "candidates": candidates,
            "latest_comparison": QuantAgentComparisonContext(
                artifact_id="comparison-1",
                candidate_ids=["candidate-1", "candidate-2"],
                ranking=["candidate-1", "candidate-2"],
            ),
        }
    )
    missing = _context().model_copy(update={"candidates": candidates})
    fresh = _context().model_copy(
        update={
            "candidates": candidates,
            "latest_comparison": QuantAgentComparisonContext(
                artifact_id="comparison-2",
                candidate_ids=["candidate-1", "candidate-2", "candidate-3"],
                ranking=["candidate-2", "candidate-1", "candidate-3"],
            ),
        }
    )

    assert (
        QuantAgentRunner._budget_finish_decision(stale).action  # pyright: ignore[reportPrivateUsage]
        is QuantAgentAction.COMPARE_CANDIDATES
    )
    assert (
        QuantAgentRunner._budget_finish_decision(missing).action  # pyright: ignore[reportPrivateUsage]
        is QuantAgentAction.COMPARE_CANDIDATES
    )
    fresh_decision = QuantAgentRunner._budget_finish_decision(  # pyright: ignore[reportPrivateUsage]
        fresh
    )
    assert fresh_decision.action is QuantAgentAction.FINISH_RESEARCH
    assert fresh_decision.arguments["selected_candidate_id"] == "candidate-2"


def test_mock_and_budget_finish_preserve_supported_typed_override() -> None:
    candidates = [
        QuantAgentCandidateContext(
            candidate_id=f"candidate-{index}",
            name=f"Candidate {index}",
            template="sma_crossover",
            hypothesis="Use train-only robustness evidence.",
            parameters={"fast_window": 10 + index, "slow_window": 100 + index},
            state="completed",
            repair_count=0,
            verdict="viable",
            metrics={"trade_count": index},
            latest_observation="Backtest completed.",
        )
        for index in range(1, 4)
    ]
    comparison = QuantAgentComparisonContext(
        artifact_id="comparison-final",
        candidate_ids=[item.candidate_id for item in candidates],
        ranking=["candidate-1", "candidate-2", "candidate-3"],
        candidates=[
            QuantAgentComparisonCandidateEvidence(
                candidate_id="candidate-1",
                trade_count=3,
                walk_forward_pass_folds=1,
                pass_regime_labels=["trend"],
            ),
            QuantAgentComparisonCandidateEvidence(
                candidate_id="candidate-2",
                trade_count=2,
                walk_forward_pass_folds=3,
                pass_regime_labels=["trend", "high-vol"],
            ),
            QuantAgentComparisonCandidateEvidence(
                candidate_id="candidate-3",
                trade_count=1,
                walk_forward_pass_folds=0,
                pass_regime_labels=[],
            ),
        ],
    )
    context = _context().model_copy(
        update={
            "candidates": candidates,
            "latest_comparison": comparison,
            "budget": _context().budget.model_copy(
                update={"used_experiments": 3, "remaining_experiments": 0}
            ),
            "recent_observations": [
                {"action": "inspect_research_context", "success": True},
                {"action": "list_strategy_templates", "success": True},
            ],
        }
    )

    provider_decision = MockQuantAgentProvider().decide(context)
    budget_decision = QuantAgentRunner._budget_finish_decision(  # pyright: ignore[reportPrivateUsage]
        context
    )
    for decision in (provider_decision, budget_decision):
        assert decision.arguments["selected_candidate_id"] == "candidate-2"
        assert decision.arguments["research_decision"] == {
            "selected_candidate_id": "candidate-2",
            "source_comparison_artifact_id": "comparison-final",
            "decision_basis": "robustness_override",
            "deviation": {
                "reason": "walk_forward_stability",
                "reference_candidate_id": "candidate-1",
            },
        }


def test_budget_finish_requires_a_fresh_final_comparison_for_single_candidate() -> None:
    candidate = QuantAgentCandidateContext(
        candidate_id="candidate-1",
        name="SMA 50/200",
        template="sma_crossover",
        hypothesis="Retain holdout evidence.",
        parameters=cast(
            dict[str, int | float | str | bool],
            {"fast_window": 50, "slow_window": 200},
        ),
        state="completed",
        repair_count=0,
        verdict="viable",
        metrics={"sharpe_ratio": 1.0, "total_return_pct": 1.0},
        latest_observation="Backtest completed.",
    )
    missing = _context().model_copy(update={"candidates": [candidate]})
    fresh = _context().model_copy(
        update={
            "candidates": [candidate],
            "latest_comparison": QuantAgentComparisonContext(
                artifact_id="comparison-1",
                candidate_ids=["candidate-1"],
                ranking=["candidate-1"],
            ),
        }
    )

    assert (
        QuantAgentRunner._budget_finish_decision(missing).action  # pyright: ignore[reportPrivateUsage]
        is QuantAgentAction.COMPARE_CANDIDATES
    )
    assert (
        QuantAgentRunner._budget_finish_decision(fresh).action  # pyright: ignore[reportPrivateUsage]
        is QuantAgentAction.FINISH_RESEARCH
    )


def test_model_provider_rejects_invalid_decision_json() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(SecretStr("test-key"), "https://api.example.com", "test-model")
    )
    provider._complete = lambda _messages: "{}"  # type: ignore[method-assign]

    with pytest.raises(QuantAgentProviderError, match="closed validation"):
        provider.decide(_context())


def test_plan_prompt_uses_plan_contract_not_action_contract() -> None:
    messages = build_plan_messages("Reduce drawdown")
    assert "QuantAgentPlan" in messages[0]["content"]
    assert "Do not return an action decision" in messages[0]["content"]
    assert "max_experiments exactly 3" in messages[0]["content"]
    assert "exactly two initial candidates" in messages[0]["content"]
    assert "objective_summary" in messages[1]["content"]


def test_decision_prompt_carries_the_closed_schema_without_output_projections() -> None:
    payload = json.loads(build_decision_messages(_context())[1]["content"])

    assert payload["response_schema"]["title"] == "QuantAgentDecision"
    assert set(payload["format_example_only_do_not_copy_the_action"]) == {
        "action",
        "arguments",
        "decision_summary",
        "expected_result",
    }
    assert len(payload["tool_registry"]["tools"]) == 7
    assert all("output_schema" not in tool for tool in payload["tool_registry"]["tools"].values())


def test_decision_prompt_exposes_rejected_arguments_and_repair_instruction() -> None:
    rejected_arguments: dict[str, object] = {
        "name": "SMA 15/80",
        "template": "sma_crossover",
        "hypothesis": "Refine the leading family.",
        "parameters": {"fast_window": 15, "slow_window": 80},
        "change_rationale": "Test a tighter same-family parameter set.",
        "replan_decision": {
            "action": "switch_approved_family",
            "source_comparison_artifact_id": "comparison-1",
            "improvement_reference_candidate_id": "candidate-1",
        },
    }
    context = _context().model_copy(
        update={
            "recent_observations": [
                {
                    "action": "create_candidate",
                    "success": False,
                    "error_code": "INVALID_ARGUMENTS",
                    "call_fingerprint": "sha256:abc123",
                    "repair": {
                        "schema_version": "quant-tool-repair-v1",
                        "action": "create_candidate",
                        "call_fingerprint": "sha256:abc123",
                        "violations": [
                            {
                                "path": "replan_decision.action",
                                "required_change": "replace",
                                "allowed_values": ["refine_parameters"],
                                "rejected_value_fingerprint": "sha256:rejected",
                            }
                        ],
                    },
                    "rejected_arguments": rejected_arguments,
                },
                {"action": "inspect_research_context", "success": True},
            ]
        }
    )
    messages = build_decision_messages(context)
    system_prompt = messages[0]["content"]
    payload = json.loads(messages[1]["content"])

    assert "rejected_arguments" in system_prompt
    assert "copy" in system_prompt.lower()
    assert "only the path" in system_prompt.lower()
    failed_observation = next(
        item
        for item in payload["context"]["recent_observations"]
        if item["action"] == "create_candidate"
    )
    assert failed_observation["rejected_arguments"] == rejected_arguments
    success_observation = next(
        item
        for item in payload["context"]["recent_observations"]
        if item["action"] == "inspect_research_context"
    )
    assert "rejected_arguments" not in success_observation


def test_quant_provider_requests_bounded_non_thinking_json() -> None:
    captured: dict[str, object] = {}
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            SecretStr("test-key"),
            "https://api.example.com",
            "test-model",
            max_tokens=2_500,
        )
    )

    class RecordingTransport:
        def complete(self, request: dict[str, object]) -> dict[str, object]:
            captured.update(request)
            return {"choices": [{"message": {"content": "{}"}}]}

    provider._transport = RecordingTransport()  # type: ignore[assignment]

    assert provider._complete([{"role": "user", "content": "Return JSON."}]) == "{}"  # pyright: ignore[reportPrivateUsage]
    assert captured["thinking"] == {"type": "disabled"}
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["max_tokens"] == 2_500


def test_model_provider_repairs_contract_json_once() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            SecretStr("test-key"),
            "https://api.example.com",
            "test-model",
        )
    )
    valid = QuantAgentDecision(
        action=QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
        arguments={},
        decision_summary="Inspect the pinned research context.",
        expected_result="Return the authoritative dataset and budget.",
    ).model_dump_json()
    responses = iter(["{}", valid])
    message_batches: list[list[dict[str, str]]] = []

    def complete(messages: list[dict[str, str]]) -> str:
        message_batches.append(messages)
        return next(responses)

    provider._complete = complete  # type: ignore[method-assign]

    decision = provider.decide(_context())

    assert decision.action is QuantAgentAction.INSPECT_RESEARCH_CONTEXT
    assert len(message_batches) == 2
    repair = json.loads(message_batches[1][-1]["content"])
    assert repair["response_schema"]["title"] == "QuantAgentDecision"
    assert repair["validation_errors"]
    assert all("input" not in error for error in repair["validation_errors"])


def test_model_provider_stops_after_one_contract_repair() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            SecretStr("test-key"),
            "https://api.example.com",
            "test-model",
        )
    )
    calls = 0

    def complete(_messages: list[dict[str, str]]) -> str:
        nonlocal calls
        calls += 1
        return "{}"

    provider._complete = complete  # type: ignore[method-assign]

    with pytest.raises(QuantAgentProviderError, match="closed validation"):
        provider.decide(_context())
    assert calls == 2


def test_plan_retries_one_pre_run_transport_failure() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            SecretStr("test-key"),
            "https://api.example.com",
            "test-model",
        )
    )
    valid = MockQuantAgentProvider().plan("Reduce drawdown").model_dump_json()
    calls = 0

    def complete(_messages: list[dict[str, str]]) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise QuantAgentProviderError(
                "Provider request failed safely.",
                reason_code="transport_failed",
            )
        return valid

    provider._complete = complete  # type: ignore[method-assign]

    assert provider.plan("Reduce drawdown").max_experiments == 3
    assert calls == 2


def test_plan_retries_one_fresh_attempt_after_contract_repair_exhausts() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            SecretStr("test-key"),
            "https://api.example.com",
            "test-model",
        )
    )
    valid = MockQuantAgentProvider().plan("Reduce drawdown").model_dump_json()
    responses = iter(["{}", "{}", valid])
    calls = 0

    def complete(_messages: list[dict[str, str]]) -> str:
        nonlocal calls
        calls += 1
        return next(responses)

    provider._complete = complete  # type: ignore[method-assign]

    assert provider.plan("Reduce drawdown").max_experiments == 3
    assert calls == 3


def test_iteration_v1_plan_requires_three_experiments() -> None:
    plan = MockQuantAgentProvider().plan("Reduce drawdown")
    assert plan.max_experiments == 3

    with pytest.raises(ValueError, match="max_experiments"):
        QuantAgentPlan.model_validate({**plan.model_dump(), "max_experiments": 2})
