from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from packages.contracts.quant import (
    QuantAgentAction,
    QuantAgentDecision,
    QuantIterationFeedback,
    QuantResearchDecision,
    QuantToolObservation,
)
from packages.contracts.quant.enums import QuantRunState
from services.api.app.modules.quant.store import QuantFixtureLease, QuantStore
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.provider import MockQuantAgentProvider
from services.worker.app.quant_agent.runner import QuantAgentRunner
from services.worker.app.quant_agent.tool_registry import QuantToolRegistry


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _create_auto_run(
    client: TestClient, principal_id: str, goal: str
) -> tuple[str, dict[str, Any]]:
    workspace_response = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={
            "name": f"Agent {uuid4().hex[:8]}",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert workspace_response.status_code == 201
    workspace_id = workspace_response.json()["workspace_id"]
    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Autonomous research", "objective": goal},
    )
    assert project_response.status_code == 201
    project = project_response.json()
    run_response = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "mode": "auto",
            "question": goal,
            "expected_project_row_version": project["row_version"],
        },
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    assert run["state"] == "running_experiments"
    assert run["agent_iteration"] == 0
    return workspace_id, run


def _finish(workspace_id: str, maximum_polls: int = 15) -> QuantStore:
    for _ in range(maximum_polls):
        if not run_quant_agent_once(workspace_id=workspace_id):
            break
        store = QuantStore()
        run = store.list_runs(workspace_id=workspace_id)[0]
        if run.state.value in {"completed", "failed", "cancelled"}:
            return store
    return QuantStore()


def test_mock_agent_executes_one_action_per_poll_and_finishes(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Find a simple strategy that reduces maximum drawdown compared with buy and hold.",
    )
    store = QuantStore()
    before = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert run_quant_agent_once(workspace_id=workspace_id)
    after_store = QuantStore()
    after = after_store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert after.agent_iteration == before.agent_iteration + 1
    first_types = [
        item["event_type"]
        for item in after_store.events_for_run(workspace_id=workspace_id, run_id=created["id"])
    ]
    assert first_types[-2:] == ["tool.started", "tool.completed"]

    completed_store = _finish(workspace_id)
    completed = completed_store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert completed.state.value == "completed"
    assert completed.agent_iteration <= completed.max_agent_iterations
    experiments = completed_store.experiments_for_run(
        workspace_id=workspace_id, run_id=created["id"]
    )
    assert [item.name for item in experiments] == [
        "SMA 50/200",
        "SMA 20/100",
        "200-day breakout",
    ]
    experiment_states = [(item.state, bool(item.metrics)) for item in experiments]
    assert experiment_states == [("completed", True)] * 3
    assert all("fixture" not in json.dumps(item.metrics).lower() for item in experiments)
    artifacts = completed_store.artifacts_for_run(workspace_id=workspace_id, run_id=created["id"])
    assert any(item.kind.value == "research_report" for item in artifacts)
    comparisons = [
        item
        for item in artifacts
        if item.kind.value == "validation_report"
        and item.content.get("evaluation_partition") == "train"
    ]
    assert len(comparisons) == 2
    assert comparisons[-1].content["selection_objective"] == "drawdown_control"
    assert comparisons[-1].content["ranking"]
    assert {item["candidate_id"] for item in comparisons[-1].content["candidates"]} == {
        item.id for item in experiments
    }
    expected_ranking = [
        item["candidate_id"]
        for item in sorted(
            comparisons[-1].content["candidates"],
            key=lambda item: (
                int(item["trade_count"]) > 0,
                float(item["maximum_drawdown_pct"]),
                float(item["sharpe_ratio"]),
                float(item["total_return_pct"]),
                str(item["candidate_id"]),
            ),
            reverse=True,
        )
    ]
    assert comparisons[-1].content["ranking"] == expected_ranking
    feedback = next(item for item in artifacts if item.kind.value == "iteration_feedback")
    assert feedback.content["improvement_reference"]["selection_rule"] == "drawdown_control"
    report = next(item for item in artifacts if item.kind.value == "research_report")
    assert report.content["selected_candidate_id"] == comparisons[-1].content["ranking"][0]
    snapshot_response = client.get(
        f"/v1/quant/runs/{completed.id}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot_report = snapshot_response.json()["report"]
    research_decision = QuantResearchDecision.model_validate(report.content["research_decision"])
    assert research_decision.decision_basis == "approved_objective_rank"
    assert snapshot_report["selectionDecision"] == {
        "basis": "approved_objective_rank",
        "selectedCandidateId": research_decision.selected_candidate_id,
    }
    assert "sourceComparisonArtifactId" not in snapshot_report["selectionDecision"]
    assert "iterationStop" not in snapshot_report
    actions = [
        item["payload"]["action"]
        for item in completed_store.events_for_run(workspace_id=workspace_id, run_id=created["id"])
        if item["event_type"] == "agent.action_selected"
    ]
    assert actions == [
        "inspect_research_context",
        "list_strategy_templates",
        "create_candidate",
        "run_backtest",
        "create_candidate",
        "run_backtest",
        "compare_candidates",
        "create_candidate",
        "run_backtest",
        "compare_candidates",
        "finish_research",
    ]


def test_approved_plan_is_in_agent_context_and_blocks_unplanned_candidate(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Find a simple trend strategy that reduces drawdown.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert run.planned_candidate_families == ["sma_crossover", "breakout"]
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    assert context["approved_plan"] == {
        "candidate_families": ["sma_crossover", "breakout"],
        "strategy_scope": {
            "schema_version": "quant-strategy-scope-v1",
            "status": "supported",
            "reason": "The request fits the registered long-or-cash strategy templates.",
            "proxy_description": None,
            "excluded_behaviors": [],
        },
        "selection_objective": "drawdown_control",
        "completion_criteria": [
            "Backtest every judged candidate with the local kernel.",
            "Compare completed candidates before selecting one.",
            "Retain a report even when no candidate meets the goal.",
        ],
    }
    snapshot_response = client.get(
        f"/v1/quant/runs/{run.id}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot_response.status_code == 200, snapshot_response.text
    assert snapshot_response.json()["researchPlan"] == {
        "objectiveSummary": run.plan_summary,
        "candidateFamilies": ["sma_crossover", "breakout"],
        "strategyScope": {
            "schemaVersion": "quant-strategy-scope-v1",
            "status": "supported",
            "reason": "The request fits the registered long-or-cash strategy templates.",
            "excludedBehaviors": [],
        },
        "selectionObjective": "drawdown_control",
        "completionCriteria": context["approved_plan"]["completion_criteria"],
    }

    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="plan-policy-test")
    assert claim is not None
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    candidate, artifact_ids, error = store.create_agent_candidate(
        claim,
        name="Unplanned RSI",
        template="rsi_mean_reversion",
        hypothesis="This family was not approved by the plan.",
        parameters={"period": 14, "entry_threshold": 30, "exit_threshold": 55},
    )

    assert candidate is None
    assert artifact_ids == []
    assert error == "CANDIDATE_OUTSIDE_APPROVED_PLAN"
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]


def test_plan_external_candidate_requires_template_and_parameter_repair_before_runner_executes(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Find a simple trend strategy that reduces drawdown.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert run.planned_candidate_families == ["sma_crossover", "breakout"]
    run.provider = "deepseek"
    rejected_parameters = {"period": 14, "entry_threshold": 30, "exit_threshold": 55}

    class TemplateOnlyRepairProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "Plan repair probe",
                    "template": ("rsi_mean_reversion" if self.calls == 1 else "sma_crossover"),
                    "hypothesis": "Test whether both coupled strategy fields are repaired.",
                    "parameters": rejected_parameters,
                },
                decision_summary="Submit a bounded candidate repair probe.",
                expected_result="The plan and parameter guards remain authoritative.",
            )

    provider = TemplateOnlyRepairProvider()
    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    pending = store.latest_invalid_tool_repair(workspace_id=workspace_id, run_id=run.id)
    assert pending is not None
    assert [item.path for item in pending.violations] == ["template", "parameters"]
    assert pending.violations[0].allowed_values == ["sma_crossover", "breakout"]
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run.id) == []

    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    failed = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert failed.state is QuantRunState.FAILED
    assert failed.failure_reason == (
        "The Agent did not apply the required contract repair before its next action."
    )
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run.id) == []
    events = store.events_for_run(workspace_id=workspace_id, run_id=run.id)
    assert (
        sum(
            item["event_type"] == "tool.started"
            and item["payload"].get("action") == "create_candidate"
            for item in events
        )
        == 1
    )
    assert any(
        item["event_type"] == "agent.decision_failed"
        and item["payload"].get("reason_code") == "agent_contract_repair_exhausted"
        for item in events
    )


def test_plan_external_candidate_repair_resolves_with_allowed_family_and_matching_parameters(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Find a simple trend strategy that reduces drawdown.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert run.planned_candidate_families == ["sma_crossover", "breakout"]
    run.provider = "deepseek"

    class CompletePlanRepairProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            outside_plan = self.calls == 1
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "Plan repair probe",
                    "template": "rsi_mean_reversion" if outside_plan else "breakout",
                    "hypothesis": "Test one repaired, plan-approved trend candidate.",
                    "parameters": (
                        {"period": 14, "entry_threshold": 30, "exit_threshold": 55}
                        if outside_plan
                        else {"lookback_window": 55}
                    ),
                },
                decision_summary="Repair both coupled strategy fields when required.",
                expected_result="Exactly one approved candidate is created.",
            )

    provider = CompletePlanRepairProvider()
    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run.id) == []
    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )

    current = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert current.state is QuantRunState.RUNNING_EXPERIMENTS
    candidates = store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    assert len(candidates) == 1
    assert candidates[0].template == "breakout"
    assert candidates[0].parameters == {"lookback_window": 55}
    assert store.latest_invalid_tool_repair(workspace_id=workspace_id, run_id=run.id) is None
    reloaded = QuantStore()
    assert reloaded.latest_invalid_tool_repair(workspace_id=workspace_id, run_id=run.id) is None
    persisted_candidates = reloaded.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    assert len(persisted_candidates) == 1
    assert persisted_candidates[0].template == "breakout"
    assert persisted_candidates[0].parameters == {"lookback_window": 55}
    learning_traces = [
        artifact
        for artifact in reloaded.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        if artifact.kind.value == "learning_trace"
    ]
    assert len(learning_traces) == 1
    assert learning_traces[0].content["outcome"] == "resolved"
    assert {item["path"] for item in learning_traces[0].content["correction_delta"]} == {
        "template",
        "parameters",
    }
    candidate_outcomes = [
        (item["event_type"], item["payload"].get("error_code"))
        for item in reloaded.events_for_run(workspace_id=workspace_id, run_id=run.id)
        if item["event_type"] in {"tool.completed", "tool.failed"}
        and item["payload"].get("action") == "create_candidate"
    ]
    assert candidate_outcomes == [
        ("tool.failed", "INVALID_ARGUMENTS"),
        ("tool.completed", None),
    ]
    resolved_context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    create_candidate_observations = [
        item
        for item in resolved_context["recent_observations"]
        if item["action"] == "create_candidate"
    ]
    assert len(create_candidate_observations) == 1
    assert create_candidate_observations[0]["success"] is True
    assert "rejected_arguments" not in create_candidate_observations[0]


def _prepare_a_b_feedback_with_reference(
    client: TestClient, principal_id: str
) -> tuple[
    str, str, QuantStore, QuantFixtureLease, list[Any], QuantIterationFeedback, dict[str, Any]
]:
    workspace_id, run_response = _create_auto_run(
        client, principal_id, "Find a simple trend strategy that reduces drawdown."
    )
    run_id = str(run_response["id"])
    store = QuantStore()
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id=f"replan-repair-{uuid4()}")
    assert lease is not None
    candidates: list[Any] = []
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
    feedback_artifact = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.kind.value == "iteration_feedback"
    )
    feedback = QuantIterationFeedback.model_validate(feedback_artifact.content)
    return workspace_id, run_id, store, lease, candidates, feedback, comparison


def test_replan_template_relation_invalid_persists_typed_repair(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id, store, lease, candidates, feedback, _ = (
        _prepare_a_b_feedback_with_reference(client, principal_id)
    )
    store.release_agent_claim(lease)
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.provider = "deepseek"

    class InvalidReplanActionProvider:
        def decide(self, _context: object) -> QuantAgentDecision:
            reference_id = feedback.improvement_reference.candidate_id
            comparison_id = feedback.comparison_artifact_id
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 15/80",
                    "template": "sma_crossover",
                    "hypothesis": "Refine the leading family.",
                    "parameters": {"fast_window": 15, "slow_window": 80},
                    "change_rationale": "Test a tighter same-family parameter set.",
                    "replan_decision": {
                        "action": "switch_approved_family",
                        "source_comparison_artifact_id": comparison_id,
                        "improvement_reference_candidate_id": reference_id,
                    },
                },
                decision_summary="Submit a same-family candidate with the wrong replan action.",
                expected_result="A typed action-only repair.",
            )

    provider = InvalidReplanActionProvider()
    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    pending = store.latest_invalid_tool_repair(workspace_id=workspace_id, run_id=run_id)
    assert pending is not None
    assert [item.path for item in pending.violations] == ["replan_decision.action"]
    assert pending.violations[0].allowed_values == ["refine_parameters"]
    assert pending.violations[0].required_change == "replace"
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run_id) == candidates
    events = store.events_for_run(workspace_id=workspace_id, run_id=run_id)
    assert (
        sum(
            item["event_type"] == "tool.started"
            and item["payload"].get("action") == "create_candidate"
            for item in events
        )
        == 1
    )


def test_replan_template_relation_context_exposes_rejected_arguments(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id, store, lease, candidates, feedback, comparison = (
        _prepare_a_b_feedback_with_reference(client, principal_id)
    )
    store.release_agent_claim(lease)
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.provider = "deepseek"
    reference_id = feedback.improvement_reference.candidate_id
    comparison_id = feedback.comparison_artifact_id
    rejected_arguments: dict[str, object] = {
        "name": "SMA 15/80",
        "template": "sma_crossover",
        "hypothesis": "Refine the leading family.",
        "parameters": {"fast_window": 15, "slow_window": 80},
        "change_rationale": "Test a tighter same-family parameter set.",
        "replan_decision": {
            "action": "switch_approved_family",
            "source_comparison_artifact_id": comparison_id,
            "improvement_reference_candidate_id": reference_id,
        },
    }

    class InvalidReplanActionProvider:
        def decide(self, _context: object) -> QuantAgentDecision:
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments=rejected_arguments,
                decision_summary="Submit a same-family candidate with the wrong replan action.",
                expected_result="A typed action-only repair.",
            )

    provider = InvalidReplanActionProvider()
    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run_id)
    failed_observation = next(
        item for item in context["recent_observations"] if item["action"] == "create_candidate"
    )
    assert failed_observation["error_code"] == "INVALID_ARGUMENTS"
    assert failed_observation["repair"]["schema_version"] == "quant-tool-repair-v1"
    assert [item["path"] for item in failed_observation["repair"]["violations"]] == [
        "replan_decision.action"
    ]
    assert failed_observation["rejected_arguments"] == rejected_arguments
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run_id) == candidates


def test_replan_template_relation_unchanged_correction_stops_pre_execution(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id, store, lease, candidates, feedback, _ = (
        _prepare_a_b_feedback_with_reference(client, principal_id)
    )
    store.release_agent_claim(lease)
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.provider = "deepseek"

    class RepeatedInvalidReplanActionProvider:
        def decide(self, _context: object) -> QuantAgentDecision:
            reference_id = feedback.improvement_reference.candidate_id
            comparison_id = feedback.comparison_artifact_id
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 15/80",
                    "template": "sma_crossover",
                    "hypothesis": "Refuse to change the replan action.",
                    "parameters": {"fast_window": 15, "slow_window": 80},
                    "change_rationale": "The action remains invalid.",
                    "replan_decision": {
                        "action": "switch_approved_family",
                        "source_comparison_artifact_id": comparison_id,
                        "improvement_reference_candidate_id": reference_id,
                    },
                },
                decision_summary="Repeat the same invalid replan action.",
                expected_result="The repair guard must stop this repeated call.",
            )

    provider = RepeatedInvalidReplanActionProvider()
    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run_id) == candidates

    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    failed = store.get_run(workspace_id=workspace_id, run_id=run_id)
    assert failed.state is QuantRunState.FAILED
    assert failed.failure_reason == (
        "The Agent did not apply the required contract repair before its next action."
    )
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run_id) == candidates
    events = store.events_for_run(workspace_id=workspace_id, run_id=run_id)
    assert (
        sum(
            item["event_type"] == "tool.started"
            and item["payload"].get("action") == "create_candidate"
            for item in events
        )
        == 1
    )
    assert any(
        item["event_type"] == "agent.decision_failed"
        and item["payload"].get("reason_code") == "agent_contract_repair_exhausted"
        for item in events
    )


def test_replan_template_relation_changed_candidate_fields_stop_pre_execution(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id, store, lease, candidates, feedback, _ = (
        _prepare_a_b_feedback_with_reference(client, principal_id)
    )
    store.release_agent_claim(lease)
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.provider = "deepseek"

    class ActionPlusTemplateChangeProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            reference_id = feedback.improvement_reference.candidate_id
            comparison_id = feedback.comparison_artifact_id
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 15/80" if self.calls == 1 else "55-day breakout",
                    "template": "sma_crossover" if self.calls == 1 else "breakout",
                    "hypothesis": (
                        "Same-family refinement." if self.calls == 1 else "Family switch."
                    ),
                    "parameters": (
                        {"fast_window": 15, "slow_window": 80}
                        if self.calls == 1
                        else {"lookback_window": 55}
                    ),
                    "change_rationale": "First call." if self.calls == 1 else "Second call.",
                    "replan_decision": {
                        "action": (
                            "switch_approved_family" if self.calls == 1 else "refine_parameters"
                        ),
                        "source_comparison_artifact_id": comparison_id,
                        "improvement_reference_candidate_id": reference_id,
                    },
                },
                decision_summary="Correct the action but also change the candidate proposal.",
                expected_result="The action-only repair guard stops this before execution.",
            )

    provider = ActionPlusTemplateChangeProvider()
    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run_id) == candidates

    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    failed = store.get_run(workspace_id=workspace_id, run_id=run_id)
    assert failed.state is QuantRunState.FAILED
    assert failed.failure_reason == (
        "The Agent did not apply the required contract repair before its next action."
    )
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run_id) == candidates
    events = store.events_for_run(workspace_id=workspace_id, run_id=run_id)
    assert (
        sum(
            item["event_type"] == "tool.started"
            and item["payload"].get("action") == "create_candidate"
            for item in events
        )
        == 1
    )
    assert any(
        item["event_type"] == "agent.decision_failed"
        and item["payload"].get("reason_code") == "agent_contract_repair_exhausted"
        for item in events
    )


def test_replan_template_relation_action_only_repair_creates_third_candidate_and_trace(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id, store, lease, candidates, feedback, _ = (
        _prepare_a_b_feedback_with_reference(client, principal_id)
    )
    store.release_agent_claim(lease)
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    run.provider = "deepseek"
    reference_id = feedback.improvement_reference.candidate_id
    comparison_id = feedback.comparison_artifact_id

    class CorrectedReplanActionProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 15/80",
                    "template": "sma_crossover",
                    "hypothesis": "Refine the leading family.",
                    "parameters": {"fast_window": 15, "slow_window": 80},
                    "change_rationale": "Test a tighter same-family parameter set.",
                    "replan_decision": {
                        "action": (
                            "switch_approved_family" if self.calls == 1 else "refine_parameters"
                        ),
                        "source_comparison_artifact_id": comparison_id,
                        "improvement_reference_candidate_id": reference_id,
                    },
                },
                decision_summary="First fail with wrong action, then correct only the action.",
                expected_result="One third candidate and one resolved learning trace.",
            )

    provider = CorrectedReplanActionProvider()
    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    assert len(store.experiments_for_run(workspace_id=workspace_id, run_id=run_id)) == len(
        candidates
    )
    assert store.latest_invalid_tool_repair(workspace_id=workspace_id, run_id=run_id) is not None

    assert run_quant_agent_once(  # type: ignore[arg-type]
        store=store, provider=provider, workspace_id=workspace_id
    )
    current = store.get_run(workspace_id=workspace_id, run_id=run_id)
    assert current.state is QuantRunState.RUNNING_EXPERIMENTS
    all_candidates = store.experiments_for_run(workspace_id=workspace_id, run_id=run_id)
    assert len(all_candidates) == len(candidates) + 1
    third = next(
        item
        for item in all_candidates
        if item.template == "sma_crossover"
        and item.parameters == {"fast_window": 15, "slow_window": 80}
    )
    assert third.replan_decision is not None
    assert third.replan_decision.action == "refine_parameters"
    assert store.latest_invalid_tool_repair(workspace_id=workspace_id, run_id=run_id) is None

    reloaded = QuantStore()
    assert reloaded.latest_invalid_tool_repair(workspace_id=workspace_id, run_id=run_id) is None
    persisted_candidates = reloaded.experiments_for_run(workspace_id=workspace_id, run_id=run_id)
    assert len(persisted_candidates) == len(candidates) + 1
    assert any(
        item.template == "sma_crossover"
        and item.parameters == {"fast_window": 15, "slow_window": 80}
        for item in persisted_candidates
    )
    learning_traces = [
        artifact
        for artifact in reloaded.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.kind.value == "learning_trace"
    ]
    assert len(learning_traces) == 1
    assert learning_traces[0].content["outcome"] == "resolved"
    assert {item["path"] for item in learning_traces[0].content["correction_delta"]} == {
        "replan_decision.action"
    }


def test_strategy_scope_gates_auto_execution_and_unsupported_approval(
    client: TestClient, principal_id: str
) -> None:
    def create_scoped_auto_run(goal: str) -> tuple[str, dict[str, Any]]:
        workspace_response = client.post(
            "/v1/workspaces",
            headers=_headers(principal_id),
            json={
                "name": f"Scope {uuid4().hex[:8]}",
                "data_region": "local",
                "retention_policy_version": "retention-v1",
            },
        )
        assert workspace_response.status_code == 201
        workspace_id = workspace_response.json()["workspace_id"]
        project_response = client.post(
            "/v1/quant/projects",
            headers=_headers(principal_id, workspace_id),
            json={"name": "Scoped research", "objective": goal},
        )
        assert project_response.status_code == 201
        project = project_response.json()
        run_response = client.post(
            "/v1/quant/runs",
            headers=_headers(principal_id, workspace_id),
            json={
                "project_id": project["id"],
                "mode": "auto",
                "question": goal,
                "expected_project_row_version": project["row_version"],
            },
        )
        assert run_response.status_code == 201, run_response.text
        return workspace_id, run_response.json()

    bounded_workspace, bounded = create_scoped_auto_run(
        "Use MACD with a volume filter to improve risk-adjusted return."
    )
    assert bounded["state"] == "waiting_plan_approval"
    bounded_snapshot = client.get(
        "/v1/quant/workspace-snapshot",
        headers=_headers(principal_id, bounded_workspace),
    )
    assert bounded_snapshot.status_code == 200
    assert bounded_snapshot.json()["researchPlan"]["strategyScope"]["status"] == "bounded_proxy"
    assert bounded_snapshot.json()["run"]["legalCommands"] == [
        "approve_plan",
        "request_plan_changes",
        "cancel_run",
    ]
    approved = client.post(
        f"/v1/quant/runs/{bounded['id']}/approve-plan",
        headers=_headers(principal_id, bounded_workspace),
        json={
            "expected_row_version": bounded["row_version"],
            "plan_revision": bounded["plan_revision"],
            "reason": "Approve the named bounded proxy.",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["state"] == "running_experiments"

    unsupported_workspace, unsupported = create_scoped_auto_run("Run exact MACD with no proxy.")
    assert unsupported["state"] == "waiting_plan_approval"
    store = QuantStore()
    unsupported_run = store.get_run(
        workspace_id=unsupported_workspace,
        run_id=unsupported["id"],
    )
    assert unsupported_run.strategy_scope.status == "unsupported"
    unsupported_snapshot = client.get(
        "/v1/quant/workspace-snapshot",
        headers=_headers(principal_id, unsupported_workspace),
    )
    assert unsupported_snapshot.status_code == 200
    snapshot = unsupported_snapshot.json()
    assert snapshot["researchPlan"]["candidateFamilies"] == []
    assert snapshot["researchPlan"]["strategyScope"]["status"] == "unsupported"
    assert "proxyDescription" not in snapshot["researchPlan"]["strategyScope"]
    assert snapshot["run"]["legalCommands"] == ["request_plan_changes", "cancel_run"]

    rejected_approval = client.post(
        f"/v1/quant/runs/{unsupported['id']}/approve-plan",
        headers=_headers(principal_id, unsupported_workspace),
        json={
            "expected_row_version": unsupported["row_version"],
            "plan_revision": unsupported["plan_revision"],
            "reason": "This must fail closed.",
        },
    )
    assert rejected_approval.status_code == 409
    restored = QuantStore()
    retained = restored.get_run(
        workspace_id=unsupported_workspace,
        run_id=unsupported["id"],
    )
    assert retained.state is QuantRunState.WAITING_PLAN_APPROVAL
    assert (
        restored.experiments_for_run(
            workspace_id=unsupported_workspace,
            run_id=retained.id,
        )
        == []
    )
    assert [
        artifact.kind.value
        for artifact in restored.artifacts_for_run(
            workspace_id=unsupported_workspace,
            run_id=retained.id,
        )
    ] == ["plan"]
    assert (
        restored.claim_agent_run(
            workspace_id=unsupported_workspace,
            worker_id="unsupported-scope-test",
        )
        is None
    )

    cancelled = client.post(
        f"/v1/quant/runs/{retained.id}/cancel",
        headers=_headers(principal_id, unsupported_workspace),
        json={
            "expected_row_version": retained.row_version,
            "reason": "Cancel the unsupported request.",
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    retry = client.post(
        f"/v1/quant/runs/{retained.id}/retry",
        headers=_headers(principal_id, unsupported_workspace),
        json={
            "expected_row_version": cancelled.json()["row_version"],
            "reason": "Verify the exact scope pin.",
        },
    )
    assert retry.status_code == 201, retry.text
    retry_run = QuantStore().get_run(
        workspace_id=unsupported_workspace,
        run_id=retry.json()["id"],
    )
    assert retry_run.state is QuantRunState.WAITING_PLAN_APPROVAL
    assert retry_run.strategy_scope.model_dump(mode="json") == retained.strategy_scope.model_dump(
        mode="json"
    )


def test_comparison_objectives_use_distinct_deterministic_rankings() -> None:
    rows = [
        {
            "candidate_id": "risk",
            "sharpe_ratio": 2.0,
            "total_return_pct": 5.0,
            "maximum_drawdown_pct": -20.0,
            "trade_count": 5,
        },
        {
            "candidate_id": "return",
            "sharpe_ratio": 1.0,
            "total_return_pct": 20.0,
            "maximum_drawdown_pct": -30.0,
            "trade_count": 5,
        },
        {
            "candidate_id": "drawdown",
            "sharpe_ratio": 0.5,
            "total_return_pct": 3.0,
            "maximum_drawdown_pct": -2.0,
            "trade_count": 5,
        },
    ]

    def ranking(objective: str) -> list[str]:
        return [
            str(row["candidate_id"])
            for row in sorted(
                rows,
                key=lambda row: cast(Any, QuantStore)._comparison_ranking_key(row, objective),
                reverse=True,
            )
        ]

    assert ranking("risk_adjusted_return") == ["risk", "return", "drawdown"]
    assert ranking("total_return") == ["return", "risk", "drawdown"]
    assert ranking("drawdown_control") == ["drawdown", "risk", "return"]

    exact_ties = [
        {
            "candidate_id": candidate_id,
            "sharpe_ratio": 1.0,
            "total_return_pct": 5.0,
            "maximum_drawdown_pct": -3.0,
            "trade_count": 2,
        }
        for candidate_id in ("candidate-a", "candidate-b")
    ]
    for objective in ("risk_adjusted_return", "total_return", "drawdown_control"):
        assert [
            str(row["candidate_id"])
            for row in sorted(
                exact_ties,
                key=lambda row: cast(Any, QuantStore)._comparison_ranking_key(row, objective),
                reverse=True,
            )
        ] == ["candidate-b", "candidate-a"]


def test_finish_rejects_non_leading_candidate_without_mutation(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Reduce maximum drawdown and finish from the approved objective.",
    )
    store = QuantStore()
    for _ in range(10):
        assert run_quant_agent_once(
            store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
        )

    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert run.state.value == "running_experiments"
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    ranking = context["latest_comparison"]["ranking"]
    assert len(ranking) == 3
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="objective-selection-gate")
    assert claim is not None
    baseline = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    report, artifact_ids, error = store.finish_agent_research(
        claim,
        selected_candidate_id=ranking[-1],
        conclusion="Do not allow the model to bypass the approved comparison objective.",
        next_step="stop",
    )

    assert report is None
    assert artifact_ids == []
    assert error == "FINAL_SELECTION_OBJECTIVE_MISMATCH"
    assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
    assert not any(
        artifact.kind.value == "research_report"
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
    )
    store.release_agent_claim(claim)


def test_restore_defaults_missing_legacy_selection_objective_and_rejects_unknown(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Compare candidates by risk-adjusted return.",
    )
    guarded = QuantStore()
    guarded.get_run(workspace_id=workspace_id, run_id=created["id"])
    baseline = guarded._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    unknown = json.loads(json.dumps(baseline))
    unknown_run = next(item for item in unknown["runs"] if item["id"] == created["id"])
    unknown_run["selection_objective"] = "model_decides_later"
    with pytest.raises(ValueError, match="invalid selection objective"):
        guarded._restore_workspace(workspace_id, unknown)  # pyright: ignore[reportPrivateUsage]
    assert guarded._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]

    artifact_unknown = json.loads(json.dumps(baseline))
    artifact_unknown_run = next(
        item for item in artifact_unknown["runs"] if item["id"] == created["id"]
    )
    artifact_unknown_plan = next(
        item
        for item in artifact_unknown["artifacts"]
        if item["id"] == artifact_unknown_run["plan_artifact_id"]
    )
    artifact_unknown_plan["content"]["selection_objective"] = "model_decides_later"
    with pytest.raises(ValueError, match="plan artifact has an invalid selection objective"):
        guarded._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, artifact_unknown
        )
    assert guarded._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]

    different_objective = next(
        objective
        for objective in ("risk_adjusted_return", "total_return", "drawdown_control")
        if objective != unknown_run["selection_objective"]
    )
    for field, value in (
        ("selection_objective", different_objective),
        ("candidate_families", ["breakout"]),
        ("completion_criteria", ["Use a different policy."]),
    ):
        mismatch = json.loads(json.dumps(baseline))
        mismatch_run = next(item for item in mismatch["runs"] if item["id"] == created["id"])
        mismatch_plan = next(
            item for item in mismatch["artifacts"] if item["id"] == mismatch_run["plan_artifact_id"]
        )
        mismatch_plan["content"][field] = value
        with pytest.raises(ValueError, match="executable policy.*not match"):
            guarded._restore_workspace(  # pyright: ignore[reportPrivateUsage]
                workspace_id, mismatch
            )
        assert (
            guarded._workspace_state(  # pyright: ignore[reportPrivateUsage]
                workspace_id
            )
            == baseline
        )

    artifact_missing_field = json.loads(json.dumps(baseline))
    missing_field_run = next(
        item for item in artifact_missing_field["runs"] if item["id"] == created["id"]
    )
    missing_field_plan = next(
        item
        for item in artifact_missing_field["artifacts"]
        if item["id"] == missing_field_run["plan_artifact_id"]
    )
    missing_field_plan["content"].pop("selection_objective")
    with pytest.raises(ValueError, match="executable policy fields do not match"):
        guarded._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, artifact_missing_field
        )
    assert guarded._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]

    missing_plan_artifact = json.loads(json.dumps(baseline))
    missing_plan_run = next(
        item for item in missing_plan_artifact["runs"] if item["id"] == created["id"]
    )
    missing_plan_artifact["artifacts"] = [
        item
        for item in missing_plan_artifact["artifacts"]
        if item["id"] != missing_plan_run["plan_artifact_id"]
    ]
    with pytest.raises(ValueError, match="plan artifact identity is invalid"):
        guarded._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, missing_plan_artifact
        )
    assert guarded._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]

    one_sided_scope = json.loads(json.dumps(baseline))
    one_sided_scope_run = next(
        item for item in one_sided_scope["runs"] if item["id"] == created["id"]
    )
    one_sided_scope_run.pop("strategy_scope")
    with pytest.raises(ValueError, match="strategy scope fields do not match"):
        guarded._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, one_sided_scope
        )
    assert guarded._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]

    legacy = json.loads(json.dumps(baseline))
    legacy_run = next(item for item in legacy["runs"] if item["id"] == created["id"])
    legacy_run.pop("selection_objective")
    legacy_run.pop("strategy_scope")
    plan_artifact = next(
        item for item in legacy["artifacts"] if item["id"] == legacy_run["plan_artifact_id"]
    )
    plan_artifact["content"].pop("selection_objective")
    plan_artifact["content"].pop("strategy_scope")
    guarded._restore_workspace(workspace_id, legacy)  # pyright: ignore[reportPrivateUsage]
    restored = guarded.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert restored.selection_objective == "risk_adjusted_return"
    assert restored.strategy_scope.model_dump(mode="json") == {
        "schema_version": "quant-strategy-scope-v1",
        "status": "supported",
        "reason": (
            "Legacy retained plan predates strategy-scope classification and is treated "
            "as supported."
        ),
        "proxy_description": None,
        "excluded_behaviors": [],
    }
    assert (
        guarded.agent_context_data(workspace_id=workspace_id, run_id=created["id"])[
            "approved_plan"
        ]["selection_objective"]
        == "risk_adjusted_return"
    )


def test_completed_third_candidate_uses_provider_for_final_selection(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Finish a three-candidate loop with a provider-owned final selection.",
    )
    store = QuantStore()
    for _ in range(9):
        assert run_quant_agent_once(
            store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
        )
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert run.used_experiments == run.max_experiments == 3
    assert all(
        item.state == "completed"
        for item in store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    )
    run.provider = "deepseek"

    class FinalSelectionProvider:
        calls = 0

        def decide(self, context: object) -> object:
            self.calls += 1
            return MockQuantAgentProvider().decide(context)  # type: ignore[arg-type]

    provider = FinalSelectionProvider()
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    completed = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert completed.state.value == "completed"
    assert provider.calls == 2
    actions = [
        item["payload"]["action"]
        for item in store.events_for_run(workspace_id=workspace_id, run_id=created["id"])
        if item["event_type"] == "agent.action_selected"
    ]
    assert actions[-2:] == ["compare_candidates", "finish_research"]
    events = store.events_for_run(workspace_id=workspace_id, run_id=created["id"])
    assert not any(
        item["event_type"] == "tool.failed" and item["payload"].get("action") == "create_candidate"
        for item in events
    )
    assert not any(item["event_type"] == "agent.decision_failed" for item in events)


@pytest.mark.parametrize(
    "invalid_fast_window",
    ["not-a-number", {"int": "bad"}],
    ids=["scalar", "dict-shaped-branch"],
)
def test_union_validation_repair_targets_real_field_and_accepts_numeric_fix(
    client: TestClient, principal_id: str, invalid_fast_window: object
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Repair one invalid strategy parameter type.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.provider = "deepseek"

    class NumericRepairProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            fast_window = invalid_fast_window if self.calls == 1 else 30
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 30/100",
                    "template": "sma_crossover",
                    "hypothesis": "Test a bounded trend candidate.",
                    "parameters": {"fast_window": fast_window, "slow_window": 100},
                },
                decision_summary="Repair the rejected numeric parameter when required.",
                expected_result="One valid strategy candidate.",
            )

    provider = NumericRepairProvider()
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    failed_observation = context["recent_observations"][0]
    assert failed_observation["error_code"] == "INVALID_ARGUMENTS"
    assert [item["path"] for item in failed_observation["repair"]["violations"]] == [
        "parameters.fast_window"
    ]

    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    current = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert current.state is QuantRunState.RUNNING_EXPERIMENTS
    assert current.agent_iteration == 2
    candidates = store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    assert len(candidates) == 1
    assert candidates[0].parameters == {"fast_window": 30, "slow_window": 100}


@pytest.mark.parametrize("tamper_kind", ["mismatched_fingerprint", "missing_repair"])
def test_restore_rejects_tampered_tool_repair_atomically(
    client: TestClient, principal_id: str, tamper_kind: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Retain one typed repair for restore validation.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.provider = "deepseek"

    class InvalidParameterProvider:
        def decide(self, _context: object) -> QuantAgentDecision:
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 30/100",
                    "template": "sma_crossover",
                    "hypothesis": "Test one bounded trend candidate.",
                    "parameters": {"fast_window": "not-a-number", "slow_window": 100},
                },
                decision_summary="Submit one invalid numeric parameter.",
                expected_result="A typed repair.",
            )

    assert run_quant_agent_once(
        store=store,
        provider=cast(Any, InvalidParameterProvider()),
        workspace_id=workspace_id,
    )
    guarded = QuantStore()
    guarded.get_run(workspace_id=workspace_id, run_id=run.id)
    baseline = deepcopy(guarded._workspace_state(workspace_id))  # pyright: ignore[reportPrivateUsage]
    tampered = deepcopy(baseline)
    tool_failure = next(
        item
        for item in reversed(tampered["events"])
        if item["event_type"] == "tool.failed" and item["payload"].get("tool_repair") is not None
    )
    if tamper_kind == "mismatched_fingerprint":
        tool_failure["payload"]["call_fingerprint"] = "sha256:tampered-tool-call"
    else:
        tool_failure["payload"]["tool_repair"] = None
    durable = store._durable_workspace_truth(workspace_id)  # pyright: ignore[reportPrivateUsage]
    assert durable.research_memory_contract_version is not None
    assert durable.evidence_replan_contract_marker is not None
    assert durable.research_decision_contract_marker is not None

    with pytest.raises(ValueError, match="repair|fingerprint"):
        guarded._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id,
            tampered,
            repository_memory_contract_version=durable.research_memory_contract_version,
            repository_replan_contract_marker=durable.evidence_replan_contract_marker,
            repository_research_decision_contract_marker=(
                durable.research_decision_contract_marker
            ),
        )
    assert (
        guarded._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        == baseline
    )


@pytest.mark.parametrize("failure_timing", ["precommit", "postcommit"])
def test_repair_exhaustion_reconciles_persistence_failures(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
    failure_timing: str,
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        f"Reconcile a {failure_timing} repair-exhaustion write failure.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.provider = "deepseek"

    class RepeatedInvalidParameterProvider:
        def decide(self, _context: object) -> QuantAgentDecision:
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 30/100",
                    "template": "sma_crossover",
                    "hypothesis": "Test one bounded trend candidate.",
                    "parameters": {"fast_window": "not-a-number", "slow_window": 100},
                },
                decision_summary="Repeat one invalid numeric parameter.",
                expected_result="The repair guard must stop this repeated call.",
            )

    provider = RepeatedInvalidParameterProvider()
    assert run_quant_agent_once(
        store=store, provider=cast(Any, provider), workspace_id=workspace_id
    )
    baseline = deepcopy(store._workspace_state(workspace_id))  # pyright: ignore[reportPrivateUsage]
    original_persist = store._persist_workspace  # pyright: ignore[reportPrivateUsage]
    injected = False

    def fail_repair_persist(target_workspace_id: str) -> None:
        nonlocal injected
        if injected:
            original_persist(target_workspace_id)
            return
        injected = True
        if failure_timing == "postcommit":
            original_persist(target_workspace_id)
        raise RuntimeError(f"injected {failure_timing} repair-exhaustion persist failure")

    monkeypatch.setattr(store, "_persist_workspace", fail_repair_persist)
    if failure_timing == "precommit":
        with pytest.raises(RuntimeError, match="injected precommit"):
            run_quant_agent_once(
                store=store,
                provider=cast(Any, provider),
                workspace_id=workspace_id,
            )
        assert (
            store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
            == baseline
        )
        restored = store.get_run(workspace_id=workspace_id, run_id=run.id)
        assert restored.state is QuantRunState.RUNNING_EXPERIMENTS
        assert not any(
            item["payload"].get("reason_code") == "agent_contract_repair_exhausted"
            for item in store.events_for_run(workspace_id=workspace_id, run_id=run.id)
        )
        replacement_claim = store.claim_agent_run(
            workspace_id=workspace_id,
            worker_id="repair-exhaustion-retry",
        )
        assert replacement_claim is not None
        store.release_agent_claim(replacement_claim)
        return

    assert run_quant_agent_once(
        store=store,
        provider=cast(Any, provider),
        workspace_id=workspace_id,
    )
    reloaded = QuantStore()
    failed = reloaded.get_run(workspace_id=workspace_id, run_id=run.id)
    assert failed.state is QuantRunState.FAILED
    assert failed.research_series_child_run_id is None
    events = reloaded.events_for_run(workspace_id=workspace_id, run_id=run.id)
    assert (
        sum(
            item["event_type"] == "run.failed"
            and item["payload"].get("reason_code") == "agent_contract_repair_exhausted"
            for item in events
        )
        == 1
    )
    assert not any(
        artifact.kind.value == "research_report"
        for artifact in reloaded.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
    )


def test_repeated_invalid_feedback_candidate_fails_once_without_reexecuting_tool(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Reproduce the sanitized Q1 feedback-candidate contract failure.",
    )
    store = QuantStore()
    for _ in range(7):
        assert run_quant_agent_once(
            store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
        )
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert run.agent_iteration == 7
    assert (
        store.agent_context_data(workspace_id=workspace_id, run_id=run.id)["iteration_feedback"]
        is not None
    )
    run.provider = "deepseek"
    baseline_final_artifact_ids = {
        artifact.id
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        if artifact.kind.value in {"validation_report", "research_report"}
    }

    class RepeatingInvalidFeedbackProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 30/100",
                    "template": "sma_crossover",
                    "hypothesis": "Test one slower feedback-driven candidate.",
                    "parameters": {"fast_window": 30, "slow_window": 100},
                    "change_rationale": (
                        "Use the retained A/B training comparison, with changed prose that "
                        "must not bypass the field-level repair guard."
                    ),
                    "replan_decision": {
                        "action": "refine_parameters",
                        "source_comparison_artifact_id": store.agent_context_data(
                            workspace_id=workspace_id, run_id=run.id
                        )["iteration_feedback"]["comparison_artifact_id"],
                        "improvement_reference_candidate_id": store.agent_context_data(
                            workspace_id=workspace_id, run_id=run.id
                        )["iteration_feedback"]["improvement_reference"]["candidate_id"],
                        "proposed_parameters": {"fast_window": 30, "slow_window": 100},
                    },
                },
                decision_summary="Retry the same invalid feedback-candidate wire shape.",
                expected_result="The contract either repairs or stops safely.",
            )

    provider = RepeatingInvalidFeedbackProvider()
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    after_first = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert after_first.state is QuantRunState.RUNNING_EXPERIMENTS
    assert after_first.agent_iteration == 8
    first_context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    failed_observation = next(
        item
        for item in first_context["recent_observations"]
        if item["action"] == "create_candidate"
    )
    assert failed_observation["error_code"] == "INVALID_ARGUMENTS"
    assert failed_observation["call_fingerprint"].startswith("sha256:")
    assert failed_observation["repair"]["schema_version"] == "quant-tool-repair-v1"

    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    failed = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert failed.state is QuantRunState.FAILED
    assert failed.agent_iteration == 9
    assert failed.failure_reason == (
        "The Agent did not apply the required contract repair before its next action."
    )
    events = store.events_for_run(workspace_id=workspace_id, run_id=run.id)
    invalid_tool_failures = [
        item
        for item in events
        if item["event_type"] == "tool.failed"
        and item["payload"].get("action") == "create_candidate"
        and item["payload"].get("error_code") == "INVALID_ARGUMENTS"
    ]
    assert len(invalid_tool_failures) == 1
    assert any(
        item["event_type"] == "run.failed"
        and item["payload"].get("reason_code") == "agent_contract_repair_exhausted"
        for item in events
    )
    repair_failure = next(
        item
        for item in events
        if item["event_type"] == "agent.decision_failed"
        and item["payload"].get("reason_code") == "agent_contract_repair_exhausted"
    )
    assert repair_failure["payload"]["rejected_action"] == "create_candidate"
    assert repair_failure["payload"]["attempted_action"] == "create_candidate"
    assert repair_failure["payload"]["rejected_call_fingerprint"].startswith("sha256:")
    assert repair_failure["payload"]["attempted_call_fingerprint"].startswith("sha256:")
    assert (
        repair_failure["payload"]["rejected_call_fingerprint"]
        == repair_failure["payload"]["attempted_call_fingerprint"]
    )
    assert failed.research_series_child_run_id is None
    assert {
        artifact.id
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        if artifact.kind.value in {"validation_report", "research_report"}
    } == baseline_final_artifact_ids


def test_invalid_feedback_candidate_cannot_bypass_repair_with_unrelated_action(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Reject an unrelated action after a feedback-candidate contract error.",
    )
    store = QuantStore()
    for _ in range(7):
        assert run_quant_agent_once(
            store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
        )
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.provider = "deepseek"
    run.max_agent_iterations = 16
    feedback = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)[
        "iteration_feedback"
    ]
    assert feedback is not None

    class BypassProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            if self.calls > 1:
                return QuantAgentDecision(
                    action=QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
                    arguments={},
                    decision_summary="Try to bypass the required candidate repair.",
                    expected_result="The unrelated action must not execute.",
                )
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 30/100",
                    "template": "sma_crossover",
                    "hypothesis": "Test one slower feedback-driven candidate.",
                    "parameters": {"fast_window": 30, "slow_window": 100},
                    "change_rationale": "Use the retained A/B training comparison.",
                    "replan_decision": {
                        "action": "refine_parameters",
                        "source_comparison_artifact_id": feedback["comparison_artifact_id"],
                        "improvement_reference_candidate_id": feedback["improvement_reference"][
                            "candidate_id"
                        ],
                        "proposed_parameters": {"fast_window": 30, "slow_window": 100},
                    },
                },
                decision_summary="Submit the sanitized invalid candidate shape.",
                expected_result="A typed contract repair.",
            )

    provider = BypassProvider()
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]

    failed = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert failed.state is QuantRunState.FAILED
    assert failed.agent_iteration == 9
    events = store.events_for_run(workspace_id=workspace_id, run_id=run.id)
    initial_inspections = [
        item
        for item in events
        if item["event_type"] == "tool.completed"
        and item["payload"].get("action") == "inspect_research_context"
    ]
    assert len(initial_inspections) == 1
    repair_failure = next(
        item
        for item in events
        if item["event_type"] == "agent.decision_failed"
        and item["payload"].get("reason_code") == "agent_contract_repair_exhausted"
    )
    assert repair_failure["payload"]["rejected_action"] == "create_candidate"
    assert repair_failure["payload"]["attempted_action"] == "inspect_research_context"


def test_provider_failure_does_not_clear_pending_repair_or_allow_unrelated_tool(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Preserve a pending candidate repair across one provider failure.",
    )
    store = QuantStore()
    for _ in range(7):
        assert run_quant_agent_once(
            store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
        )
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.provider = "deepseek"
    feedback = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)[
        "iteration_feedback"
    ]
    assert feedback is not None

    class FailureThenBypassProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("sanitized transient provider failure")
            if self.calls == 3:
                return QuantAgentDecision(
                    action=QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
                    arguments={},
                    decision_summary="Try an unrelated tool after the provider recovers.",
                    expected_result="The pending repair must still block this action.",
                )
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 30/100",
                    "template": "sma_crossover",
                    "hypothesis": "Test one slower feedback-driven candidate.",
                    "parameters": {"fast_window": 30, "slow_window": 100},
                    "change_rationale": "Use the retained A/B training comparison.",
                    "replan_decision": {
                        "action": "refine_parameters",
                        "source_comparison_artifact_id": feedback["comparison_artifact_id"],
                        "improvement_reference_candidate_id": feedback["improvement_reference"][
                            "candidate_id"
                        ],
                        "proposed_parameters": {"fast_window": 30, "slow_window": 100},
                    },
                },
                decision_summary="Submit one invalid feedback-candidate shape.",
                expected_result="A typed contract repair.",
            )

    provider = FailureThenBypassProvider()
    baseline_candidate_ids = {
        item.id for item in store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    }
    baseline_final_artifact_ids = {
        artifact.id
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        if artifact.kind.value in {"validation_report", "research_report"}
    }
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    after_provider_failure = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert after_provider_failure.state is QuantRunState.RUNNING_EXPERIMENTS
    assert after_provider_failure.agent_iteration == 9
    reloaded_store = QuantStore()
    assert (
        reloaded_store.latest_invalid_tool_repair(workspace_id=workspace_id, run_id=run.id)
        is not None
    )
    assert run_quant_agent_once(
        store=reloaded_store,
        provider=cast(Any, provider),
        workspace_id=workspace_id,
    )

    failed = reloaded_store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert failed.state is QuantRunState.FAILED
    assert failed.agent_iteration == 10
    assert failed.research_series_child_run_id is None
    assert {
        item.id
        for item in reloaded_store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    } == baseline_candidate_ids
    events = reloaded_store.events_for_run(workspace_id=workspace_id, run_id=run.id)
    assert (
        sum(
            item["event_type"] == "agent.decision_failed"
            and item["payload"].get("reason_code") == "provider_decision_failed"
            for item in events
        )
        == 1
    )
    assert (
        sum(
            item["event_type"] == "tool.completed"
            and item["payload"].get("action") == "inspect_research_context"
            for item in events
        )
        == 1
    )
    assert any(
        item["event_type"] == "run.failed"
        and item["payload"].get("reason_code") == "agent_contract_repair_exhausted"
        for item in events
    )
    assert {
        artifact.id
        for artifact in reloaded_store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        if artifact.kind.value in {"validation_report", "research_report"}
    } == baseline_final_artifact_ids


def test_provider_failure_does_not_prevent_corrected_candidate_repair(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Apply a pending candidate repair after one provider failure.",
    )
    store = QuantStore()
    for _ in range(7):
        assert run_quant_agent_once(
            store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
        )
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.provider = "deepseek"
    feedback = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)[
        "iteration_feedback"
    ]
    assert feedback is not None

    class FailureThenRepairProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("sanitized transient provider failure")
            replan: dict[str, object] = {
                "action": "refine_parameters",
                "source_comparison_artifact_id": feedback["comparison_artifact_id"],
                "improvement_reference_candidate_id": feedback["improvement_reference"][
                    "candidate_id"
                ],
            }
            if self.calls == 1:
                replan["proposed_parameters"] = {
                    "fast_window": 30,
                    "slow_window": 100,
                }
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 30/100",
                    "template": "sma_crossover",
                    "hypothesis": "Test one slower feedback-driven candidate.",
                    "parameters": {"fast_window": 30, "slow_window": 100},
                    "change_rationale": "Apply the A/B evidence after provider recovery.",
                    "replan_decision": replan,
                },
                decision_summary="Apply the pending field removal.",
                expected_result="A feedback-linked candidate ready for backtesting.",
            )

    provider = FailureThenRepairProvider()
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]

    current = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert current.state is QuantRunState.RUNNING_EXPERIMENTS
    assert current.agent_iteration == 10
    candidates = store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    assert len(candidates) == 3
    repaired = candidates[-1]
    assert repaired.state == "created"
    assert repaired.feedback_artifact_id is not None
    assert repaired.replan_decision is not None
    assert repaired.replan_decision.proposed_parameters is None


def test_feedback_candidate_can_apply_typed_repair_on_next_decision(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Apply one typed repair to a feedback-driven candidate.",
    )
    store = QuantStore()
    for _ in range(7):
        assert run_quant_agent_once(
            store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
        )
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.provider = "deepseek"
    feedback = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)[
        "iteration_feedback"
    ]
    assert feedback is not None

    class RepairingFeedbackProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            replan: dict[str, object] = {
                "action": "refine_parameters",
                "source_comparison_artifact_id": feedback["comparison_artifact_id"],
                "improvement_reference_candidate_id": feedback["improvement_reference"][
                    "candidate_id"
                ],
            }
            if self.calls == 1:
                replan["proposed_parameters"] = {
                    "fast_window": 30,
                    "slow_window": 100,
                }
            return QuantAgentDecision(
                action=QuantAgentAction.CREATE_CANDIDATE,
                arguments={
                    "name": "SMA 30/100",
                    "template": "sma_crossover",
                    "hypothesis": "Test one slower feedback-driven candidate.",
                    "parameters": {"fast_window": 30, "slow_window": 100},
                    "change_rationale": "Apply the A/B evidence to one slower crossover.",
                    "replan_decision": replan,
                },
                decision_summary=(
                    "Retry the candidate without the field rejected by the typed repair."
                ),
                expected_result="A feedback-linked candidate ready for backtesting.",
            )

    provider = RepairingFeedbackProvider()
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]
    assert run_quant_agent_once(store=store, provider=provider, workspace_id=workspace_id)  # type: ignore[arg-type]

    current = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert current.state is QuantRunState.RUNNING_EXPERIMENTS
    assert current.agent_iteration == 9
    candidates = store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    assert len(candidates) == 3
    repaired = candidates[-1]
    assert repaired.state == "created"
    assert repaired.feedback_artifact_id is not None
    assert repaired.replan_decision is not None
    assert repaired.replan_decision.proposed_parameters is None
    events = store.events_for_run(workspace_id=workspace_id, run_id=run.id)
    assert (
        sum(
            item["event_type"] == "tool.failed"
            and item["payload"].get("error_code") == "INVALID_ARGUMENTS"
            for item in events
        )
        == 1
    )
    assert events[-2]["event_type"] == "tool.completed"
    assert events[-1]["event_type"] == "artifact.published"
    assert events[-1]["payload"]["artifact_kind"] == "learning_trace"


def test_completed_candidate_must_be_selected_before_finish(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client, principal_id, "Require holdout evidence before completion."
    )
    for _ in range(4):
        assert run_quant_agent_once(workspace_id=workspace_id)

    store = QuantStore()
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="selection-gate")
    assert claim is not None
    report, artifact_ids, error = store.finish_agent_research(
        claim,
        selected_candidate_id=None,
        conclusion="Do not finish without sealed holdout evidence.",
        next_step="stop",
    )

    assert report is None
    assert artifact_ids == []
    assert error == "SELECTION_REQUIRED"
    current = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert current.state.value != "completed"
    store.release_agent_claim(claim)


def test_budget_exhaustion_compares_once_then_finishes_with_fresh_comparison(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Keep the low-budget terminal path bounded and deterministic.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.state = QuantRunState.RUNNING_EXPERIMENTS
    run.max_experiments = 2
    run.max_agent_iterations = 12
    run.agent_iteration = run.max_agent_iterations - 2

    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="budget-terminal")
    assert claim is not None
    for name, parameters in (
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
    ):
        candidate, _, error = store.create_agent_candidate(
            claim,
            name=name,
            template="sma_crossover",
            hypothesis="Keep the budget-exhaustion path honest.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        run.state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(claim, candidate_id=candidate.id)[2] is None

    store.release_agent_claim(claim)
    first_poll = run_quant_agent_once(
        store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
    )
    assert first_poll
    after_compare = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert after_compare.state.value == "running_experiments"

    second_poll = run_quant_agent_once(
        store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
    )
    assert second_poll
    finished = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert finished.state.value == "completed"
    assert not run_quant_agent_once(
        store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
    )

    actions = [
        item["payload"]["action"]
        for item in store.events_for_run(workspace_id=workspace_id, run_id=created["id"])
        if item["event_type"] == "agent.action_selected"
    ]
    assert actions[-2:] == ["compare_candidates", "finish_research"]
    assert actions.count("compare_candidates") == 1


def test_budget_exhaustion_with_single_candidate_fails_without_holdout(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Keep the single-candidate terminal path bounded and deterministic.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.state = QuantRunState.RUNNING_EXPERIMENTS
    run.max_experiments = 3
    run.max_agent_iterations = 12
    run.agent_iteration = run.max_agent_iterations - 2

    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="single-terminal")
    assert claim is not None
    candidate, _, error = store.create_agent_candidate(
        claim,
        name="SMA 50/200",
        template="sma_crossover",
        hypothesis="Keep the single-candidate budget-exhaustion path honest.",
        parameters=cast(dict[str, int | float], {"fast_window": 50, "slow_window": 200}),
    )
    assert error is None and candidate is not None
    run.state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(claim, candidate_id=candidate.id)[2] is None
    store.release_agent_claim(claim)

    first_poll = run_quant_agent_once(
        store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
    )
    assert first_poll
    assert (
        store.get_run(workspace_id=workspace_id, run_id=created["id"]).state.value
        == "running_experiments"
    )

    second_poll = run_quant_agent_once(
        store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
    )
    assert second_poll
    finished = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert finished.state.value == "failed"
    assert finished.failure_reason is not None
    assert not run_quant_agent_once(
        store=store, provider=MockQuantAgentProvider(), workspace_id=workspace_id
    )

    actions = [
        item["payload"]["action"]
        for item in store.events_for_run(workspace_id=workspace_id, run_id=created["id"])
        if item["event_type"] == "agent.action_selected"
    ]
    assert actions[-2:] == ["compare_candidates", "finish_research"]
    assert actions.count("compare_candidates") == 1
    assert not any(
        artifact.kind.value == "research_report"
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=created["id"])
    )


def test_final_two_iterations_are_reserved_for_final_comparison_and_finish(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Reserve the final two actions for comparison and an honest terminal decision.",
    )
    store = QuantStore()
    for _ in range(9):
        assert run_quant_agent_once(
            store=store,
            provider=MockQuantAgentProvider(),
            workspace_id=workspace_id,
        )

    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert len(store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)) == 3
    run.provider = "deepseek"
    run.agent_iteration = run.max_agent_iterations - 2

    class ProviderMustNotConsumeReservedActions:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            raise AssertionError("the final two actions are controller-owned")

    provider = ProviderMustNotConsumeReservedActions()
    assert run_quant_agent_once(
        store=store,
        provider=cast(Any, provider),
        workspace_id=workspace_id,
    )
    after_comparison = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert after_comparison.state is QuantRunState.RUNNING_EXPERIMENTS
    assert after_comparison.agent_iteration == after_comparison.max_agent_iterations - 1

    assert run_quant_agent_once(
        store=store,
        provider=cast(Any, provider),
        workspace_id=workspace_id,
    )
    finished = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert finished.state is QuantRunState.COMPLETED
    assert finished.agent_iteration == finished.max_agent_iterations
    assert provider.calls == 0
    actions = [
        event["payload"]["action"]
        for event in store.events_for_run(workspace_id=workspace_id, run_id=run.id)
        if event["event_type"] == "agent.action_selected"
    ]
    assert actions[-2:] == ["compare_candidates", "finish_research"]


def test_unfinished_feedback_candidate_fails_terminally_before_action_budget_ends(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Fail honestly when Candidate C cannot be completed inside the remaining budget.",
    )
    store = QuantStore()
    for _ in range(8):
        assert run_quant_agent_once(
            store=store,
            provider=MockQuantAgentProvider(),
            workspace_id=workspace_id,
        )

    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    candidates = store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    assert len(candidates) == 3
    assert candidates[-1].state == "created"
    run.provider = "deepseek"
    run.agent_iteration = run.max_agent_iterations - 2

    class ProviderMustNotConsumeReservedActions:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            raise AssertionError("the controller must terminate the incomplete 2+1 sequence")

    provider = ProviderMustNotConsumeReservedActions()
    assert run_quant_agent_once(
        store=store,
        provider=cast(Any, provider),
        workspace_id=workspace_id,
    )

    failed = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert failed.state is QuantRunState.FAILED
    assert failed.agent_iteration <= failed.max_agent_iterations
    assert failed.failure_reason == (
        "The bounded research budget ended before the required 2+1 candidate sequence completed."
    )
    assert provider.calls == 0
    assert not any(
        artifact.kind.value == "research_report"
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
    )


def test_provider_failure_on_last_action_budget_slot_is_terminal(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Do not leave a half-finished Run after the last bounded provider attempt.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.provider = "deepseek"
    run.agent_iteration = run.max_agent_iterations - 1
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="provider-budget-terminal")
    assert claim is not None

    failures = store.record_agent_provider_failure(
        claim,
        "The model provider could not produce a valid bounded decision.",
        allow_mock_fallback=False,
    )

    assert failures == 1
    failed = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert failed.state is QuantRunState.FAILED
    assert failed.agent_iteration == failed.max_agent_iterations
    terminal = [
        event
        for event in store.events_for_run(workspace_id=workspace_id, run_id=run.id)
        if event["event_type"] == "run.failed"
    ]
    assert terminal[-1]["payload"]["reason_code"] == "agent_iteration_budget_exhausted"


def test_nonterminal_tool_observation_on_last_action_budget_slot_is_terminal(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Do not leave a half-finished Run after the last bounded tool action.",
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    run.agent_iteration = run.max_agent_iterations - 1
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="tool-budget-terminal")
    assert claim is not None
    assert store.record_agent_decision(
        claim,
        QuantAgentDecision(
            action=QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
            arguments={},
            decision_summary="Use the final bounded action.",
            expected_result="The controller must terminate if this tool is nonterminal.",
        ),
    )

    assert store.complete_agent_step(
        claim,
        QuantToolObservation(
            action=QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
            success=True,
            safe_summary="Research context inspected.",
        ),
    )

    failed = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert failed.state is QuantRunState.FAILED
    assert failed.agent_iteration == failed.max_agent_iterations
    terminal = [
        event
        for event in store.events_for_run(workspace_id=workspace_id, run_id=run.id)
        if event["event_type"] == "run.failed"
    ]
    assert terminal[-1]["payload"]["reason_code"] == "agent_iteration_budget_exhausted"


def test_finish_research_prose_change_cannot_bypass_selected_candidate_repair(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Reject a finish retry that still omits the selected candidate field.",
    )
    store = QuantStore()
    for _ in range(10):
        assert run_quant_agent_once(
            store=store,
            provider=MockQuantAgentProvider(),
            workspace_id=workspace_id,
        )
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    comparison = context["latest_comparison"]
    assert comparison is not None
    selected_candidate_id = comparison["ranking"][0]
    comparison_artifact_id = comparison["artifact_id"]
    run.provider = "deepseek"
    run.max_agent_iterations = 20

    class ProseOnlyFinishRepairProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            return QuantAgentDecision(
                action=QuantAgentAction.FINISH_RESEARCH,
                arguments={
                    "conclusion": (
                        "Select the leading candidate from the final comparison."
                        if self.calls == 1
                        else "Changed prose must not count as supplying the missing field."
                    ),
                    "next_step": "paper_evaluation",
                    "research_decision": {
                        "selected_candidate_id": selected_candidate_id,
                        "source_comparison_artifact_id": comparison_artifact_id,
                        "decision_basis": "approved_objective_rank",
                    },
                },
                decision_summary="Attempt to finish without the required top-level candidate.",
                expected_result="The typed repair must require the missing field.",
            )

    provider = ProseOnlyFinishRepairProvider()
    assert run_quant_agent_once(
        store=store,
        provider=cast(Any, provider),
        workspace_id=workspace_id,
    )
    assert run_quant_agent_once(
        store=store,
        provider=cast(Any, provider),
        workspace_id=workspace_id,
    )

    failed = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert failed.state is QuantRunState.FAILED
    events = store.events_for_run(workspace_id=workspace_id, run_id=run.id)
    invalid_finishes = [
        event
        for event in events
        if event["event_type"] == "tool.failed"
        and event["payload"].get("action") == "finish_research"
        and event["payload"].get("error_code") == "INVALID_ARGUMENTS"
    ]
    assert len(invalid_finishes) == 1
    assert any(
        event["event_type"] == "run.failed"
        and event["payload"].get("reason_code") == "agent_contract_repair_exhausted"
        for event in events
    )


def test_finish_research_applies_selected_candidate_repair_on_next_action(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client,
        principal_id,
        "Apply the field-level selected candidate repair before finishing.",
    )
    store = QuantStore()
    for _ in range(10):
        assert run_quant_agent_once(
            store=store,
            provider=MockQuantAgentProvider(),
            workspace_id=workspace_id,
        )
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    comparison = context["latest_comparison"]
    assert comparison is not None
    selected_candidate_id = comparison["ranking"][0]
    comparison_artifact_id = comparison["artifact_id"]
    run.provider = "deepseek"
    run.max_agent_iterations = 20

    class CorrectingFinishProvider:
        calls = 0

        def decide(self, _context: object) -> QuantAgentDecision:
            self.calls += 1
            arguments: dict[str, object] = {
                "conclusion": "Select the leading candidate from the final comparison.",
                "next_step": "paper_evaluation",
                "research_decision": {
                    "selected_candidate_id": selected_candidate_id,
                    "source_comparison_artifact_id": comparison_artifact_id,
                    "decision_basis": "approved_objective_rank",
                },
            }
            if self.calls > 1:
                arguments["selected_candidate_id"] = selected_candidate_id
            return QuantAgentDecision(
                action=QuantAgentAction.FINISH_RESEARCH,
                arguments=arguments,
                decision_summary="Apply the required selected candidate field.",
                expected_result="The corrected finish should execute once.",
            )

    provider = CorrectingFinishProvider()
    assert run_quant_agent_once(
        store=store,
        provider=cast(Any, provider),
        workspace_id=workspace_id,
    )
    assert run_quant_agent_once(
        store=store,
        provider=cast(Any, provider),
        workspace_id=workspace_id,
    )

    completed = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert completed.state is QuantRunState.COMPLETED
    events = store.events_for_run(workspace_id=workspace_id, run_id=run.id)
    assert (
        sum(
            event["event_type"] == "tool.failed"
            and event["payload"].get("action") == "finish_research"
            and event["payload"].get("error_code") == "INVALID_ARGUMENTS"
            for event in events
        )
        == 1
    )


def test_goals_create_different_candidates_and_cancel_stops_recovery(
    client: TestClient, principal_id: str
) -> None:
    drawdown_workspace, drawdown_run = _create_auto_run(
        client, principal_id, "Reduce maximum drawdown."
    )
    opportunity_workspace, opportunity_run = _create_auto_run(
        client, principal_id, "Find more trading opportunities without excessive drawdown."
    )
    drawdown_store = _finish(drawdown_workspace)
    opportunity_store = _finish(opportunity_workspace)
    drawdown_specs = [
        (item.template, item.parameters)
        for item in drawdown_store.experiments_for_run(
            workspace_id=drawdown_workspace, run_id=drawdown_run["id"]
        )
    ]
    opportunity_specs = [
        (item.template, item.parameters)
        for item in opportunity_store.experiments_for_run(
            workspace_id=opportunity_workspace, run_id=opportunity_run["id"]
        )
    ]
    assert drawdown_specs != opportunity_specs
    drawdown_actions = [
        item["payload"]["action"]
        for item in drawdown_store.events_for_run(
            workspace_id=drawdown_workspace, run_id=drawdown_run["id"]
        )
        if item["event_type"] == "agent.action_selected"
    ]
    opportunity_actions = [
        item["payload"]["action"]
        for item in opportunity_store.events_for_run(
            workspace_id=opportunity_workspace, run_id=opportunity_run["id"]
        )
        if item["event_type"] == "agent.action_selected"
    ]
    assert drawdown_actions.count("compare_candidates") == 2
    assert opportunity_actions.count("compare_candidates") == 2
    assert "revise_candidate" not in opportunity_actions
    assert len(drawdown_actions) == len(opportunity_actions) == 11

    cancel_workspace, cancel_run = _create_auto_run(
        client, principal_id, "Test cancellation recovery."
    )
    for _ in range(4):
        assert run_quant_agent_once(workspace_id=cancel_workspace)
    current_store = QuantStore()
    current = current_store.get_run(workspace_id=cancel_workspace, run_id=cancel_run["id"])
    response = client.post(
        f"/v1/quant/runs/{cancel_run['id']}/cancel",
        headers=_headers(principal_id, cancel_workspace),
        json={"expected_row_version": current.row_version, "reason": "User stopped the run."},
    )
    assert response.status_code == 200, response.text
    retained = len(
        QuantStore().artifacts_for_run(workspace_id=cancel_workspace, run_id=cancel_run["id"])
    )
    assert not run_quant_agent_once(workspace_id=cancel_workspace)
    assert (
        len(QuantStore().artifacts_for_run(workspace_id=cancel_workspace, run_id=cancel_run["id"]))
        == retained
    )


def test_mac_snapshot_auto_command_starts_real_incremental_run(
    client: TestClient, principal_id: str
) -> None:
    workspace_response = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={
            "name": "Mac autonomous path",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    workspace_id = workspace_response.json()["workspace_id"]
    command = client.post(
        "/v1/quant/workspace-snapshot/commands",
        headers=_headers(principal_id, workspace_id),
        json={
            "command": "start_auto_research",
            "expected_row_version": 8,
            "payload": {"goal": "Reduce drawdown from the Mac workspace."},
        },
    )
    assert command.status_code == 200, command.text
    assert command.json()["run"]["state"] == "running_experiments"
    for _ in range(3):
        assert run_quant_agent_once(workspace_id=workspace_id)
    snapshot = client.get(
        "/v1/quant/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()
    assert body["version"].startswith("Phase 1A")
    assert body["run"]["agentIteration"] == 3
    assert body["candidates"][0]["name"] == "SMA 50/200"
    assert any(item["type"] == "agent.action_selected" for item in body["events"])


class _ExplodingTools:
    def execute(self, **_kwargs: object) -> None:
        raise RuntimeError("private tool failure")


def test_unexpected_tool_failure_is_persisted_and_releases_claim(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, created = _create_auto_run(
        client, principal_id, "Persist an unexpected tool failure safely."
    )
    store = QuantStore()
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="tool-failure-test")
    assert claim is not None
    result = QuantAgentRunner(
        store=store,
        provider=MockQuantAgentProvider(),
        tools=cast(QuantToolRegistry, _ExplodingTools()),
    ).run_step(claim=claim)

    assert result.did_work
    assert not result.terminal
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert run.agent_iteration == 1
    events = store.events_for_run(workspace_id=workspace_id, run_id=created["id"])
    assert events[-1]["event_type"] == "tool.failed"
    assert events[-1]["payload"]["error_code"] == "TOOL_EXECUTION_FAILED"
    assert (
        store.claim_agent_run(workspace_id=workspace_id, worker_id="tool-failure-recovery")
        is not None
    )
