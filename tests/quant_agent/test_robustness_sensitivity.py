from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.contracts.quant import QuantResearchDecision, QuantRobustnessSensitivity
from packages.domain.canonical import canonical_digest
from services.api.app.modules.quant.snapshot import quant_agent_workspace_snapshot
from services.api.app.modules.quant.store import (
    RESEARCH_DECISION_REPOSITORY_PREFIX,
    QuantExperimentRecord,
    QuantStore,
)
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.provider import MockQuantAgentProvider


def _metrics() -> dict[str, float | int]:
    return {
        "total_return_pct": 3.25,
        "annualized_return_pct": 4.5,
        "maximum_drawdown_pct": -2.0,
        "sharpe_ratio": 0.75,
        "trade_count": 4,
        "win_rate_pct": 50.0,
        "final_equity": 103.25,
    }


def _contract_payload() -> dict[str, object]:
    return {
        "schema_version": "robustness_sensitivity_v1",
        "evaluation_partition": "train",
        "run_id": "run-1",
        "report_artifact_id": "report-1",
        "candidate": {
            "candidate_id": "candidate-1",
            "template": "rsi_mean_reversion",
            "parameters": {
                "period": 14,
                "entry_threshold": 30,
                "exit_threshold": 70,
            },
            "canonical_key": "sha256:candidate",
        },
        "final_training_comparison": {
            "artifact_id": "comparison-1",
            "artifact_digest": "sha256:comparison",
        },
        "dataset": {
            "dataset_id": "dataset-1",
            "dataset_digest": "sha256:dataset",
        },
        "interval": "1D",
        "periods_per_year": 252,
        "runtime_descriptor_digest": "sha256:runtime",
        "training_split": {
            "identity_kind": "deterministic_legacy_split",
            "rule_version": "chronological-80-20-v1",
            "training_bar_count": 800,
            "training_start": "2020-01-01",
            "training_end": "2023-03-01",
            "training_split_digest": "sha256:training",
            "sealed_split_digest": None,
        },
        "execution_rule_version": "quant-execution-cost-policy-v1",
        "sampler_rule_version": "oat-parameter-neighborhood-v1",
        "cost_scenarios": [
            {
                "scenario": name,
                "multiplier": multiplier,
                "fee_rate": 0.001 * multiplier,
                "slippage_rate": 0.0005 * multiplier,
                "candidate_metrics": _metrics(),
                "benchmark_metrics": _metrics(),
            }
            for name, multiplier in (
                ("baseline_1x", 1),
                ("stressed_2x", 2),
                ("stressed_4x", 4),
            )
        ],
        "parameter_neighbors": [
            {
                "parameter_name": parameter,
                "direction": direction,
                "parameters": {
                    "period": period,
                    "entry_threshold": entry,
                    "exit_threshold": exit_,
                },
                "canonical_key": f"sha256:{parameter}-{direction}",
                "candidate_metrics": _metrics(),
            }
            for parameter, direction, period, entry, exit_ in (
                ("period", "lower", 13, 30, 70),
                ("period", "upper", 15, 30, 70),
                ("entry_threshold", "lower", 14, 25, 70),
                ("entry_threshold", "upper", 14, 35, 70),
                ("exit_threshold", "lower", 14, 30, 65),
                ("exit_threshold", "upper", 14, 30, 75),
            )
        ],
        "kernel_call_count": 12,
    }


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _create_run(
    client: TestClient,
    principal_id: str,
    *,
    name: str,
) -> tuple[str, dict[str, Any]]:
    workspace_id = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={
            "name": name,
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    ).json()["workspace_id"]
    project = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": name, "objective": "Compare bounded strategies."},
    ).json()
    run = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "mode": "auto",
            "question": "Compare bounded strategies.",
            "expected_project_row_version": project["row_version"],
        },
    ).json()
    return workspace_id, run


def _prepare_final_comparison(workspace_id: str, *, polls: int = 10) -> QuantStore:
    store = QuantStore()
    for _ in range(polls):
        assert run_quant_agent_once(
            store=store,
            provider=MockQuantAgentProvider(),
            workspace_id=workspace_id,
        )
    return store


def _finish_prepared(store: QuantStore, workspace_id: str, run_id: str) -> None:
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run_id)
    comparison = context["latest_comparison"]
    assert comparison is not None
    selected_id = comparison["ranking"][0]
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="w3-finish")
    assert claim is not None
    report, artifact_ids, error = store.finish_agent_research(
        claim,
        selected_candidate_id=selected_id,
        conclusion="Retain the final training selection.",
        next_step="stop",
        research_decision=QuantResearchDecision(
            selected_candidate_id=selected_id,
            source_comparison_artifact_id=comparison["artifact_id"],
            decision_basis="approved_objective_rank",
        ),
    )
    assert report is not None
    assert len(artifact_ids) == 2
    assert error is None


def _reseal_p19(state: dict[str, Any]) -> None:
    reports = [
        artifact for artifact in state["artifacts"] if artifact["kind"] == "research_report"
    ]
    report_identities = [
        {
            "artifact_id": artifact["id"],
            "workspace_id": artifact["workspace_id"],
            "run_id": artifact["run_id"],
            "selected_candidate_id": artifact["content"].get("selected_candidate_id"),
            "decision_exempt": artifact["content"].get("research_decision") is None,
            "artifact_digest": artifact["digest"],
            "content_digest": canonical_digest(artifact["content"]),
        }
        for artifact in reports
    ]
    artifacts_by_id = {artifact["id"]: artifact for artifact in state["artifacts"]}
    comparison_identities: dict[str, dict[str, Any]] = {}
    for report in reports:
        decision = report["content"].get("research_decision")
        if not isinstance(decision, dict):
            continue
        comparison = artifacts_by_id[decision["source_comparison_artifact_id"]]
        comparison_identities[comparison["id"]] = {
            "artifact_id": comparison["id"],
            "workspace_id": comparison["workspace_id"],
            "run_id": comparison["run_id"],
            "artifact_digest": comparison["digest"],
            "content_digest": canonical_digest(comparison["content"]),
        }
    report_identities.sort(key=lambda item: item["artifact_id"])
    comparisons = sorted(
        comparison_identities.values(), key=lambda item: item["artifact_id"]
    )
    state["research_decision_report_manifest_digest"] = canonical_digest(
        report_identities
    )
    marker_digest = canonical_digest(
        {"reports": report_identities, "comparisons": comparisons}
    ).removeprefix("sha256:")
    state["research_decision_contract_marker"] = (
        f"{RESEARCH_DECISION_REPOSITORY_PREFIX}{marker_digest[:56]}"
    )


def test_robustness_sensitivity_contract_is_closed_and_finite() -> None:
    payload = _contract_payload()
    parsed = QuantRobustnessSensitivity.model_validate(payload)
    assert parsed.schema_version == "robustness_sensitivity_v1"
    assert parsed.kernel_call_count == 12

    extra = deepcopy(payload)
    extra["robustness_score"] = 0.8
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QuantRobustnessSensitivity.model_validate(extra)

    nan_payload = deepcopy(payload)
    nan_payload["cost_scenarios"][0]["candidate_metrics"]["sharpe_ratio"] = float("nan")  # type: ignore[index]
    with pytest.raises(ValidationError):
        QuantRobustnessSensitivity.model_validate(nan_payload)


@pytest.mark.parametrize(
    ("template", "parameters", "expected_count"),
    (
        (
            "sma_crossover",
            {"fast_window": 20, "slow_window": 100},
            4,
        ),
        (
            "rsi_mean_reversion",
            {"period": 14, "entry_threshold": 30, "exit_threshold": 70},
            6,
        ),
        ("breakout", {"lookback_window": 50}, 2),
    ),
)
def test_parameter_neighborhood_has_bounded_oat_shape(
    template: str,
    parameters: dict[str, int | float],
    expected_count: int,
) -> None:
    from services.api.app.modules.quant.store import QuantStore

    neighbors = QuantStore._robustness_parameter_neighbors(  # pyright: ignore[reportPrivateUsage]
        template,
        parameters,
    )
    assert len(neighbors) == expected_count
    assert len({item["canonical_key"] for item in neighbors}) == expected_count
    assert all(
        sum(
            item["parameters"][key] != parameters[key]
            for key in parameters
        )
        == 1
        for item in neighbors
    )


def test_completed_run_retains_one_linked_artifact_and_exact_snapshot_projection(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace_id, run = _create_run(client, principal_id, name="W3 retained evidence")
    store = _prepare_final_comparison(workspace_id)
    _finish_prepared(store, workspace_id, run["id"])

    artifacts = store.artifacts_for_run(workspace_id=workspace_id, run_id=run["id"])
    robustness = [
        item for item in artifacts if item.kind.value == "robustness_sensitivity"
    ]
    assert len(robustness) == 1
    retained = robustness[0]
    report = next(item for item in artifacts if item.kind.value == "research_report")
    comparison = next(
        item
        for item in artifacts
        if item.id
        == report.content["research_decision"]["source_comparison_artifact_id"]
    )
    selected = next(
        item
        for item in store.experiments_for_run(
            workspace_id=workspace_id, run_id=run["id"]
        )
        if item.id == report.content["selected_candidate_id"]
    )
    parsed = QuantRobustnessSensitivity.model_validate(retained.content)
    assert comparison.ordinal < retained.ordinal < report.ordinal
    assert report.content["robustness_sensitivity"] == {
        "artifact_id": retained.id,
        "artifact_digest": retained.digest,
    }
    assert parsed.report_artifact_id == report.id
    assert parsed.cost_scenarios[0].candidate_metrics.model_dump(mode="json") == (
        selected.metrics
    )
    assert parsed.cost_scenarios[0].benchmark_metrics.model_dump(mode="json") == (
        comparison.content["benchmark"]
    )
    assert parsed.kernel_call_count == 6 + len(parsed.parameter_neighbors)
    assert all("trades" not in item and "equity_curve" not in item for item in retained.content)

    published_ids = {
        event["payload"]["artifact_id"]
        for event in store.events_for_run(
            workspace_id=workspace_id, run_id=run["id"]
        )
        if event["event_type"] == "artifact.published"
    }
    assert retained.id in published_ids

    snapshot = quant_agent_workspace_snapshot(
        workspace_id=workspace_id, run_id=run["id"]
    )
    assert snapshot is not None
    projection = snapshot["report"]["robustnessSensitivity"]
    assert projection["schemaVersion"] == "robustness_sensitivity_v1"
    assert projection["runId"] == run["id"]
    assert projection["reportArtifactId"] == report.id
    assert projection["candidate"]["candidateId"] == selected.id
    assert projection["candidate"]["parameters"] == selected.parameters
    assert set(projection["candidate"]["parameters"]) == set(selected.parameters)
    assert all(
        set(item["parameters"]) == set(selected.parameters)
        for item in projection["parameterNeighbors"]
    )
    assert projection["kernelCallCount"] == parsed.kernel_call_count
    artifact_projection = next(
        item for item in snapshot["artifacts"] if item["id"] == retained.id
    )
    assert artifact_projection["type"] == "validation_report"


def test_pre_w3_completed_state_without_artifact_or_link_still_restores(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace_id, run = _create_run(client, principal_id, name="W3 legacy restore")
    store = _prepare_final_comparison(workspace_id)
    _finish_prepared(store, workspace_id, run["id"])
    legacy = deepcopy(
        store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    )
    robustness = next(
        item for item in legacy["artifacts"] if item["kind"] == "robustness_sensitivity"
    )
    legacy["artifacts"].remove(robustness)
    report = next(
        item for item in legacy["artifacts"] if item["kind"] == "research_report"
    )
    report["content"].pop("robustness_sensitivity")
    report["digest"] = canonical_digest(report["content"])
    _reseal_p19(legacy)

    restored = QuantStore()
    restored._restore_workspace(workspace_id, legacy)  # pyright: ignore[reportPrivateUsage]
    restored._loaded_workspaces.add(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    assert (
        restored.get_run(workspace_id=workspace_id, run_id=run["id"]).state.value
        == "completed"
    )
    assert not any(
        item.kind.value == "robustness_sensitivity"
        for item in restored._artifacts.values()  # pyright: ignore[reportPrivateUsage]
        if item.run_id == run["id"]
    )


@pytest.mark.parametrize(
    "tamper",
    (
        "stale_digest",
        "candidate_identity",
        "comparison_identity",
        "missing",
        "duplicate",
        "unlinked",
        "cross_run",
        "ordinal",
        "baseline",
        "neighbor_order",
        "report_link_digest",
    ),
)
def test_w3_tamper_is_rejected_atomically(
    client: TestClient,
    principal_id: str,
    tamper: str,
) -> None:
    workspace_id, run = _create_run(client, principal_id, name=f"W3 tamper {tamper}")
    store = _prepare_final_comparison(workspace_id)
    _finish_prepared(store, workspace_id, run["id"])
    state = deepcopy(
        store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    )
    robustness = next(
        item for item in state["artifacts"] if item["kind"] == "robustness_sensitivity"
    )
    report = next(
        item for item in state["artifacts"] if item["kind"] == "research_report"
    )

    def reseal_graph() -> None:
        robustness["digest"] = canonical_digest(robustness["content"])
        report["content"]["robustness_sensitivity"] = {
            "artifact_id": robustness["id"],
            "artifact_digest": robustness["digest"],
        }
        report["digest"] = canonical_digest(report["content"])
        _reseal_p19(state)

    if tamper == "stale_digest":
        robustness["content"]["kernel_call_count"] -= 1
    elif tamper == "candidate_identity":
        robustness["content"]["candidate"]["candidate_id"] = "candidate-tampered"
        reseal_graph()
    elif tamper == "comparison_identity":
        robustness["content"]["final_training_comparison"]["artifact_id"] = "missing"
        reseal_graph()
    elif tamper == "missing":
        state["artifacts"].remove(robustness)
    elif tamper == "duplicate":
        duplicate = deepcopy(robustness)
        duplicate["id"] = f"{robustness['id']}-duplicate"
        state["artifacts"].append(duplicate)
    elif tamper == "unlinked":
        report["content"].pop("robustness_sensitivity")
        report["digest"] = canonical_digest(report["content"])
        _reseal_p19(state)
    elif tamper == "cross_run":
        robustness["run_id"] = "another-run"
    elif tamper == "ordinal":
        robustness["ordinal"] = report["ordinal"] + 1
    elif tamper == "baseline":
        robustness["content"]["cost_scenarios"][0]["candidate_metrics"][
            "total_return_pct"
        ] += 1
        reseal_graph()
    elif tamper == "neighbor_order":
        robustness["content"]["parameter_neighbors"].reverse()
        reseal_graph()
    else:
        report["content"]["robustness_sensitivity"]["artifact_digest"] = "sha256:wrong"
        report["digest"] = canonical_digest(report["content"])
        _reseal_p19(state)

    guarded = QuantStore()
    baseline = guarded._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    with pytest.raises((KeyError, TypeError, ValueError)):
        guarded._restore_workspace(workspace_id, state)  # pyright: ignore[reportPrivateUsage]
    assert (
        guarded._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        == baseline
    )


def test_no_selected_candidate_produces_no_sensitivity_artifact(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace_id, run_response = _create_run(
        client, principal_id, name="W3 no selected candidate"
    )
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=run_response["id"])
    run.agent_iteration = run.max_agent_iterations - 1
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="w3-no-selection")
    assert claim is not None
    report, artifact_ids, error = store.finish_agent_research(
        claim,
        selected_candidate_id=None,
        conclusion="No completed candidate was available.",
        next_step="stop",
    )
    assert report is not None
    assert len(artifact_ids) == 1
    assert error is None
    assert "robustness_sensitivity" not in report
    assert not any(
        item.kind.value == "robustness_sensitivity"
        for item in store.artifacts_for_run(
            workspace_id=workspace_id, run_id=run_response["id"]
        )
    )


@pytest.mark.parametrize("failure", ("generation", "persistence"))
def test_sensitivity_failure_leaves_no_partial_artifact(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    workspace_id, run = _create_run(
        client, principal_id, name=f"W3 atomic {failure}"
    )
    store = _prepare_final_comparison(workspace_id)
    context = store.agent_context_data(workspace_id=workspace_id, run_id=run["id"])
    comparison = context["latest_comparison"]
    selected_id = comparison["ranking"][0]
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id=f"w3-{failure}")
    assert claim is not None
    baseline = deepcopy(
        store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    )

    def fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(f"injected {failure} failure")

    target = (
        "_robustness_sensitivity_content"
        if failure == "generation"
        else "_persist_workspace"
    )
    monkeypatch.setattr(store, target, fail)
    with pytest.raises(RuntimeError, match=failure):
        store.finish_agent_research(
            claim,
            selected_candidate_id=selected_id,
            conclusion="This finish must roll back.",
            next_step="stop",
            research_decision=QuantResearchDecision(
                selected_candidate_id=selected_id,
                source_comparison_artifact_id=comparison["artifact_id"],
                decision_basis="approved_objective_rank",
            ),
        )
    assert (
        store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        == baseline
    )


def test_rsi_sensitivity_uses_twelve_training_only_kernel_calls(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.api.app.modules.quant import store as store_module

    workspace_id, run_response = _create_run(client, principal_id, name="W3 RSI calls")
    store = _prepare_final_comparison(workspace_id)
    run = store.get_run(workspace_id=workspace_id, run_id=run_response["id"])
    selected_parameters = {
        "period": 14,
        "entry_threshold": 30,
        "exit_threshold": 70,
    }
    selected = QuantExperimentRecord(
        id="candidate-rsi",
        workspace_id=workspace_id,
        run_id=run.id,
        ordinal=99,
        name="RSI sensitivity candidate",
        hypothesis="Test a bounded RSI neighborhood.",
        verdict="viable",  # type: ignore[arg-type]
        summary="Completed.",
        template="rsi_mean_reversion",
        parameters=selected_parameters,
        state="completed",
        candidate_key=store.canonical_candidate_key(
            "rsi_mean_reversion", selected_parameters
        ),
    )
    comparison = next(
        item
        for item in reversed(
            store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        )
        if item.kind.value == "validation_report"
        and item.content.get("evaluation_partition") == "train"
    )
    runtime_projection = store.runtime_projection(run)
    call_bar_counts: list[int] = []
    original_candidate = store_module.run_backtest
    original_benchmark = store_module.backtest_buy_and_hold

    def candidate_call(*args: Any, **kwargs: Any) -> Any:
        call_bar_counts.append(len(args[0]))
        return original_candidate(*args, **kwargs)

    def benchmark_call(*args: Any, **kwargs: Any) -> Any:
        call_bar_counts.append(len(args[0]))
        return original_benchmark(*args, **kwargs)

    monkeypatch.setattr(store_module, "run_backtest", candidate_call)
    monkeypatch.setattr(store_module, "backtest_buy_and_hold", benchmark_call)
    content = store._robustness_sensitivity_content(  # pyright: ignore[reportPrivateUsage]
        run=run,
        selected=selected,
        comparison_artifact=comparison,
        runtime=runtime_projection.descriptor,
        runtime_split=runtime_projection.split,
        report_artifact_id="report-rsi",
    )
    assert content["kernel_call_count"] == 12
    assert len(call_bar_counts) == 12
    assert set(call_bar_counts) == {len(runtime_projection.split.training_bars)}


def test_finish_runs_all_sensitivity_calls_before_any_holdout_kernel_call(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.api.app.modules.quant import store as store_module

    workspace_id, run = _create_run(client, principal_id, name="W3 holdout order")
    store = _prepare_final_comparison(workspace_id)
    runtime = store.runtime_projection(
        store.get_run(workspace_id=workspace_id, run_id=run["id"])
    )
    training_count = len(runtime.split.training_bars)
    all_count = len(runtime.split.all_bars)
    calls: list[tuple[str, int, float, float]] = []
    original_candidate = store_module.run_backtest
    original_benchmark = store_module.backtest_buy_and_hold

    def candidate_call(*args: Any, **kwargs: Any) -> Any:
        execution = args[2]
        calls.append(
            (
                "candidate",
                len(args[0]),
                execution.fee_rate,
                execution.slippage_rate,
            )
        )
        return original_candidate(*args, **kwargs)

    def benchmark_call(*args: Any, **kwargs: Any) -> Any:
        execution = args[1]
        calls.append(
            (
                "benchmark",
                len(args[0]),
                execution.fee_rate,
                execution.slippage_rate,
            )
        )
        return original_benchmark(*args, **kwargs)

    monkeypatch.setattr(store_module, "run_backtest", candidate_call)
    monkeypatch.setattr(store_module, "backtest_buy_and_hold", benchmark_call)
    _finish_prepared(store, workspace_id, run["id"])
    artifact = next(
        item
        for item in store.artifacts_for_run(
            workspace_id=workspace_id, run_id=run["id"]
        )
        if item.kind.value == "robustness_sensitivity"
    )
    sensitivity_call_count = artifact.content["kernel_call_count"]
    leading_context_call_count = 1
    sensitivity_calls = calls[
        leading_context_call_count : leading_context_call_count
        + sensitivity_call_count
    ]
    assert all(
        bar_count == training_count
        for _, bar_count, _, _ in sensitivity_calls
    )
    assert sensitivity_calls[:6] == [
        ("candidate", training_count, 0.001, 0.0005),
        ("benchmark", training_count, 0.001, 0.0005),
        ("candidate", training_count, 0.002, 0.001),
        ("benchmark", training_count, 0.002, 0.001),
        ("candidate", training_count, 0.004, 0.002),
        ("benchmark", training_count, 0.004, 0.002),
    ]
    first_holdout_call = next(
        index for index, (_, bar_count, _, _) in enumerate(calls) if bar_count == all_count
    )
    assert first_holdout_call >= leading_context_call_count + sensitivity_call_count


def test_extreme_sensitivity_does_not_change_selection_series_or_next_step(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normal_workspace, normal_run = _create_run(
        client, principal_id, name="W3 normal sensitivity"
    )
    extreme_workspace, extreme_run = _create_run(
        client, principal_id, name="W3 extreme sensitivity"
    )
    normal_store = _prepare_final_comparison(normal_workspace)
    extreme_store = _prepare_final_comparison(extreme_workspace)
    original_builder = extreme_store._robustness_sensitivity_content  # pyright: ignore[reportPrivateUsage]

    def extreme_builder(**kwargs: Any) -> dict[str, Any]:
        content = original_builder(**kwargs)
        extreme_metrics = {
            "total_return_pct": -9999.0,
            "annualized_return_pct": -9999.0,
            "maximum_drawdown_pct": -99.0,
            "sharpe_ratio": -9999.0,
            "trade_count": 0,
            "win_rate_pct": 0.0,
            "final_equity": 1.0,
        }
        for scenario in content["cost_scenarios"][1:]:
            scenario["candidate_metrics"] = deepcopy(extreme_metrics)
        for neighbor in content["parameter_neighbors"]:
            neighbor["candidate_metrics"] = deepcopy(extreme_metrics)
        QuantRobustnessSensitivity.model_validate(content)
        return content

    monkeypatch.setattr(
        extreme_store,
        "_robustness_sensitivity_content",
        extreme_builder,
    )
    _finish_prepared(normal_store, normal_workspace, normal_run["id"])
    _finish_prepared(extreme_store, extreme_workspace, extreme_run["id"])

    def outcome(
        store: QuantStore, workspace_id: str, run_id: str
    ) -> tuple[str, dict[str, Any], str, object, object]:
        artifacts = store.artifacts_for_run(
            workspace_id=workspace_id, run_id=run_id
        )
        report = next(item for item in artifacts if item.kind.value == "research_report")
        selected = next(
            item
            for item in store.experiments_for_run(
                workspace_id=workspace_id, run_id=run_id
            )
            if item.id == report.content["selected_candidate_id"]
        )
        retained_run = store.get_run(workspace_id=workspace_id, run_id=run_id)
        return (
            selected.template,
            selected.parameters,
            report.content["next_step"],
            retained_run.research_series_decision,
            retained_run.research_series_child_run_id,
        )

    assert outcome(normal_store, normal_workspace, normal_run["id"]) == outcome(
        extreme_store, extreme_workspace, extreme_run["id"]
    )
