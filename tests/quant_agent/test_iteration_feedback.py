from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.contracts.quant import (
    QuantAgentAction,
    QuantAgentBudget,
    QuantAgentCandidateContext,
    QuantAgentComparisonContext,
    QuantAgentContext,
    QuantArtifactKind,
    QuantEvidenceReplanDecision,
    QuantIterationFeedback,
    QuantRefinementSeedContext,
    QuantResearchDecision,
    QuantResearchDecisionDeviation,
    QuantResearchSeriesDecision,
    QuantRunState,
)
from packages.domain.canonical import canonical_digest
from services.api.app.db.models import QuantRepositoryState
from services.api.app.db.session import get_session_factory, set_rls_context
from services.api.app.modules.quant.store import (
    EVIDENCE_REPLAN_REPOSITORY_PREFIX,
    LEGACY_EVIDENCE_REPLAN_REPOSITORY_MARKER,
    QuantFixtureLease,
    QuantStore,
)
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.context_builder import QuantAgentContextBuilder
from services.worker.app.quant_agent.prompt import build_decision_messages
from services.worker.app.quant_agent.provider import MockQuantAgentProvider
from services.worker.app.quant_agent.runner import QuantAgentRunner
from services.worker.app.quant_agent.tool_registry import QuantToolRegistry


def _feedback_payload() -> dict[str, object]:
    candidate = {
        "candidate_id": "candidate-1",
        "name": "SMA 20/100",
        "template": "sma_crossover",
        "parameters": {"fast_window": 20, "slow_window": 100},
        "canonical_key": "sha256:candidate-1",
        "metrics": {
            "total_return_pct": 5.0,
            "annualized_return_pct": 14.0,
            "maximum_drawdown_pct": -5.0,
            "sharpe_ratio": 1.1,
            "trade_count": 8,
            "win_rate_pct": 50.0,
            "final_equity": 10500.0,
        },
        "deltas": {
            "return_difference": 0.8,
            "drawdown_difference": 2.1,
            "sharpe_difference": 0.2,
            "trade_count_difference": 7,
        },
        "walk_forward": {
            "status": "completed",
            "evaluated_folds": 3,
            "candidate_positive_return_folds": 2,
            "candidate_lower_drawdown_folds": 2,
            "candidate_median_return_pct": 1.2,
            "benchmark_median_return_pct": 0.8,
            "candidate_median_drawdown_pct": -2.3,
            "benchmark_median_drawdown_pct": -3.1,
            "candidate_median_sharpe_ratio": 1.0,
            "benchmark_median_sharpe_ratio": 0.6,
            "distinct_market_regimes": 2,
            "regime_diversity_status": "covered",
        },
    }
    second = {
        **candidate,
        "candidate_id": "candidate-2",
        "name": "SMA 50/200",
        "canonical_key": "sha256:candidate-2",
    }
    return {
        "schema_version": "quant-iteration-feedback-v1",
        "round": 1,
        "comparison_artifact_id": "comparison-1",
        "evaluation_partition": "train",
        "training_split": {
            "rule_version": "chronological-80-20-v1",
            "train_bar_count": 80,
            "train_start": "2024-01-01",
            "train_end": "2024-03-20",
        },
        "benchmark": {
            "total_return_pct": 4.2,
            "annualized_return_pct": 12.5,
            "maximum_drawdown_pct": -7.1,
            "sharpe_ratio": 0.9,
            "trade_count": 1,
            "win_rate_pct": 100.0,
            "final_equity": 10420.0,
        },
        "completed_candidates": [candidate, second],
        "remaining_budget": {"experiments": 1, "iterations": 5},
        "novelty": {
            "exact_dedupe_rule": "template_parameters_canonical_v1",
            "tested_candidate_keys": ["sha256:candidate-1", "sha256:candidate-2"],
        },
        "improvement_reference": {
            "candidate_id": "candidate-1",
            "canonical_key": "sha256:candidate-1",
            "selection_rule": "highest_sharpe_then_return_then_drawdown",
        },
        "stop_signal": {
            "code": "continue_train_only_iteration",
            "reason": "One experiment slot remains after a train-only comparison.",
        },
    }


def _context(*, feedback: QuantIterationFeedback | None = None) -> QuantAgentContext:
    return QuantAgentContext(
        run_id="run-1",
        project_id="project-1",
        research_goal="Improve drawdown with an interpretable rule.",
        mode="auto",
        run_state="running_experiments",
        dataset_summary={},
        benchmark_summary=None,
        available_templates=[],
        candidates=[],
        budget=QuantAgentBudget(
            max_iterations=8,
            used_iterations=2,
            remaining_iterations=6,
            max_experiments=3,
            used_experiments=2,
            remaining_experiments=1,
            max_repairs=2,
            used_repairs=0,
            remaining_repairs=2,
        ),
        recent_events=[],
        recent_observations=[],
        plan_summary=None,
        final_conclusion=None,
        iteration_feedback=feedback,
    )


def _candidate_replan_decision(
    feedback_artifact: Any,
    *,
    template: str,
) -> QuantEvidenceReplanDecision:
    feedback = QuantIterationFeedback.model_validate(feedback_artifact.content)
    reference = next(
        item
        for item in feedback.completed_candidates
        if item.candidate_id == feedback.improvement_reference.candidate_id
    )
    return QuantEvidenceReplanDecision(
        action=(
            "refine_parameters" if template == reference.template else "switch_approved_family"
        ),
        source_comparison_artifact_id=feedback.comparison_artifact_id,
        improvement_reference_candidate_id=reference.candidate_id,
    )


def test_refinement_seed_contract_is_closed_and_excludes_evaluation_evidence() -> None:
    payload = {
        "parent_run_id": "parent-1",
        "seed_candidate_id": "candidate-1",
        "refinement_reason": "Test a slower trend filter.",
        "source_research_goal": "Reduce drawdown.",
        "seed_candidate": {
            "name": "SMA 20/100",
            "template": "sma_crossover",
            "parameters": {"fast_window": 20, "slow_window": 100},
        },
    }
    parsed = QuantRefinementSeedContext.model_validate(payload)
    assert parsed.seed_candidate.template == "sma_crossover"
    for forbidden in ("metrics", "validation", "generalization", "holdout", "recommendation"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            QuantRefinementSeedContext.model_validate({**payload, forbidden: {}})
    seed_candidate = cast(dict[str, object], payload["seed_candidate"])
    nested_metrics = {**payload, "seed_candidate": {**seed_candidate, "metrics": {}}}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QuantRefinementSeedContext.model_validate(nested_metrics)


def test_iteration_feedback_contract_is_closed_and_train_only() -> None:
    feedback = QuantIterationFeedback.model_validate(_feedback_payload())
    assert feedback.evaluation_partition == "train"
    for forbidden in ("holdout", "generalization", "validation"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            QuantIterationFeedback.model_validate({**_feedback_payload(), forbidden: {}})
    invalid_folds = _feedback_payload()
    candidate = invalid_folds["completed_candidates"][0]  # type: ignore[index]
    candidate["walk_forward"]["folds"] = []  # type: ignore[index]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QuantIterationFeedback.model_validate(invalid_folds)


def test_feedback_is_serialized_to_the_provider_payload_without_a_new_tool() -> None:
    feedback = QuantIterationFeedback.model_validate(_feedback_payload())
    message = build_decision_messages(_context(feedback=feedback))[1]
    assert "iteration_feedback" in message["content"]
    assert "comparison-1" in message["content"]
    assert len(QuantToolRegistry().manifest["tools"]) == 7


def test_mock_requires_comparison_before_third_candidate_and_uses_feedback_for_c() -> None:
    candidates = [
        QuantAgentCandidateContext(
            candidate_id=f"candidate-{index}",
            name=name,
            template="sma_crossover",
            hypothesis="Bounded trend test.",
            parameters=cast(dict[str, int | float | str | bool], parameters),
            state="completed",
            repair_count=0,
            verdict="viable",
            metrics={"sharpe_ratio": 1.0},
            latest_observation="Backtest completed.",
        )
        for index, (name, parameters) in enumerate(
            (
                ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
                ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
            ),
            start=1,
        )
    ]
    context = _context().model_copy(
        update={
            "candidates": candidates,
            "recent_observations": [
                {"action": "inspect_research_context", "success": True},
                {"action": "list_strategy_templates", "success": True},
            ],
        }
    )
    provider = MockQuantAgentProvider()
    assert provider.decide(context).action is QuantAgentAction.COMPARE_CANDIDATES

    feedback = QuantIterationFeedback.model_validate(_feedback_payload())
    feedback_context = context.model_copy(update={"iteration_feedback": feedback})
    decision = provider.decide(feedback_context)

    assert decision.action is QuantAgentAction.CREATE_CANDIDATE
    assert "comparison-1" in str(decision.arguments["change_rationale"])
    assert (
        QuantStore.canonical_candidate_key(
            str(decision.arguments["template"]),
            cast(dict[str, Any], decision.arguments["parameters"]),
        )
        not in feedback.novelty.tested_candidate_keys
    )

    reserve_context = feedback_context.model_copy(
        update={
            "budget": feedback_context.budget.model_copy(
                update={"remaining_iterations": 2, "used_iterations": 10}
            ),
            "latest_comparison": QuantAgentComparisonContext(
                artifact_id="comparison-1",
                candidate_ids=["candidate-1", "candidate-2"],
                ranking=["candidate-1", "candidate-2"],
            ),
        }
    )
    reserved = provider.decide(reserve_context)
    assert reserved.action is QuantAgentAction.FINISH_RESEARCH
    assert reserved.arguments["selected_candidate_id"] == "candidate-1"


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {principal_id}", "Idempotency-Key": str(uuid4())}
    if workspace_id:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _create_run(client: TestClient, principal_id: str) -> tuple[str, str]:
    workspace = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={
            "name": f"Iteration {uuid4().hex[:8]}",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert workspace.status_code == 201, workspace.text
    workspace_id = workspace.json()["workspace_id"]
    project = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Iteration contract", "objective": "Compare train-only candidates."},
    )
    assert project.status_code == 201, project.text
    run = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project.json()["id"],
            "mode": "auto",
            "question": "Compare train-only candidates.",
            "expected_project_row_version": project.json()["row_version"],
        },
    )
    assert run.status_code == 201, run.text
    return workspace_id, run.json()["id"]


def _prepare_a_b_feedback(
    client: TestClient, principal_id: str
) -> tuple[
    str,
    str,
    QuantStore,
    QuantFixtureLease,
    list[Any],
    Any,
    dict[str, Any],
]:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id=f"p18-{uuid4()}")
    assert lease is not None
    candidates = []
    for name, parameters in (
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template="sma_crossover",
            hypothesis="Create one bounded base candidate.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        candidates.append(candidate)
        store.get_run(
            workspace_id=workspace_id, run_id=run_id
        ).state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    comparison, _, error = store.compare_agent_candidates(lease)
    assert error is None and comparison is not None
    feedback = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.kind is QuantArtifactKind.ITERATION_FEEDBACK
    )
    return workspace_id, run_id, store, lease, candidates, feedback, comparison


def _complete_candidate(
    store: QuantStore,
    lease: QuantFixtureLease,
    *,
    name: str,
    template: str,
    fast_window: int,
    slow_window: int,
) -> Any:
    persisted_template = template
    backtest_template = "sma_crossover" if template == "fixture" else template
    candidate, _, error = store.create_agent_candidate(
        lease,
        name=name,
        template=backtest_template,
        hypothesis="Test a bounded trend filter.",
        parameters={"fast_window": fast_window, "slow_window": slow_window},
    )
    assert error is None and candidate is not None
    store.get_run(
        workspace_id=lease.workspace_id, run_id=lease.run_id
    ).state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    if persisted_template == "fixture":
        candidate.template = "fixture"
    return candidate


def test_compare_persists_one_train_only_feedback_and_context_reads_it(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.max_experiments = 3
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="iteration-feedback")
    assert lease is not None
    first, _, error = store.create_agent_candidate(
        lease,
        name="SMA 20/100",
        template="sma_crossover",
        hypothesis="Test an intermediate trend filter.",
        parameters={"fast_window": 20, "slow_window": 100},
    )
    assert error is None and first is not None
    store.get_run(
        workspace_id=workspace_id, run_id=run_id
    ).state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(lease, candidate_id=first.id)[2] is None
    assert store.compare_agent_candidates(lease)[2] is None
    assert not any(
        artifact.kind.value == "iteration_feedback"
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
    )
    second, _, error = store.create_agent_candidate(
        lease,
        name="SMA 50/200",
        template="sma_crossover",
        hypothesis="Test a slow trend filter.",
        parameters={"fast_window": 50, "slow_window": 200},
    )
    assert error is None and second is not None
    store.get_run(
        workspace_id=workspace_id, run_id=run_id
    ).state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(lease, candidate_id=second.id)[2] is None

    comparison, _, error = store.compare_agent_candidates(lease)
    assert error is None and comparison is not None
    feedbacks = [
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.kind.value == "iteration_feedback"
    ]
    assert len(feedbacks) == 1
    feedback = QuantIterationFeedback.model_validate(feedbacks[0].content)
    assert feedback.comparison_artifact_id
    assert feedback.evaluation_partition == "train"
    assert feedback.remaining_budget.experiments == 1
    assert len(feedback.completed_candidates) == 2
    assert all(
        "holdout" not in candidate.model_dump() for candidate in feedback.completed_candidates
    )

    reloaded = QuantStore()
    assert reloaded.compare_agent_candidates(lease)[2] is None
    assert (
        len(
            [
                artifact
                for artifact in reloaded.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
                if artifact.kind.value == "iteration_feedback"
            ]
        )
        == 1
    )
    typed_context = QuantAgentContextBuilder(reloaded).build(
        workspace_id=workspace_id, run_id=run_id
    )
    assert typed_context.iteration_feedback == feedback


def test_runner_preempts_provider_with_required_a_b_comparison(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="a-b-setup")
    assert lease is not None
    for name, parameters in (
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template="sma_crossover",
            hypothesis="Create one completed base candidate.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        store.get_run(
            workspace_id=workspace_id, run_id=run_id
        ).state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    store.release_agent_claim(lease)

    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.provider = "deepseek"
    store._persist_workspace(workspace_id)  # pyright: ignore[reportPrivateUsage]

    class _ProviderMustNotBeCalled:
        provider_name = "test"
        model_name: str | None = "test"
        calls = 0

        def decide(self, _context: QuantAgentContext) -> Any:
            self.calls += 1
            raise AssertionError("A/B comparison must preempt the provider")

    provider = _ProviderMustNotBeCalled()
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="a-b-preemption")
    assert claim is not None
    result = QuantAgentRunner(store=store, provider=cast(Any, provider)).run_step(claim=claim)

    assert result.did_work and not result.terminal
    assert provider.calls == 0
    artifacts = store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
    assert any(item.kind is QuantArtifactKind.ITERATION_FEEDBACK for item in artifacts)
    actions = [
        item["payload"]["action"]
        for item in store.events_for_run(workspace_id=workspace_id, run_id=run_id)
        if item["event_type"] == "agent.action_selected"
    ]
    assert actions[-1] == "compare_candidates"
    assert not any(
        item["event_type"] == "agent.decision_failed"
        for item in store.events_for_run(workspace_id=workspace_id, run_id=run_id)
    )


def test_third_candidate_requires_feedback_then_consumes_it_once(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="feedback-gate")
    assert lease is not None
    for name, parameters in (
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template="sma_crossover",
            hypothesis="Test a bounded trend filter.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        store.get_run(
            workspace_id=workspace_id, run_id=run_id
        ).state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None

    used_before = store.get_run(workspace_id=workspace_id, run_id=run_id).used_experiments
    artifacts_before = len(store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id))
    rejected, artifacts, error = store.create_agent_candidate(
        lease,
        name="Initial third candidate",
        template="breakout",
        hypothesis="This must wait for the comparison.",
        parameters={"lookback_window": 55},
    )
    assert rejected is None and artifacts == [] and error == "ITERATION_FEEDBACK_REQUIRED"
    assert store.get_run(workspace_id=workspace_id, run_id=run_id).used_experiments == used_before
    assert (
        len(store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)) == artifacts_before
    )

    assert store.compare_agent_candidates(lease)[2] is None
    feedback = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.kind.value == "iteration_feedback"
    )
    completed_before_iteration = store.experiments_for_run(workspace_id=workspace_id, run_id=run_id)
    state_before_early_finish = store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    report, artifact_ids, error = store.finish_agent_research(
        lease,
        selected_candidate_id=completed_before_iteration[0].id,
        conclusion="Do not finish before the feedback-driven candidate.",
        next_step="stop",
    )
    assert report is None and artifact_ids == []
    assert error == "ITERATION_CANDIDATE_REQUIRED"
    assert (
        store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        == state_before_early_finish
    )
    third, _, error = store.create_agent_candidate(
        lease,
        name="55-day breakout",
        template="breakout",
        hypothesis="Use the train-only comparison to test a distinct rule.",
        parameters={"lookback_window": 55},
        change_rationale="The retained train-only comparison identifies a distinct breakout test.",
        replan_decision=_candidate_replan_decision(feedback, template="breakout"),
    )
    assert error is None and third is not None
    assert third.feedback_artifact_id == feedback.id
    assert third.change_rationale is not None
    assert third.replan_decision is not None
    assert third.replan_decision.action == "switch_approved_family"
    reloaded_third = next(
        item
        for item in QuantStore().experiments_for_run(workspace_id=workspace_id, run_id=run_id)
        if item.id == third.id
    )
    assert reloaded_third.feedback_artifact_id == feedback.id
    assert reloaded_third.replan_decision == third.replan_decision
    store.get_run(
        workspace_id=workspace_id, run_id=run_id
    ).state = QuantRunState.RUNNING_EXPERIMENTS

    report, artifact_ids, error = store.finish_agent_research(
        lease,
        selected_candidate_id=completed_before_iteration[0].id,
        conclusion="Do not finish while the feedback-driven candidate is untested.",
        next_step="stop",
    )
    assert report is None and artifact_ids == []
    assert error == "ITERATION_CANDIDATE_REQUIRED"

    fourth, artifacts, error = store.create_agent_candidate(
        lease,
        name="A fourth candidate",
        template="breakout",
        hypothesis="This must not consume the same feedback twice.",
        parameters={"lookback_window": 80},
        change_rationale="Try another strategy.",
        replan_decision=_candidate_replan_decision(feedback, template="breakout"),
    )
    assert fourth is None and artifacts == []
    assert error == "EXPERIMENT_BUDGET_EXHAUSTED"

    assert store.run_agent_backtest(lease, candidate_id=third.id)[2] is None
    completed = store.experiments_for_run(workspace_id=workspace_id, run_id=run_id)
    report, _, error = store.finish_agent_research(
        lease,
        selected_candidate_id=completed[0].id,
        conclusion="A final comparison is required before holdout.",
        next_step="stop",
    )
    assert report is None and error == "FINAL_COMPARISON_REQUIRED"

    final_comparison, _, error = store.compare_agent_candidates(lease)
    assert error is None and final_comparison is not None
    assert len(final_comparison["candidates"]) == 3
    report, _, error = store.finish_agent_research(
        lease,
        selected_candidate_id=final_comparison["ranking"][0],
        conclusion="Finish only from the retained final comparison.",
        next_step="stop",
    )
    assert error is None and report is not None
    assert report["selected_candidate_id"] in final_comparison["ranking"]
    completed_state = store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    repeated_report, repeated_artifacts, repeated_error = store.finish_agent_research(
        lease,
        selected_candidate_id=report["selected_candidate_id"],
        conclusion="A repeated finish must not create another report or holdout.",
        next_step="stop",
    )
    assert repeated_report is None and repeated_artifacts == []
    assert repeated_error == "STALE_CLAIM"
    assert store._workspace_state(workspace_id) == completed_state  # pyright: ignore[reportPrivateUsage]
    assert (
        len(
            [
                artifact
                for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
                if artifact.kind.value == "research_report"
            ]
        )
        == 1
    )


def test_same_family_replan_requires_material_parameters_and_persists(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id, store, lease, _, feedback, _ = _prepare_a_b_feedback(client, principal_id)
    decision = _candidate_replan_decision(feedback, template="sma_crossover")
    assert decision.action == "refine_parameters"

    candidate, artifact_ids, error = store.create_agent_candidate(
        lease,
        name="SMA 15/80",
        template="sma_crossover",
        hypothesis="Refine the objective-leading family with distinct parameters.",
        parameters={"fast_window": 15, "slow_window": 80},
        change_rationale="Test one material same-family parameter change.",
        replan_decision=decision,
    )

    assert error is None and candidate is not None
    assert candidate.replan_decision == decision
    strategy = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.id in artifact_ids
    )
    assert strategy.content["replan_decision"] == decision.model_dump(mode="json")
    restored = next(
        item
        for item in QuantStore().experiments_for_run(workspace_id=workspace_id, run_id=run_id)
        if item.id == candidate.id
    )
    assert restored.replan_decision == decision


def test_invalid_replan_bindings_fail_before_any_mutation(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, _, store, lease, candidates, feedback_artifact, _ = _prepare_a_b_feedback(
        client, principal_id
    )
    feedback = QuantIterationFeedback.model_validate(feedback_artifact.content)
    reference_id = feedback.improvement_reference.candidate_id
    other_id = next(item.id for item in candidates if item.id != reference_id)
    attempts: list[tuple[str, dict[str, int | float], QuantEvidenceReplanDecision | None]] = [
        (
            "sma_crossover",
            {"fast_window": 15, "slow_window": 80},
            QuantEvidenceReplanDecision(
                action="refine_parameters",
                source_comparison_artifact_id="wrong-comparison",
                improvement_reference_candidate_id=reference_id,
            ),
        ),
        (
            "sma_crossover",
            {"fast_window": 16, "slow_window": 81},
            QuantEvidenceReplanDecision(
                action="refine_parameters",
                source_comparison_artifact_id=feedback.comparison_artifact_id,
                improvement_reference_candidate_id=other_id,
            ),
        ),
        (
            "sma_crossover",
            {"fast_window": 17, "slow_window": 82},
            QuantEvidenceReplanDecision(
                action="stop_insufficient_budget",
                source_comparison_artifact_id=feedback.comparison_artifact_id,
                improvement_reference_candidate_id=reference_id,
            ),
        ),
        (
            "breakout",
            {"lookback_window": 55},
            QuantEvidenceReplanDecision(
                action="refine_parameters",
                source_comparison_artifact_id=feedback.comparison_artifact_id,
                improvement_reference_candidate_id=reference_id,
            ),
        ),
        (
            "sma_crossover",
            {"fast_window": 18, "slow_window": 83},
            QuantEvidenceReplanDecision(
                action="switch_approved_family",
                source_comparison_artifact_id=feedback.comparison_artifact_id,
                improvement_reference_candidate_id=reference_id,
            ),
        ),
        ("sma_crossover", {"fast_window": 19, "slow_window": 84}, None),
        (
            candidates[0].template,
            cast(dict[str, int | float], candidates[0].parameters),
            QuantEvidenceReplanDecision(
                action="refine_parameters",
                source_comparison_artifact_id=feedback.comparison_artifact_id,
                improvement_reference_candidate_id=reference_id,
            ),
        ),
    ]
    for index, (template, parameters, decision) in enumerate(attempts):
        baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        candidate, artifact_ids, error = store.create_agent_candidate(
            lease,
            name=f"Rejected P18 candidate {index}",
            template=template,
            hypothesis="This invalid replan must not mutate the Run.",
            parameters=parameters,
            change_rationale="A rationale cannot replace the typed decision.",
            replan_decision=decision,
        )
        assert candidate is None and artifact_ids == [] and error is not None
        assert (
            store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
            == baseline
        )


@pytest.mark.parametrize("stop_action", ["stop_insufficient_budget", "stop_no_novel_candidate"])
def test_structured_stop_finishes_from_fresh_a_b_without_candidate_c(
    client: TestClient,
    principal_id: str,
    stop_action: str,
) -> None:
    workspace_id, run_id, store, lease, candidates, feedback_artifact, comparison = (
        _prepare_a_b_feedback(client, principal_id)
    )
    feedback = QuantIterationFeedback.model_validate(feedback_artifact.content)
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    decision_payload: dict[str, Any] = {
        "action": stop_action,
        "source_comparison_artifact_id": feedback.comparison_artifact_id,
        "improvement_reference_candidate_id": feedback.improvement_reference.candidate_id,
    }
    if stop_action == "stop_insufficient_budget":
        run.max_agent_iterations = run.agent_iteration + 3
    else:
        decision_payload.update(
            {
                "proposed_template": candidates[0].template,
                "proposed_parameters": candidates[0].parameters,
            }
        )
    decision = QuantEvidenceReplanDecision.model_validate(decision_payload)

    report, artifact_ids, error = store.finish_agent_research(
        lease,
        selected_candidate_id=comparison["ranking"][0],
        conclusion="Do not claim an experiment that did not run.",
        next_step="stop",
        replan_decision=decision,
    )

    assert error is None and report is not None
    assert len(report["candidates_tested"]) == 2
    assert {item["candidate_id"] for item in report["candidates_tested"]} == {
        item.id for item in candidates
    }
    assert report["replan_decision"] == decision.model_dump(mode="json")
    assert "no third candidate ran" in report["conclusion"].lower()
    assert report["generalization"]["status"] in {"pass", "fail", "inconclusive"}
    assert {
        store.get_artifact(workspace_id=workspace_id, artifact_id=artifact_id).kind
        for artifact_id in artifact_ids
    } == {
        QuantArtifactKind.ROBUSTNESS_SENSITIVITY,
        QuantArtifactKind.RESEARCH_REPORT,
    }
    assert (
        len(
            [
                item
                for item in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
                if item.kind is QuantArtifactKind.RESEARCH_REPORT
            ]
        )
        == 1
    )
    restored_report = next(
        item
        for item in QuantStore().artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if item.kind is QuantArtifactKind.RESEARCH_REPORT
    )
    assert restored_report.content["replan_decision"] == decision.model_dump(mode="json")
    snapshot_response = client.get(
        f"/v1/quant/runs/{run_id}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot_response.status_code == 200, snapshot_response.text
    expected_reason = (
        "insufficient_action_budget"
        if stop_action == "stop_insufficient_budget"
        else "no_novel_candidate"
    )
    assert snapshot_response.json()["report"]["iterationStop"] == {
        "reason": expected_reason,
        "referenceCandidateId": feedback.improvement_reference.candidate_id,
    }


def test_structured_stop_restores_a_valid_p19_override_selection(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, run_id, store, lease, candidates, feedback_artifact, comparison = (
        _prepare_a_b_feedback(client, principal_id)
    )
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    leader_id, selected_id = comparison["ranking"]
    comparison_artifact = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.id == feedback_artifact.content["comparison_artifact_id"]
    )
    selected_row = next(
        row
        for row in comparison_artifact.content["candidates"]
        if row["candidate_id"] == selected_id
    )
    for row in comparison_artifact.content["candidates"]:
        for fold in row["walk_forward"]["folds"]:
            fold["status"] = "pass" if row["candidate_id"] == selected_id else "fail"
    comparison_artifact.digest = canonical_digest(comparison_artifact.content)
    selected = next(candidate for candidate in candidates if candidate.id == selected_id)
    selected_spec = store._strategy_spec(  # pyright: ignore[reportPrivateUsage]
        selected.template, selected.parameters
    )
    original_walk_forward = store._walk_forward_candidate  # pyright: ignore[reportPrivateUsage]

    def retained_walk_forward(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if args[1] == selected_spec:
            return deepcopy(selected_row["walk_forward"])
        return original_walk_forward(*args, **kwargs)

    monkeypatch.setattr(store, "_walk_forward_candidate", retained_walk_forward)
    run.max_agent_iterations = run.agent_iteration + 3
    stop_decision = QuantEvidenceReplanDecision(
        action="stop_insufficient_budget",
        source_comparison_artifact_id=feedback_artifact.content["comparison_artifact_id"],
        improvement_reference_candidate_id=feedback_artifact.content["improvement_reference"][
            "candidate_id"
        ],
    )
    research_decision = QuantResearchDecision(
        selected_candidate_id=selected_id,
        source_comparison_artifact_id=comparison_artifact.id,
        decision_basis="robustness_override",
        deviation=QuantResearchDecisionDeviation(
            reason="walk_forward_stability",
            reference_candidate_id=leader_id,
        ),
    )
    report, _, error = store.finish_agent_research(
        lease,
        selected_candidate_id=selected_id,
        conclusion="Retain the uniquely stable A/B candidate.",
        next_step="stop",
        replan_decision=stop_decision,
        research_decision=research_decision,
    )
    assert error is None and report is not None
    assert report["selected_candidate_id"] == selected_id
    restored_report = next(
        artifact
        for artifact in QuantStore().artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.kind is QuantArtifactKind.RESEARCH_REPORT
    )
    assert restored_report.content["selected_candidate_id"] == selected_id
    assert restored_report.content["research_decision"] == research_decision.model_dump(mode="json")
    snapshot_response = client.get(
        f"/v1/quant/runs/{run_id}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot_response.status_code == 200, snapshot_response.text
    assert snapshot_response.json()["report"]["selectionDecision"] == {
        "basis": "robustness_override",
        "selectedCandidateId": selected_id,
        "reason": "walk_forward_stability",
        "referenceCandidateId": leader_id,
    }
    assert (
        "sourceComparisonArtifactId" not in snapshot_response.json()["report"]["selectionDecision"]
    )


def test_structured_stop_rejects_conflicting_series_child_without_side_effects(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace_id, run_id, store, lease, candidates, feedback_artifact, comparison = (
        _prepare_a_b_feedback(client, principal_id)
    )
    feedback = QuantIterationFeedback.model_validate(feedback_artifact.content)
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.max_agent_iterations = run.agent_iteration + 3
    stop_decision = QuantEvidenceReplanDecision(
        action="stop_insufficient_budget",
        source_comparison_artifact_id=feedback.comparison_artifact_id,
        improvement_reference_candidate_id=feedback.improvement_reference.candidate_id,
    )
    series_decision = QuantResearchSeriesDecision(
        action="refine_selected",
        source_comparison_artifact_id=feedback.comparison_artifact_id,
        seed_candidate_id=comparison["ranking"][0],
        focus="improve_risk_adjusted_return",
        refinement_reason="This conflicting follow-up must be rejected at the store boundary.",
    )
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    report, artifact_ids, error = store.finish_agent_research(
        lease,
        selected_candidate_id=comparison["ranking"][0],
        conclusion="Stop without scheduling a child.",
        next_step="stop",
        series_decision=series_decision,
        replan_decision=stop_decision,
    )

    assert report is None and artifact_ids == []
    assert error == "ITERATION_STOP_SERIES_DECISION_CONFLICT"
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
    assert (
        store.get_run(workspace_id=workspace_id, run_id=run_id).research_series_child_run_id is None
    )
    assert {item.id for item in candidates} == {
        item.id for item in store.experiments_for_run(workspace_id=workspace_id, run_id=run_id)
    }


def test_pre_p18_feedback_candidate_restores_then_seals_repository_boundary(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace_id, run_id, store, lease, _, feedback, _ = _prepare_a_b_feedback(client, principal_id)
    third, _, error = store.create_agent_candidate(
        lease,
        name="55-day breakout",
        template="breakout",
        hypothesis="Exercise the retained pre-P18 feedback lineage.",
        parameters={"lookback_window": 55},
        change_rationale="Use the train-only comparison to test a distinct family.",
        replan_decision=_candidate_replan_decision(feedback, template="breakout"),
    )
    assert error is None and third is not None
    store.get_run(
        workspace_id=workspace_id, run_id=run_id
    ).state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(lease, candidate_id=third.id)[2] is None
    comparison, _, error = store.compare_agent_candidates(lease)
    assert error is None and comparison is not None
    report, _, error = store.finish_agent_research(
        lease,
        selected_candidate_id=comparison["ranking"][0],
        conclusion="Retain a genuine completed pre-P18 feedback-linked candidate.",
        next_step="stop",
    )
    assert error is None and report is not None

    legacy_state = deepcopy(
        store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    )
    legacy_candidate = next(item for item in legacy_state["experiments"] if item["id"] == third.id)
    legacy_candidate["replan_decision"] = None
    legacy_strategy = next(
        item
        for item in legacy_state["artifacts"]
        if item["kind"] == "strategy_spec"
        and item["content"].get("feedback_artifact_id") == feedback.id
    )
    legacy_strategy["content"]["replan_decision"] = None
    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p18-legacy-boundary-setup")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        row.state_json = legacy_state
        row.evidence_replan_contract_marker = LEGACY_EVIDENCE_REPLAN_REPOSITORY_MARKER
        row.row_version += 1
        db.commit()

    restored_store = QuantStore()
    restored = next(
        item
        for item in restored_store.experiments_for_run(workspace_id=workspace_id, run_id=run_id)
        if item.id == third.id
    )
    assert restored.feedback_artifact_id == feedback.id
    assert restored.replan_decision is None
    assert any(
        item.kind is QuantArtifactKind.RESEARCH_REPORT
        for item in restored_store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
    )
    restored_store._persist_workspace(workspace_id)  # pyright: ignore[reportPrivateUsage]
    with get_session_factory()() as db:
        set_rls_context(db, workspace_id, "p18-legacy-boundary-sealed")
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None
        assert row.evidence_replan_contract_marker.startswith(EVIDENCE_REPLAN_REPOSITORY_PREFIX)
        row.evidence_replan_contract_marker = f"{EVIDENCE_REPLAN_REPOSITORY_PREFIX}tampered"
        row.row_version += 1
        db.commit()

    tampered_store = QuantStore()
    baseline = tampered_store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    with pytest.raises(ValueError, match="does not match its repository marker"):
        tampered_store.get_run(workspace_id=workspace_id, run_id=run_id)
    assert (
        tampered_store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        == baseline
    )
    assert workspace_id not in tampered_store._loaded_workspaces  # pyright: ignore[reportPrivateUsage]


def test_strict_finish_rejects_one_completed_candidate_without_side_effects(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="one-candidate-gate")
    assert lease is not None
    candidate, _, error = store.create_agent_candidate(
        lease,
        name="SMA 20/100",
        template="sma_crossover",
        hypothesis="One candidate is insufficient for strict autonomous research.",
        parameters={"fast_window": 20, "slow_window": 100},
    )
    assert error is None and candidate is not None
    store.get_run(
        workspace_id=workspace_id, run_id=run_id
    ).state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    assert store.compare_agent_candidates(lease)[2] is None
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    report, artifact_ids, error = store.finish_agent_research(
        lease,
        selected_candidate_id=candidate.id,
        conclusion="Do not finish a single-candidate run.",
        next_step="stop",
    )

    assert report is None and artifact_ids == []
    assert error == "ITERATION_BASE_CANDIDATES_REQUIRED"
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]


def test_failed_feedback_candidate_cannot_produce_holdout_or_report(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="failed-c-gate")
    assert lease is not None
    base_candidates = []
    for name, parameters in (
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template="sma_crossover",
            hypothesis="Create the two valid base candidates.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        base_candidates.append(candidate)
        store.get_run(
            workspace_id=workspace_id, run_id=run_id
        ).state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    assert store.compare_agent_candidates(lease)[2] is None
    failed, _, error = store.create_agent_candidate(
        lease,
        name="Invalid SMA",
        template="sma_crossover",
        hypothesis="An invalid feedback candidate must terminate honestly.",
        parameters={"fast_window": 100, "slow_window": 20},
        change_rationale="Exercise the bounded candidate-failure branch.",
        replan_decision=_candidate_replan_decision(
            next(
                artifact
                for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
                if artifact.kind is QuantArtifactKind.ITERATION_FEEDBACK
            ),
            template="sma_crossover",
        ),
    )
    assert error is None and failed is not None
    store.get_run(
        workspace_id=workspace_id, run_id=run_id
    ).state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(lease, candidate_id=failed.id)[2] == (
        "INVALID_STRATEGY_PARAMETERS"
    )
    assert store.compare_agent_candidates(lease)[2] is None
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    report, artifact_ids, error = store.finish_agent_research(
        lease,
        selected_candidate_id=base_candidates[0].id,
        conclusion="Do not promote a run whose iteration candidate failed.",
        next_step="stop",
    )

    assert report is None and artifact_ids == []
    assert error == "ITERATION_CANDIDATE_REQUIRED"
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
    assert not any(
        artifact.kind.value == "research_report"
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
    )
    store.release_agent_claim(lease)
    assert run_quant_agent_once(
        store=store,
        provider=MockQuantAgentProvider(),
        workspace_id=workspace_id,
    )
    assert store.get_run(workspace_id=workspace_id, run_id=run_id).state is QuantRunState.FAILED
    assert not run_quant_agent_once(
        store=store,
        provider=MockQuantAgentProvider(),
        workspace_id=workspace_id,
    )


def test_canonical_candidate_and_feedback_lineage_tampering_fails_closed(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="canonical-gate")
    assert lease is not None
    base_candidates = []
    for name, parameters in (
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template="sma_crossover",
            hypothesis="Create a canonical base candidate.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        base_candidates.append(candidate)
        store.get_run(
            workspace_id=workspace_id, run_id=run_id
        ).state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    initial_comparison, initial_artifact_ids, error = store.compare_agent_candidates(lease)
    assert error is None and initial_comparison is not None
    feedback = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.kind is QuantArtifactKind.ITERATION_FEEDBACK
    )
    comparison_artifact_id = next(
        artifact_id for artifact_id in initial_artifact_ids if artifact_id != feedback.id
    )
    third, _, error = store.create_agent_candidate(
        lease,
        name="55-day breakout",
        template="breakout",
        hypothesis="Create one canonical feedback-linked candidate.",
        parameters={"lookback_window": 55},
        change_rationale="Use the retained comparison for a distinct candidate.",
        replan_decision=_candidate_replan_decision(feedback, template="breakout"),
    )
    assert error is None and third is not None
    store.get_run(
        workspace_id=workspace_id, run_id=run_id
    ).state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(lease, candidate_id=third.id)[2] is None
    final_comparison, _, error = store.compare_agent_candidates(lease)
    assert error is None and final_comparison is not None
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    def rows(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        base = next(item for item in state["experiments"] if item["id"] == base_candidates[0].id)
        iteration = next(item for item in state["experiments"] if item["id"] == third.id)
        feedback_row = next(item for item in state["artifacts"] if item["id"] == feedback.id)
        return base, iteration, feedback_row

    tampered_states: list[dict[str, Any]] = []
    copied_parameters = json.loads(json.dumps(baseline))
    base_row, iteration_row, _ = rows(copied_parameters)
    iteration_row["parameters"] = base_row["parameters"]
    tampered_states.append(copied_parameters)
    wrong_key = json.loads(json.dumps(baseline))
    rows(wrong_key)[1]["candidate_key"] = "sha256:tampered-candidate-key"
    tampered_states.append(wrong_key)
    wrong_kind = json.loads(json.dumps(baseline))
    rows(wrong_kind)[2]["kind"] = "validation_report"
    tampered_states.append(wrong_kind)
    wrong_run = json.loads(json.dumps(baseline))
    rows(wrong_run)[2]["run_id"] = str(uuid4())
    tampered_states.append(wrong_run)
    wrong_lineage_kind = json.loads(json.dumps(baseline))
    rows(wrong_lineage_kind)[1]["feedback_artifact_id"] = comparison_artifact_id
    tampered_states.append(wrong_lineage_kind)
    missing_lineage = json.loads(json.dumps(baseline))
    rows(missing_lineage)[1]["feedback_artifact_id"] = str(uuid4())
    tampered_states.append(missing_lineage)
    wrong_feedback_metrics = json.loads(json.dumps(baseline))
    feedback_content = rows(wrong_feedback_metrics)[2]["content"]
    feedback_content["completed_candidates"][0]["metrics"]["sharpe_ratio"] += 1
    tampered_states.append(wrong_feedback_metrics)
    wrong_reference = json.loads(json.dumps(baseline))
    reference_content = rows(wrong_reference)[2]["content"]
    current_reference_id = reference_content["improvement_reference"]["candidate_id"]
    alternate_reference = next(
        candidate for candidate in base_candidates if candidate.id != current_reference_id
    )
    reference_content["improvement_reference"] = {
        "candidate_id": alternate_reference.id,
        "canonical_key": alternate_reference.candidate_key,
        "selection_rule": "highest_sharpe_then_return_then_drawdown",
    }
    tampered_states.append(wrong_reference)

    guarded = QuantStore()
    guarded.get_run(workspace_id=workspace_id, run_id=run_id)
    guarded_baseline = guarded._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    for tampered in tampered_states:
        with pytest.raises(ValueError):
            guarded._restore_workspace(workspace_id, tampered)  # pyright: ignore[reportPrivateUsage]
        assert guarded._workspace_state(workspace_id) == guarded_baseline  # pyright: ignore[reportPrivateUsage]

    original_parameters = third.parameters
    third.parameters = base_candidates[0].parameters
    in_memory_tamper = store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    report, artifact_ids, error = store.finish_agent_research(
        lease,
        selected_candidate_id=final_comparison["ranking"][0],
        conclusion="Do not finish from a tampered canonical candidate.",
        next_step="stop",
    )
    assert report is None and artifact_ids == []
    assert error == "ITERATION_CANDIDATE_CANONICAL_IDENTITY_INVALID"
    assert store._workspace_state(workspace_id) == in_memory_tamper  # pyright: ignore[reportPrivateUsage]
    third.parameters = original_parameters

    original_kind = feedback.kind
    feedback.kind = QuantArtifactKind.VALIDATION_REPORT
    wrong_kind_baseline = store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    report, artifact_ids, error = store.finish_agent_research(
        lease,
        selected_candidate_id=final_comparison["ranking"][0],
        conclusion="Do not finish from a non-feedback lineage artifact.",
        next_step="stop",
    )
    assert report is None and artifact_ids == []
    assert error == "ITERATION_FEEDBACK_REQUIRED"
    assert store._workspace_state(workspace_id) == wrong_kind_baseline  # pyright: ignore[reportPrivateUsage]
    feedback.kind = original_kind
    assert QuantStore().get_run(workspace_id=workspace_id, run_id=run_id).id == run_id


@pytest.mark.parametrize(
    ("real_count", "fixture_count", "expect_feedback"),
    [(1, 1, False), (1, 2, False), (2, 0, True), (2, 1, True)],
)
def test_feedback_gate_ignores_fixture_candidates(
    client: TestClient,
    principal_id: str,
    real_count: int,
    fixture_count: int,
    expect_feedback: bool,
) -> None:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.max_experiments = max(3, real_count + fixture_count + 1)
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="fixture-gate")
    assert lease is not None
    templates = ["fixture"] * fixture_count + ["sma_crossover"] * real_count
    for index, template in enumerate(templates):
        _complete_candidate(
            store,
            lease,
            name=f"Candidate {index + 1}",
            template=template,
            fast_window=20 + index * 10,
            slow_window=100 + index * 20,
        )
    completed_records = [
        item
        for item in store.experiments_for_run(workspace_id=workspace_id, run_id=run_id)
        if item.state == "completed"
    ]
    comparison = {
        "split": {
            "rule_version": "chronological-80-20-v1",
            "train_bar_count": 80,
            "train_start": "2024-01-01",
            "train_end": "2024-03-20",
        },
        "benchmark": {
            "total_return_pct": 4.2,
            "annualized_return_pct": 12.5,
            "maximum_drawdown_pct": -7.1,
            "sharpe_ratio": 0.9,
            "trade_count": 1,
            "win_rate_pct": 100.0,
            "final_equity": 10420.0,
        },
        "ranking": [item.id for item in completed_records],
        "candidates": [
            {
                "candidate_id": item.id,
                "return_difference": 0.8,
                "drawdown_difference": 2.1,
                "sharpe_difference": 0.2,
                "trade_count_difference": 7,
                "walk_forward": {
                    "status": "completed",
                    "aggregate": {
                        "evaluated_folds": 3,
                        "candidate_positive_return_folds": 2,
                        "candidate_lower_drawdown_folds": 2,
                        "candidate_median_return_pct": 1.2,
                        "benchmark_median_return_pct": 0.8,
                        "candidate_median_drawdown_pct": -2.3,
                        "benchmark_median_drawdown_pct": -3.1,
                        "candidate_median_sharpe_ratio": 1.0,
                        "benchmark_median_sharpe_ratio": 0.6,
                        "distinct_market_regimes": 2,
                        "regime_diversity_status": "covered",
                    },
                },
            }
            for item in completed_records
        ],
    }
    artifact = cast(Any, store)._persist_iteration_feedback_if_eligible(
        run=store.get_run(workspace_id=workspace_id, run_id=run_id),
        completed=completed_records,
        comparison=comparison,
        comparison_artifact_id="comparison-1",
    )
    if not expect_feedback:
        assert artifact is None
        return
    assert artifact is not None
    feedback = QuantIterationFeedback.model_validate(artifact.content)
    assert all(candidate.template != "fixture" for candidate in feedback.completed_candidates)
    assert feedback.novelty.tested_candidate_keys == [
        candidate.canonical_key for candidate in feedback.completed_candidates
    ]


def test_feedback_requires_two_candidates_and_a_remaining_experiment_slot(
    client: TestClient, principal_id: str
) -> None:
    assert QuantStore.canonical_candidate_key(
        "sma_crossover", {"fast_window": 20, "slow_window": 100}
    ) == QuantStore.canonical_candidate_key(
        "sma_crossover", {"slow_window": 100, "fast_window": 20}
    )


def test_compare_with_no_completed_candidates_never_persists_feedback(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="no-feedback")
    assert lease is not None
    comparison, artifacts, error = store.compare_agent_candidates(lease)
    assert comparison is None
    assert artifacts == []
    assert error == "NO_COMPLETED_CANDIDATES"
    assert not any(
        artifact.kind.value == "iteration_feedback"
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
    )


def test_exhausted_experiment_budget_never_persists_feedback(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id = _create_run(client, principal_id)
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.max_experiments = 2
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="exhausted-feedback")
    assert lease is not None
    for name, parameters in (
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template="sma_crossover",
            hypothesis="Test a bounded trend filter.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        run.state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    assert store.compare_agent_candidates(lease)[2] is None
    assert not any(
        artifact.kind.value == "iteration_feedback"
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
    )
