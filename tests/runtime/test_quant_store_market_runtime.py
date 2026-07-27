from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from packages.contracts.quant import (
    QuantAgentContext,
    QuantBarInterval,
    QuantEvidenceReplanDecision,
    QuantMarketDataProvenance,
    QuantMarketDatasetCadenceQuality,
    QuantMarketDatasetEvidence,
    QuantRunMode,
    QuantRunState,
    QuantWorkspaceTradeProjection,
    daily_bar_dataset_to_market_dataset,
)
from packages.contracts.quant.context import QuantAgentMarketDatasetSummary
from packages.contracts.quant.fixture_data import SPY_DAILY_FIXTURE
from packages.domain.quant_backtest import (
    BacktestInterval,
    ExecutionConfig,
    MarketBar,
    StrategySpec,
    backtest_buy_and_hold,
    run_backtest,
)
from services.api.app.core.errors import ApiError
from services.api.app.modules.quant import store as quant_store_module
from services.api.app.modules.quant.report_export import build_strategy_report_export
from services.api.app.modules.quant.snapshot import quant_agent_workspace_snapshot
from services.api.app.modules.quant.store import (
    QuantRuntimeDatasetDescriptor,
    QuantStore,
    _decimal_to_runtime_float,  # pyright: ignore[reportPrivateUsage]
    _market_research_sufficiency,  # pyright: ignore[reportPrivateUsage]
    _runtime_split,  # pyright: ignore[reportPrivateUsage]
)
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.prompt import build_decision_messages
from services.worker.app.quant_agent.provider import MockQuantAgentProvider


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def test_workspace_trade_projection_keeps_daily_and_market_holding_contracts_disjoint() -> None:
    common = {
        "id": "trade-1",
        "candidateId": "candidate-1",
        "entryDate": "2026-01-01T00:00:00+00:00",
        "exitDate": "2026-01-04T16:00:00+00:00",
        "returnPct": 1.2,
        "reason": "Retained trade.",
    }
    market = QuantWorkspaceTradeProjection.model_validate(
        {**common, "holdingBars": 22, "holdingElapsedSeconds": 316_800}
    )
    daily = QuantWorkspaceTradeProjection.model_validate(
        {**common, "entryDate": "2026-01-01", "exitDate": "2026-01-04", "holdingDays": 3}
    )

    assert market.model_dump(by_alias=True, exclude_none=True)["holdingElapsedSeconds"] == 316_800
    assert daily.model_dump(by_alias=True, exclude_none=True)["holdingDays"] == 3
    with pytest.raises(ValueError, match="cannot be mixed"):
        QuantWorkspaceTradeProjection.model_validate(
            {**common, "holdingDays": 3, "holdingBars": 22, "holdingElapsedSeconds": 316_800}
        )
    with pytest.raises(ValueError, match="require holding_bars"):
        QuantWorkspaceTradeProjection.model_validate({**common, "holdingBars": 22})


def _workspace(client: TestClient, principal_id: str, name: str) -> str:
    response = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={
            "name": name,
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["workspace_id"])


def _market_csv(
    interval: QuantBarInterval,
    count: int,
    *,
    gap_after: int | None = None,
) -> str:
    step = {
        QuantBarInterval.HOUR: timedelta(hours=1),
        QuantBarInterval.FOUR_HOURS: timedelta(hours=4),
        QuantBarInterval.DAILY: timedelta(days=1),
    }[interval]
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    rows = ["timestamp,open,high,low,close,volume"]
    for index in range(count):
        if gap_after is not None and index == gap_after:
            timestamp += step
        opening = Decimal("100") + Decimal(index % 17) / Decimal("10")
        close = opening + Decimal((index % 5) - 2) / Decimal("20")
        high = max(opening, close) + Decimal("0.25")
        low = min(opening, close) - Decimal("0.25")
        rows.append(
            f"{timestamp.isoformat().replace('+00:00', 'Z')},"
            f"{opening},{high},{low},{close},{Decimal('12.3456789') + index}"
        )
        timestamp += step
    return "\n".join(rows) + "\n"


def _provision_runtime(
    client: TestClient,
    principal_id: str,
    *,
    interval: QuantBarInterval,
    count: int = 320,
    gap_after: int | None = None,
) -> tuple[QuantStore, str, Any, Any]:
    workspace_id = _workspace(client, principal_id, f"C3B1 {interval.value} {uuid4().hex[:8]}")
    store = QuantStore()
    record = store.import_market_dataset_v2_csv(
        workspace_id=workspace_id,
        name=f"BTCUSDT {interval.value}",
        symbol="BTCUSDT",
        interval=interval,
        csv_text=_market_csv(interval, count, gap_after=gap_after),
        source_name="C3B1 controlled market CSV",
        source_reference=f"test:{interval.value}",
        file_name=f"btcusdt-{interval.value}.csv",
    )
    project = store.create_project(
        workspace_id=workspace_id,
        name=f"C3B1 {interval.value} project",
        objective="Verify cadence-aware internal runtime evaluation.",
    )
    return store, workspace_id, record, project


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {
            nested_key for item in value.values() for nested_key in _nested_keys(item)
        }
    if isinstance(value, list | tuple):
        return {nested_key for item in value for nested_key in _nested_keys(item)}
    return set()


def _prepare_runtime_run_for_finish(
    store: QuantStore,
    *,
    workspace_id: str,
    run_id: str,
    worker_id: str,
) -> tuple[Any, str]:
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id=worker_id)
    assert claim is not None
    candidate, _, error = store.create_agent_candidate(
        claim,
        name="SMA 5/20",
        template="sma_crossover",
        hypothesis="A compact trend filter may reduce drawdown.",
        parameters={"fast_window": 5, "slow_window": 20},
    )
    assert error is None and candidate is not None
    run.state = QuantRunState.RUNNING_EXPERIMENTS
    completed, _, error = store.run_agent_backtest(claim, candidate_id=candidate.id)
    assert error is None and completed is not None

    second_candidate, _, error = store.create_agent_candidate(
        claim,
        name="Breakout 10",
        template="breakout",
        hypothesis="A short breakout provides a distinct training comparison.",
        parameters={"lookback_window": 10},
    )
    assert error is None and second_candidate is not None
    run.state = QuantRunState.RUNNING_EXPERIMENTS
    second_completed, _, error = store.run_agent_backtest(claim, candidate_id=second_candidate.id)
    assert error is None and second_completed is not None

    comparison, _, error = store.compare_agent_candidates(claim)
    assert error is None and comparison is not None
    feedback = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        if artifact.kind.value == "iteration_feedback"
    )
    third_candidate, _, error = store.create_agent_candidate(
        claim,
        name="SMA 8/30",
        template="sma_crossover",
        hypothesis="Use the train-only comparison to test one distinct trend cadence.",
        parameters={"fast_window": 8, "slow_window": 30},
        change_rationale="The training comparison supports one bounded, canonical-distinct test.",
        replan_decision=QuantEvidenceReplanDecision(
            action=(
                "refine_parameters"
                if next(
                    item["template"]
                    for item in feedback.content["completed_candidates"]
                    if item["candidate_id"]
                    == feedback.content["improvement_reference"]["candidate_id"]
                )
                == "sma_crossover"
                else "switch_approved_family"
            ),
            source_comparison_artifact_id=feedback.content["comparison_artifact_id"],
            improvement_reference_candidate_id=feedback.content["improvement_reference"][
                "candidate_id"
            ],
        ),
    )
    assert error is None and third_candidate is not None
    run.state = QuantRunState.RUNNING_EXPERIMENTS
    third_completed, _, error = store.run_agent_backtest(claim, candidate_id=third_candidate.id)
    assert error is None and third_completed is not None
    final_comparison, _, error = store.compare_agent_candidates(claim)
    assert error is None and final_comparison is not None
    return claim, str(final_comparison["ranking"][0])


def _persisted_workspace_state(workspace_id: str) -> dict[str, Any]:
    """Read the durable state through a fresh cache for mutation-boundary assertions."""

    return QuantStore()._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("interval", "periods_per_year", "bar_count", "required_bars", "eligible"),
    [
        (QuantBarInterval.HOUR, 8760, 2189, 2190, False),
        (QuantBarInterval.HOUR, 8760, 2190, 2190, True),
        (QuantBarInterval.FOUR_HOURS, 2190, 547, 548, False),
        (QuantBarInterval.FOUR_HOURS, 2190, 548, 548, True),
        (QuantBarInterval.DAILY, 365, 251, 252, False),
        (QuantBarInterval.DAILY, 365, 252, 252, True),
    ],
)
def test_market_research_sufficiency_uses_interval_aware_thresholds(
    interval: QuantBarInterval,
    periods_per_year: int,
    bar_count: int,
    required_bars: int,
    eligible: bool,
) -> None:
    step = {
        QuantBarInterval.HOUR: timedelta(hours=1),
        QuantBarInterval.FOUR_HOURS: timedelta(hours=4),
        QuantBarInterval.DAILY: timedelta(days=1),
    }[interval]
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + step * (bar_count - 1)

    sufficiency = _market_research_sufficiency(
        interval=interval,
        periods_per_year=periods_per_year,
        bar_count=bar_count,
        coverage_start_utc=start,
        coverage_end_utc=end,
    )

    assert sufficiency.required_bars == required_bars
    assert sufficiency.eligible is eligible


def test_market_research_sufficiency_requires_exact_inclusive_coverage() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    step = timedelta(hours=1)
    almost = _market_research_sufficiency(
        interval=QuantBarInterval.HOUR,
        periods_per_year=8760,
        bar_count=2190,
        coverage_start_utc=start,
        coverage_end_utc=start + step * 2189 - timedelta(microseconds=1),
    )
    exact = _market_research_sufficiency(
        interval=QuantBarInterval.HOUR,
        periods_per_year=8760,
        bar_count=2190,
        coverage_start_utc=start,
        coverage_end_utc=start + step * 2189,
    )

    assert almost.eligible is False
    assert exact.eligible is True


def test_private_market_plan_rejects_every_public_mutation_without_side_effects(
    client: TestClient,
    principal_id: str,
) -> None:
    store, workspace_id, record, project = _provision_runtime(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    run = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=project.id,
        question="Keep a private hourly plan readable but publicly immutable.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=project.row_version,
        dataset_id=record.id,
    )
    baseline = _persisted_workspace_state(workspace_id)
    explicit_requests = (
        (
            f"/v1/quant/runs/{run.id}/approve-plan",
            {
                "expected_row_version": run.row_version,
                "plan_revision": run.plan_revision,
                "reason": "This public mutation must remain disabled.",
            },
        ),
        (
            f"/v1/quant/runs/{run.id}/request-plan-changes",
            {
                "expected_row_version": run.row_version,
                "plan_revision": run.plan_revision,
                "change_request": "This public mutation must remain disabled.",
            },
        ),
        (
            f"/v1/quant/runs/{run.id}/cancel",
            {
                "expected_row_version": run.row_version,
                "reason": "This public mutation must remain disabled.",
            },
        ),
        (
            f"/v1/quant/runs/{run.id}/retry",
            {
                "expected_row_version": run.row_version,
                "reason": "This public mutation must remain disabled.",
            },
        ),
    )
    for path, body in explicit_requests:
        response = client.post(
            path,
            headers=_headers(principal_id, workspace_id),
            json=body,
        )
        assert response.status_code == 409, response.text
        assert "public mutations remain disabled" in response.json()["error"]["message"]
        assert _persisted_workspace_state(workspace_id) == baseline

    for command in ("approve_plan", "request_plan_changes", "cancel_run", "retry_run"):
        payload: dict[str, object] = {}
        if command == "request_plan_changes":
            payload["change_request"] = "This public mutation must remain disabled."
        response = client.post(
            "/v1/quant/workspace-snapshot/commands",
            headers=_headers(principal_id, workspace_id),
            json={
                "command": command,
                "expected_row_version": run.row_version,
                "payload": payload,
            },
        )
        assert response.status_code == 409, response.text
        assert "public mutations remain disabled" in response.json()["error"]["message"]
        assert _persisted_workspace_state(workspace_id) == baseline

    current_project = store.get_project(workspace_id=workspace_id, project_id=project.id)
    for lineage in (False, True):
        request_body: dict[str, object] = {
            "project_id": project.id,
            "question": "Do not publicly create from private hourly evidence.",
            "mode": "plan",
            "expected_project_row_version": current_project.row_version,
            "dataset_id": record.id,
        }
        if lineage:
            request_body.update(
                {
                    "parent_run_id": run.id,
                    "seed_candidate_id": str(uuid4()),
                    "refinement_reason": "Keep the continuation boundary closed.",
                }
            )
        response = client.post(
            "/v1/quant/runs",
            headers=_headers(principal_id, workspace_id),
            json=request_body,
        )
        assert response.status_code == 409, response.text
        assert "/v1/quant/market-runs" in response.json()["error"]["message"]
        assert _persisted_workspace_state(workspace_id) == baseline


def test_market_agent_context_rejects_partial_and_inconsistent_v2_signals(
    client: TestClient,
    principal_id: str,
) -> None:
    store, workspace_id, record, project = _provision_runtime(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    run = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=project.id,
        question="Strictly validate the private hourly Agent context.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=project.row_version,
        dataset_id=record.id,
    )
    raw_context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    parsed = QuantAgentContext.model_validate(raw_context)
    worker_payload = json.loads(build_decision_messages(parsed)[1]["content"])["context"]
    assert worker_payload["dataset_summary"] == raw_context["dataset_summary"]

    partial = json.loads(json.dumps(raw_context))
    partial["dataset_summary"].pop("runtime_descriptor_digest")
    partial["dataset_summary"].pop("sealed_split_digest")
    partial["dataset_summary"]["holdout"] = {"result": "must stay sealed"}
    with pytest.raises(ValueError):
        QuantAgentContext.model_validate(partial)

    sealed_partition = json.loads(json.dumps(raw_context))
    sealed_partition["dataset_summary"]["evaluation_partition"] = "holdout"
    with pytest.raises(ValueError):
        QuantAgentContext.model_validate(sealed_partition)

    for bad_timestamp in (
        "2024-01-01",
        "2024-01-01T00:00:00",
        "2024-01-01T08:00:00+08:00",
        "not-a-timestamp",
        1_704_067_200,
    ):
        malformed = json.loads(json.dumps(raw_context))
        malformed["dataset_summary"]["start"] = bad_timestamp
        with pytest.raises(ValueError):
            QuantAgentContext.model_validate(malformed)

    inconsistent_mutations = (
        ("dataset_id", "another-dataset"),
        ("dataset_digest", "sha256:another-dataset-digest"),
        ("interval", "4h"),
        ("periods_per_year", 2_190),
    )
    for field, value in inconsistent_mutations:
        inconsistent = json.loads(json.dumps(raw_context))
        inconsistent["dataset_summary"]["split"][field] = value
        with pytest.raises(ValueError):
            QuantAgentContext.model_validate(inconsistent)

    mismatched_coverage = json.loads(json.dumps(raw_context))
    mismatched_coverage["dataset_summary"]["utc_coverage"]["start"] = "2023-12-31T23:00:00+00:00"
    with pytest.raises(ValueError):
        QuantAgentContext.model_validate(mismatched_coverage)

    out_of_range_train = json.loads(json.dumps(raw_context))
    out_of_range_train["dataset_summary"]["split"]["train_start"] = "2023-12-31T23:00:00+00:00"
    with pytest.raises(ValueError):
        QuantAgentContext.model_validate(out_of_range_train)


@pytest.mark.parametrize(
    ("interval", "expected_interval", "expected_periods_per_year"),
    [
        (QuantBarInterval.HOUR, BacktestInterval.HOUR, 8_760),
        (QuantBarInterval.FOUR_HOURS, BacktestInterval.FOUR_HOURS, 2_190),
    ],
)
def test_internal_market_runtime_uses_one_pinned_descriptor_for_all_evaluation(
    client: TestClient,
    principal_id: str,
    interval: QuantBarInterval,
    expected_interval: BacktestInterval,
    expected_periods_per_year: int,
) -> None:
    store, workspace_id, record, project = _provision_runtime(
        client, principal_id, interval=interval
    )
    run = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=project.id,
        question="Evaluate one interpretable trend strategy on the pinned cadence.",
        mode=QuantRunMode.AUTO,
        expected_project_row_version=project.row_version,
        dataset_id=record.id,
    )
    runtime = store._runtime_descriptor(run)  # pyright: ignore[reportPrivateUsage]
    split = _runtime_split(runtime)

    assert isinstance(runtime, QuantRuntimeDatasetDescriptor)
    assert runtime.interval is expected_interval
    assert runtime.periods_per_year == expected_periods_per_year
    assert runtime.dataset_digest == record.dataset.digest
    assert runtime.record_digest == record.record_digest
    assert runtime.coverage_start_utc == record.dataset.covered_start
    assert runtime.coverage_end_utc == record.dataset.covered_end
    assert runtime.descriptor_digest == run.runtime_descriptor_digest
    assert split.seal_digest == run.runtime_split_digest
    assert split.metadata["interval"] == interval.value
    assert split.metadata["periods_per_year"] == expected_periods_per_year
    assert split.metadata["range_start_utc"] == record.dataset.covered_start.isoformat()
    assert split.metadata["range_end_utc"] == record.dataset.covered_end.isoformat()
    assert all(isinstance(bar, MarketBar) for bar in runtime.bars)
    with pytest.raises(FrozenInstanceError):
        runtime.periods_per_year = 252  # type: ignore[misc]

    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="c3b1-runtime")
    assert claim is not None
    candidate, _, error = store.create_agent_candidate(
        claim,
        name="SMA 5/20",
        template="sma_crossover",
        hypothesis="A compact trend filter may reduce drawdown.",
        parameters={"fast_window": 5, "slow_window": 20},
    )
    assert error is None and candidate is not None
    run.state = QuantRunState.RUNNING_EXPERIMENTS
    completed, _, error = store.run_agent_backtest(claim, candidate_id=candidate.id)
    assert error is None and completed is not None

    execution = ExecutionConfig(fee_rate=0.001, slippage_rate=0.0005)
    expected_candidate = run_backtest(
        split.training_bars,
        StrategySpec.sma(5, 20),
        execution,
        cadence=runtime.cadence,
    )
    assert completed.metrics == store._metrics_projection(  # pyright: ignore[reportPrivateUsage]
        expected_candidate.metrics
    )

    second_candidate, _, error = store.create_agent_candidate(
        claim,
        name="Breakout 10",
        template="breakout",
        hypothesis="A short breakout provides a distinct training comparison.",
        parameters={"lookback_window": 10},
    )
    assert error is None and second_candidate is not None
    run.state = QuantRunState.RUNNING_EXPERIMENTS
    second_completed, _, error = store.run_agent_backtest(claim, candidate_id=second_candidate.id)
    assert error is None and second_completed is not None

    comparison, _, error = store.compare_agent_candidates(claim)
    assert error is None and comparison is not None
    expected_benchmark = backtest_buy_and_hold(
        split.training_bars, execution, cadence=runtime.cadence
    )
    assert comparison["benchmark"] == store._metrics_projection(  # pyright: ignore[reportPrivateUsage]
        expected_benchmark.metrics
    )
    assert comparison["evaluation_partition"] == "train"
    training_evidence = {key: value for key, value in comparison.items() if key != "split"}
    assert "holdout" not in json.dumps(training_evidence).lower()
    assert "candidate" not in json.dumps(comparison["split"]).lower()
    assert "benchmark" not in json.dumps(comparison["split"]).lower()
    feedback = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        if artifact.kind.value == "iteration_feedback"
    )
    assert feedback.content["evaluation_partition"] == "train"
    assert feedback.content["training_split"]["train_bar_count"] == split.split_index
    feedback_json = json.dumps(feedback.content).lower()
    assert "holdout" not in feedback_json
    assert "generalization" not in feedback_json

    walk_forward = comparison["candidates"][0]["walk_forward"]
    first_fold = walk_forward["folds"][0]
    history_count = first_fold["market_regime"]["history_bar_count"]
    evaluation_start = next(
        index
        for index, bar in enumerate(split.training_bars)
        if cast(MarketBar, bar).timestamp.isoformat() == first_fold["evaluation_start"]
    )
    history = split.training_bars[evaluation_start - history_count : evaluation_start]
    period_returns = [
        history[index].close / history[index - 1].close - 1 for index in range(1, len(history))
    ]
    average = sum(period_returns) / len(period_returns)
    deviation = math.sqrt(
        sum((value - average) ** 2 for value in period_returns) / len(period_returns)
    )
    assert first_fold["market_regime"]["annualized_volatility_pct"] == round(
        deviation * math.sqrt(expected_periods_per_year) * 100, 4
    )

    third_candidate, _, error = store.create_agent_candidate(
        claim,
        name="SMA 8/30",
        template="sma_crossover",
        hypothesis="Use the train-only comparison to test one distinct trend cadence.",
        parameters={"fast_window": 8, "slow_window": 30},
        change_rationale="The training comparison supports one bounded, canonical-distinct test.",
        replan_decision=QuantEvidenceReplanDecision(
            action=(
                "refine_parameters"
                if next(
                    item["template"]
                    for item in feedback.content["completed_candidates"]
                    if item["candidate_id"]
                    == feedback.content["improvement_reference"]["candidate_id"]
                )
                == "sma_crossover"
                else "switch_approved_family"
            ),
            source_comparison_artifact_id=feedback.content["comparison_artifact_id"],
            improvement_reference_candidate_id=feedback.content["improvement_reference"][
                "candidate_id"
            ],
        ),
    )
    assert error is None and third_candidate is not None
    run.state = QuantRunState.RUNNING_EXPERIMENTS
    third_completed, _, error = store.run_agent_backtest(claim, candidate_id=third_candidate.id)
    assert error is None and third_completed is not None
    final_comparison, _, error = store.compare_agent_candidates(claim)
    assert error is None and final_comparison is not None
    assert {item["candidate_id"] for item in final_comparison["candidates"]} == {
        candidate.id,
        second_candidate.id,
        third_candidate.id,
    }

    selected_candidate_id = final_comparison["ranking"][0]
    report, _, error = store.finish_agent_research(
        claim,
        selected_candidate_id=selected_candidate_id,
        conclusion="The training ranking selected the tested strategy.",
        next_step="review_holdout_evidence",
    )
    assert error is None and report is not None
    assert report["selected_candidate_id"] == selected_candidate_id
    assert report["generalization"]["split"]["seal_digest"] == split.seal_digest
    assert report["generalization"]["holdout"]["candidate"]
    assert report["generalization"]["holdout"]["benchmark"]
    assert (
        len(
            [
                artifact
                for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
                if artifact.kind.value == "research_report"
            ]
        )
        == 1
    )
    second_report, artifact_ids, second_error = store.finish_agent_research(
        claim,
        selected_candidate_id=selected_candidate_id,
        conclusion="Do not compute a second holdout.",
        next_step="stop",
    )
    assert second_report is None
    assert artifact_ids == []
    assert second_error == "STALE_CLAIM"
    store.release_agent_claim(claim)


@pytest.mark.parametrize(
    ("interval", "periods_per_year"),
    [
        (QuantBarInterval.HOUR, 8_760),
        (QuantBarInterval.FOUR_HOURS, 2_190),
    ],
)
def test_private_market_auto_run_projects_context_snapshot_report_export_and_history(
    client: TestClient,
    principal_id: str,
    interval: QuantBarInterval,
    periods_per_year: int,
) -> None:
    store, workspace_id, record, project = _provision_runtime(
        client, principal_id, interval=interval
    )
    run = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=project.id,
        question="Project one private timestamped research run without opening public creation.",
        mode=QuantRunMode.AUTO,
        expected_project_row_version=project.row_version,
        dataset_id=record.id,
    )
    start = record.dataset.covered_start.isoformat()
    end = record.dataset.covered_end.isoformat()
    expected_split_digest = run.runtime_split_digest

    initial = quant_agent_workspace_snapshot(workspace_id=workspace_id, run_id=run.id)
    assert initial is not None
    assert initial["scope"]["symbol"] == "BTCUSDT"
    assert initial["scope"]["interval"] == interval.value
    assert initial["scope"]["dateRange"] == {"start": start, "end": end}
    assert initial["scope"]["assumptions"][:2] == [
        f"320 {interval.value} OHLCV bars in the pinned UTC research range",
        f"{periods_per_year:,} periods per year for annualized metrics",
    ]
    assert initial["dataset"]["dateRange"] == {"start": start, "end": end}
    assert initial["dataset"]["interval"] == interval.value
    assert initial["dataset"]["periodsPerYear"] == periods_per_year
    assert initial["dataset"]["runtimeDescriptorDigest"] == run.runtime_descriptor_digest
    assert initial["dataset"]["sealedSplitDigest"] == expected_split_digest
    assert initial["dataset"]["quality"]["status"] == "accepted"
    assert initial["kernelCheck"]["engineVersion"] == "market-bar-kernel-v1"
    assert initial["kernelCheck"]["interval"] == interval.value
    assert initial["kernelCheck"]["periodsPerYear"] == periods_per_year
    assert initial["report"] is None
    assert initial["run"]["legalCommands"] == []
    assert initial["composerLegalCommands"] == []
    assert all("T" in row["date"] and row["date"].endswith("+00:00") for row in initial["bars"])

    def assert_train_only_agent_context() -> None:
        raw_context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
        parsed = QuantAgentContext.model_validate(raw_context)
        dataset_summary = QuantAgentMarketDatasetSummary.model_validate(parsed.dataset_summary)
        assert dataset_summary.periods_per_year == periods_per_year
        assert dataset_summary.utc_coverage.start == record.dataset.covered_start
        assert dataset_summary.utc_coverage.end == record.dataset.covered_end
        assert dataset_summary.runtime_descriptor_digest == run.runtime_descriptor_digest
        assert dataset_summary.sealed_split_digest == expected_split_digest
        assert dataset_summary.evaluation_partition == "train"
        assert dataset_summary.split.train_bar_count == 256
        assert not {
            "holdout",
            "holdout_start",
            "holdout_end",
            "holdout_bar_count",
            "generalization",
            "validation",
        }.intersection(_nested_keys(parsed.dataset_summary))
        if parsed.iteration_feedback is not None:
            assert not {"holdout", "generalization", "validation"}.intersection(
                _nested_keys(parsed.iteration_feedback.model_dump(mode="json"))
            )
        worker_payload = json.loads(build_decision_messages(parsed)[1]["content"])["context"]
        assert worker_payload["dataset_summary"] == raw_context["dataset_summary"]
        assert not {"holdout", "generalization", "validation"}.intersection(
            _nested_keys(worker_payload["dataset_summary"])
        )
        unsafe_context = json.loads(json.dumps(raw_context))
        unsafe_context["dataset_summary"]["split"]["holdout_start"] = start
        with pytest.raises(ValueError, match="holdout_start"):
            QuantAgentContext.model_validate(unsafe_context)

    assert_train_only_agent_context()
    provider = MockQuantAgentProvider()
    action_count = 0
    for _ in range(12):
        if not run_quant_agent_once(
            store=store,
            provider=provider,
            workspace_id=workspace_id,
            worker_id=f"c3b2a-{interval.value}",
        ):
            break
        action_count += 1
        current = store.get_run(workspace_id=workspace_id, run_id=run.id)
        if current.state is QuantRunState.COMPLETED:
            break
        assert_train_only_agent_context()
        running_snapshot = quant_agent_workspace_snapshot(workspace_id=workspace_id, run_id=run.id)
        assert running_snapshot is not None
        assert running_snapshot["report"] is None
    completed = store.get_run(workspace_id=workspace_id, run_id=run.id)
    assert completed.state is QuantRunState.COMPLETED
    assert action_count <= 12

    reports = [
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        if artifact.kind.value == "research_report"
    ]
    assert len(reports) == 1
    report = reports[0].content
    selected_candidate_id = str(report["selected_candidate_id"])
    assert report["dataset"]["interval"] == interval.value
    assert report["dataset"]["periods_per_year"] == periods_per_year
    assert report["dataset"]["sealed_split_digest"] == expected_split_digest
    assert report["generalization"]["split"]["seal_digest"] == expected_split_digest
    assert report["generalization"]["holdout"]["candidate"]

    completed_snapshot = quant_agent_workspace_snapshot(workspace_id=workspace_id, run_id=run.id)
    assert completed_snapshot is not None
    assert completed_snapshot["run"]["state"] == "completed"
    assert completed_snapshot["report"]["datasetContext"] == {
        "symbol": "BTCUSDT",
        "interval": interval.value,
        "periodsPerYear": periods_per_year,
        "range": {"start": start, "end": end},
        "runtimeDescriptorDigest": run.runtime_descriptor_digest,
        "sealedSplitDigest": expected_split_digest,
    }
    generalization_split = completed_snapshot["report"]["generalization"]["split"]
    assert generalization_split["interval"] == interval.value
    assert generalization_split["periodsPerYear"] == periods_per_year
    assert generalization_split["sealDigest"] == expected_split_digest
    assert completed_snapshot["report"]["generalization"]["holdout"]["candidate"]
    assert all(
        point["date"].endswith("+00:00")
        for series in completed_snapshot["performanceSeries"]
        for point in series["points"]
    )
    assert all(
        trade["entryDate"].endswith("+00:00") and trade["exitDate"].endswith("+00:00")
        for trade in completed_snapshot["trades"]
    )
    assert all(
        isinstance(trade["holdingBars"], int)
        and isinstance(trade["holdingElapsedSeconds"], int)
        and "holdingDays" not in trade
        for trade in completed_snapshot["trades"]
    )
    marker_dates = {row["date"] for row in completed_snapshot["bars"] if row.get("marker")}
    selected_trade_dates = {
        trade[key]
        for trade in completed_snapshot["trades"]
        if trade["candidateId"] == selected_candidate_id
        for key in ("entryDate", "exitDate")
    }
    assert marker_dates == selected_trade_dates

    current_response = client.get(
        "/v1/quant/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert current_response.status_code == 200, current_response.text
    assert current_response.json()["run"]["id"] == run.id
    assert current_response.json()["report"] == completed_snapshot["report"]

    exported = build_strategy_report_export(
        workspace_id=workspace_id,
        run_id=run.id,
        candidate_id=selected_candidate_id,
    )
    markdown = str(exported["rendered_content"])
    assert f"- Dataset: BTCUSDT · {interval.value}" in markdown
    assert f"- Research range: {start} to {end}" in markdown
    assert f"- Annualization: {periods_per_year} periods per year" in markdown
    assert "Cutoff timestamp:" in markdown
    for trade in completed_snapshot["trades"]:
        if trade["candidateId"] == selected_candidate_id:
            assert f"{trade['holdingBars']} bars ·" in markdown
            break
    assert "daily OHLCV" not in markdown
    export_response = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers=_headers(principal_id, workspace_id),
        json={
            "export_type": "strategy_report_markdown",
            "run_id": run.id,
            "candidate_id": selected_candidate_id,
        },
    )
    assert export_response.status_code == 200, export_response.text
    assert export_response.json()["rendered_content"] == markdown
    assert export_response.json()["content_digest"] == exported["content_digest"]

    historical_response = client.get(
        f"/v1/quant/runs/{run.id}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert historical_response.status_code == 200, historical_response.text
    historical = historical_response.json()
    assert historical["run"]["id"] == run.id
    assert historical["dataset"]["digest"] == record.dataset.digest
    assert historical["dataset"]["periodsPerYear"] == periods_per_year
    assert historical["report"]["id"] == completed_snapshot["report"]["id"]
    assert historical["report"]["generalization"] == completed_snapshot["report"]["generalization"]

    reloaded_store = QuantStore()
    reloaded_run = reloaded_store.get_run(workspace_id=workspace_id, run_id=run.id)
    reloaded_projection = reloaded_store.runtime_projection(reloaded_run)
    assert reloaded_projection.descriptor.descriptor_digest == run.runtime_descriptor_digest
    assert reloaded_projection.split.seal_digest == expected_split_digest
    reloaded_snapshot = quant_agent_workspace_snapshot(workspace_id=workspace_id, run_id=run.id)
    assert reloaded_snapshot is not None
    assert reloaded_snapshot["report"] == completed_snapshot["report"]
    assert reloaded_snapshot["performanceSeries"] == completed_snapshot["performanceSeries"]

    with pytest.raises(ApiError, match="public mutations remain disabled"):
        store.retry_run(
            workspace_id=workspace_id,
            run_id=run.id,
            expected_row_version=completed.row_version,
            reason="The public retry boundary remains closed.",
        )
    retry = store._retry_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        run_id=run.id,
        expected_row_version=completed.row_version,
        reason="Verify private projection identity on a clean attempt.",
    )
    retry_snapshot = quant_agent_workspace_snapshot(workspace_id=workspace_id, run_id=retry.id)
    assert retry_snapshot is not None
    assert retry_snapshot["dataset"]["runtimeDescriptorDigest"] == run.runtime_descriptor_digest
    assert retry_snapshot["dataset"]["sealedSplitDigest"] == expected_split_digest
    assert retry_snapshot["report"] is None
    assert retry_snapshot["performanceSeries"] == []
    assert retry_snapshot["run"]["legalCommands"] == []
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=retry.id) == []
    assert (
        len(
            [
                artifact
                for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
                if artifact.kind.value == "research_report"
            ]
        )
        == 1
    )
    blocked_command = client.post(
        "/v1/quant/workspace-snapshot/commands",
        headers=_headers(principal_id, workspace_id),
        json={
            "command": "cancel_run",
            "expected_row_version": retry.row_version,
            "payload": {},
        },
    )
    assert blocked_command.status_code == 409, blocked_command.text
    assert "public mutations remain disabled" in blocked_command.json()["error"]["message"]


def test_internal_market_runtime_rejects_quality_range_metadata_and_float_failures(
    client: TestClient, principal_id: str
) -> None:
    short_store, workspace_id, short_record, short_project = _provision_runtime(
        client, principal_id, interval=QuantBarInterval.HOUR, count=120
    )
    with pytest.raises(ApiError, match="at least 252 market bars"):
        short_store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
            workspace_id=workspace_id,
            project_id=short_project.id,
            question="Reject a short runtime range.",
            mode=QuantRunMode.AUTO,
            expected_project_row_version=short_project.row_version,
            dataset_id=short_record.id,
        )

    gap_store, gap_workspace, gap_record, gap_project = _provision_runtime(
        client,
        principal_id,
        interval=QuantBarInterval.FOUR_HOURS,
        count=320,
        gap_after=200,
    )
    assert gap_record.quality.status == "blocked"
    with pytest.raises(ApiError, match="accepted, cadence-consistent"):
        gap_store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
            workspace_id=gap_workspace,
            project_id=gap_project.id,
            question="Reject a retained cadence gap.",
            mode=QuantRunMode.AUTO,
            expected_project_row_version=gap_project.row_version,
            dataset_id=gap_record.id,
        )

    valid_store, valid_workspace, valid_record, valid_project = _provision_runtime(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    with pytest.raises(ApiError, match="complete UTC dataset coverage"):
        valid_store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
            workspace_id=valid_workspace,
            project_id=valid_project.id,
            question="Reject a partial or misaligned internal range.",
            mode=QuantRunMode.AUTO,
            expected_project_row_version=valid_project.row_version,
            dataset_id=valid_record.id,
            research_start_utc=valid_record.dataset.covered_start + timedelta(minutes=1),
            research_end_utc=valid_record.dataset.covered_end,
        )

    unknown_dataset = daily_bar_dataset_to_market_dataset(SPY_DAILY_FIXTURE)
    unknown_evidence = QuantMarketDatasetEvidence(
        source_kind=QuantMarketDataProvenance.CSV_UPLOAD,
        source_name="Legacy adapter verification",
        submitted_csv_digest="sha256:" + "a" * 64,
        normalizer_version="legacy-adapter-test-v1",
    )
    unknown_record = valid_store.import_market_dataset_v2(
        workspace_id=valid_workspace,
        name="Unknown cadence metadata",
        dataset=unknown_dataset,
        evidence=unknown_evidence,
        quality=QuantMarketDatasetCadenceQuality(
            status="accepted",
            cadence_gap_count=0,
            normalization_note="Metadata eligibility is checked by the runtime resolver.",
        ),
    )
    current_project = valid_store.get_project(
        workspace_id=valid_workspace, project_id=valid_project.id
    )
    with pytest.raises(ApiError, match="periods_per_year"):
        valid_store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
            workspace_id=valid_workspace,
            project_id=valid_project.id,
            question="Reject unknown annualization metadata.",
            mode=QuantRunMode.AUTO,
            expected_project_row_version=current_project.row_version,
            dataset_id=unknown_record.id,
        )

    with pytest.raises(ValueError, match="finite float"):
        _decimal_to_runtime_float(Decimal("1e10000"), field_name="close")


def test_market_runtime_retry_and_restore_keep_descriptor_and_split_identity(
    client: TestClient, principal_id: str
) -> None:
    store, workspace_id, record, project = _provision_runtime(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS
    )
    run = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=project.id,
        question="Retry the same pinned market runtime evidence.",
        mode=QuantRunMode.AUTO,
        expected_project_row_version=project.row_version,
        dataset_id=record.id,
    )
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="c3b1-retry-source")
    assert claim is not None
    source_candidate, _, error = store.create_agent_candidate(
        claim,
        name="Source SMA 5/20",
        template="sma_crossover",
        hypothesis="Source-attempt evidence must not enter its retry.",
        parameters={"fast_window": 5, "slow_window": 20},
    )
    assert error is None and source_candidate is not None
    cancelled = store._cancel_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        run_id=run.id,
        expected_row_version=run.row_version,
        reason="Prepare a deterministic internal retry.",
    )
    with pytest.raises(ApiError, match="public mutations remain disabled"):
        store.retry_run(
            workspace_id=workspace_id,
            run_id=run.id,
            expected_row_version=cancelled.row_version,
            reason="The public gate remains closed.",
        )

    child = store._retry_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        run_id=run.id,
        expected_row_version=cancelled.row_version,
        reason="Retry only through the internal runtime boundary.",
    )
    assert child.retry_of_run_id == run.id
    assert child.dataset_id == run.dataset_id
    assert child.dataset_digest == run.dataset_digest
    assert child.research_start_utc == run.research_start_utc
    assert child.research_end_utc == run.research_end_utc
    assert child.runtime_interval is run.runtime_interval
    assert child.runtime_periods_per_year == run.runtime_periods_per_year
    assert child.runtime_descriptor_digest == run.runtime_descriptor_digest
    assert child.runtime_split_digest == run.runtime_split_digest
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=child.id) == []
    assert all(
        artifact.kind.value == "plan"
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=child.id)
    )

    restored_store = QuantStore()
    restored_child = restored_store.get_run(workspace_id=workspace_id, run_id=child.id)
    restored_runtime = restored_store._runtime_descriptor(  # pyright: ignore[reportPrivateUsage]
        restored_child
    )
    restored_split = _runtime_split(restored_runtime)
    assert restored_runtime.descriptor_digest == child.runtime_descriptor_digest
    assert restored_split.seal_digest == child.runtime_split_digest

    state = restored_store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    tampered = cast(dict[str, Any], json.loads(json.dumps(state)))
    market_run = next(item for item in tampered["runs"] if item["id"] == child.id)
    market_run["runtime_periods_per_year"] = 252
    with pytest.raises(ValueError, match="runtime pins"):
        QuantStore()._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, tampered
        )


def test_market_runtime_retry_of_completed_source_skips_holdout_evaluators(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, workspace_id, record, project = _provision_runtime(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS, count=600
    )
    source = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=project.id,
        question="Consume a sealed holdout before retrying the same split.",
        mode=QuantRunMode.AUTO,
        expected_project_row_version=project.row_version,
        dataset_id=record.id,
    )
    source_claim, source_selected_candidate_id = _prepare_runtime_run_for_finish(
        store,
        workspace_id=workspace_id,
        run_id=source.id,
        worker_id="g2-runtime-source",
    )
    source_report, _, error = store.finish_agent_research(
        source_claim,
        selected_candidate_id=source_selected_candidate_id,
        conclusion="Consume the source holdout before retry.",
        next_step="review_holdout_evidence",
    )
    assert error is None and source_report is not None
    store.release_agent_claim(source_claim)

    retry = store._retry_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        run_id=source.id,
        expected_row_version=store.get_run(workspace_id=workspace_id, run_id=source.id).row_version,
        reason="Retry the same pinned holdout range after completion.",
    )
    retry_claim, retry_selected_candidate_id = _prepare_runtime_run_for_finish(
        store,
        workspace_id=workspace_id,
        run_id=retry.id,
        worker_id="g2-runtime-retry",
    )
    descriptor = store._runtime_descriptor(retry)  # pyright: ignore[reportPrivateUsage]
    split = _runtime_split(descriptor)
    calls = {"holdout_backtest": 0, "holdout_benchmark": 0}
    original_run_backtest = quant_store_module.run_backtest
    original_buy_and_hold = quant_store_module.backtest_buy_and_hold

    def count_holdout_backtest(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("measurement_start_index") == split.split_index:
            calls["holdout_backtest"] += 1
        return original_run_backtest(*args, **kwargs)

    def count_holdout_benchmark(bars: Any, *args: Any, **kwargs: Any) -> Any:
        if len(bars) == len(split.all_bars) - split.split_index:
            calls["holdout_benchmark"] += 1
        return original_buy_and_hold(bars, *args, **kwargs)

    monkeypatch.setattr(quant_store_module, "run_backtest", count_holdout_backtest)
    monkeypatch.setattr(quant_store_module, "backtest_buy_and_hold", count_holdout_benchmark)

    report, _, error = store.finish_agent_research(
        retry_claim,
        selected_candidate_id=retry_selected_candidate_id,
        conclusion="Do not reopen an already-consumed holdout.",
        next_step="review_holdout_evidence",
    )
    assert error is None and report is not None
    assert calls == {"holdout_backtest": 0, "holdout_benchmark": 0}
    assert report["generalization"]["holdout_evidence_state"] == "development_only"
    assert report["generalization"]["status"] == "not_evaluated"
    assert "holdout" not in report["generalization"]
    assert report["next_step"] == "collect_more_evidence"


def test_market_runtime_retry_after_cancelled_source_keeps_fresh_holdout(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, workspace_id, record, project = _provision_runtime(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS, count=600
    )
    source = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=project.id,
        question="Retry a cancelled run that never evaluated holdout evidence.",
        mode=QuantRunMode.AUTO,
        expected_project_row_version=project.row_version,
        dataset_id=record.id,
    )
    cancelled = store._cancel_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        run_id=source.id,
        expected_row_version=source.row_version,
        reason="Cancel before any evaluated report exists.",
    )
    retry = store._retry_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        run_id=source.id,
        expected_row_version=cancelled.row_version,
        reason="Retry the never-evaluated terminal source.",
    )
    retry_claim, retry_selected_candidate_id = _prepare_runtime_run_for_finish(
        store,
        workspace_id=workspace_id,
        run_id=retry.id,
        worker_id="g2-runtime-cancelled-retry",
    )
    descriptor = store._runtime_descriptor(retry)  # pyright: ignore[reportPrivateUsage]
    split = _runtime_split(descriptor)
    calls = {"holdout_backtest": 0, "holdout_benchmark": 0}
    original_run_backtest = quant_store_module.run_backtest
    original_buy_and_hold = quant_store_module.backtest_buy_and_hold

    def count_holdout_backtest(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("measurement_start_index") == split.split_index:
            calls["holdout_backtest"] += 1
        return original_run_backtest(*args, **kwargs)

    def count_holdout_benchmark(bars: Any, *args: Any, **kwargs: Any) -> Any:
        if len(bars) == len(split.all_bars) - split.split_index:
            calls["holdout_benchmark"] += 1
        return original_buy_and_hold(bars, *args, **kwargs)

    monkeypatch.setattr(quant_store_module, "run_backtest", count_holdout_backtest)
    monkeypatch.setattr(quant_store_module, "backtest_buy_and_hold", count_holdout_benchmark)

    report, _, error = store.finish_agent_research(
        retry_claim,
        selected_candidate_id=retry_selected_candidate_id,
        conclusion="This retry still has a fresh holdout.",
        next_step="review_holdout_evidence",
    )
    assert error is None and report is not None
    assert calls == {"holdout_backtest": 1, "holdout_benchmark": 1}
    assert report["generalization"]["holdout_evidence_state"] == "fresh_sealed"
    assert report["generalization"]["holdout"]["candidate"]


def test_legacy_daily_run_keeps_its_original_serialized_and_runtime_boundary(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "C3B1 daily compatibility")
    store = QuantStore()
    project = store.create_project(
        workspace_id=workspace_id,
        name="Daily compatibility",
        objective="Keep the established DailyBar and 252 path unchanged.",
    )
    run = store.create_run(
        workspace_id=workspace_id,
        project_id=project.id,
        question="Verify the legacy daily runtime boundary.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=project.row_version,
    )
    runtime = store._runtime_descriptor(run)  # pyright: ignore[reportPrivateUsage]
    split = _runtime_split(runtime)
    persisted_run = next(
        item
        for item in store._workspace_state(  # pyright: ignore[reportPrivateUsage]
            workspace_id
        )["runs"]
        if item["id"] == run.id
    )

    assert runtime.interval is BacktestInterval.DAILY
    assert runtime.periods_per_year == 252
    assert runtime.cadence is None
    assert split.seal_digest is None
    assert "seal_digest" not in split.metadata
    assert not {
        "research_start_utc",
        "research_end_utc",
        "runtime_interval",
        "runtime_periods_per_year",
        "runtime_descriptor_digest",
        "runtime_split_digest",
    }.intersection(persisted_run)
    public_response = store.to_run_response(run)
    assert "runtime_interval" not in public_response
    assert "research_start_utc" not in public_response
    raw_context = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)
    parsed_context = QuantAgentContext.model_validate(raw_context)
    worker_context = json.loads(build_decision_messages(parsed_context)[1]["content"])["context"]
    assert worker_context["dataset_summary"] == raw_context["dataset_summary"]
    assert raw_context["dataset_summary"]["interval"] == "1D"
    assert "periods_per_year" not in raw_context["dataset_summary"]
