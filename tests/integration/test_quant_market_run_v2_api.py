from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from packages.contracts.quant import (
    QuantAgentAction,
    QuantAgentDecision,
    QuantBarInterval,
    QuantResearchDecision,
    QuantResearchDecisionDeviation,
    QuantResearchSeriesDecision,
    QuantRunMode,
    QuantRunState,
)
from services.api.app.api import routes_quant
from services.api.app.core.errors import ApiError
from services.api.app.db.models import QuantRepositoryState
from services.api.app.modules.quant.store import QuantRunRecord, QuantStore
from services.worker.app.pipelines.quant_agent import run_quant_agent_once


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


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


def _eligible_market_count(interval: QuantBarInterval) -> int:
    return {
        QuantBarInterval.HOUR: 2190,
        QuantBarInterval.FOUR_HOURS: 548,
        QuantBarInterval.DAILY: 252,
    }[interval]


def _provision(
    client: TestClient,
    principal_id: str,
    *,
    interval: QuantBarInterval,
    count: int | None = None,
    gap_after: int | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    workspace_id = _workspace(
        client, principal_id, f"Market run {interval.value} {uuid4().hex[:8]}"
    )
    dataset_response = client.post(
        "/v1/quant/datasets/v2/import-csv",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": f"BTCUSDT {interval.value}",
            "symbol": "BTCUSDT",
            "interval": interval.value,
            "csv_text": _market_csv(
                interval,
                _eligible_market_count(interval) if count is None else count,
                gap_after=gap_after,
            ),
            "file_name": f"btcusdt-{interval.value}.csv",
            "source_name": "Controlled market CSV",
            "source_reference": f"test:{interval.value}",
        },
    )
    assert dataset_response.status_code == 201, dataset_response.text
    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": f"Market research {interval.value}",
            "objective": "Verify the public cadence-aware research boundary.",
        },
    )
    assert project_response.status_code == 201, project_response.text
    return workspace_id, dataset_response.json(), project_response.json()


def _create_body(
    dataset: dict[str, Any], project: dict[str, Any], *, mode: str = "plan"
) -> dict[str, Any]:
    return {
        "project_id": project["id"],
        "mode": mode,
        "question": "Research an interpretable cadence-aware strategy.",
        "expected_project_row_version": project["row_version"],
        "dataset_id": dataset["dataset_id"],
        "research_start_utc": dataset["covered_start"],
        "research_end_utc": dataset["covered_end"],
    }


def test_public_market_research_loop_precommits_exactly_one_train_only_follow_up(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client,
        principal_id,
        interval=QuantBarInterval.FOUR_HOURS,
    )
    body = _create_body(dataset, project, mode="auto")
    body["research_loop"] = {
        "follow_up_mode": "one_train_only_follow_up",
        "max_versions": 2,
        "max_total_experiments": 6,
        "max_total_agent_actions": 24,
    }
    created_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=body,
    )
    assert created_response.status_code == 201, created_response.text
    root = created_response.json()
    assert root["research_series"]["version_number"] == 1
    assert root["research_series"]["remaining_versions"] == 1

    actions = 0
    while actions < 24 and run_quant_agent_once(workspace_id=workspace_id):
        actions += 1
    assert actions == 22

    directory_response = client.get(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
    )
    assert directory_response.status_code == 200, directory_response.text
    runs = directory_response.json()
    assert len(runs) == 2
    root_after = next(item for item in runs if item["id"] == root["id"])
    child = next(item for item in runs if item["id"] != root["id"])
    assert root_after["state"] == QuantRunState.COMPLETED.value
    assert child["state"] == QuantRunState.COMPLETED.value
    assert child["parent_run_id"] == root["id"]
    assert child["seed_candidate_id"] is not None
    assert child["research_series"]["root_run_id"] == root["id"]
    assert child["research_series"]["version_number"] == 2
    assert child["research_series"]["remaining_versions"] == 0
    assert child["research_series"]["allowed_actions"] == ["finish_without_follow_up"]

    store = QuantStore()
    root_candidates = store.experiments_for_run(workspace_id=workspace_id, run_id=root["id"])
    child_candidates = store.experiments_for_run(workspace_id=workspace_id, run_id=child["id"])
    root_record = store.get_run(workspace_id=workspace_id, run_id=root["id"])
    child_record = store.get_run(workspace_id=workspace_id, run_id=child["id"])
    assert child_record.strategy_scope.model_dump(
        mode="json"
    ) == root_record.strategy_scope.model_dump(mode="json")
    assert child_record.repair_memory is not None
    assert child_record.repair_memory.model_dump(mode="json") == store._build_repair_memory_pin(  # pyright: ignore[reportPrivateUsage]
        child_record
    ).model_dump(mode="json")
    root_keys = {item.candidate_key for item in root_candidates if item.candidate_key}
    child_keys = {item.candidate_key for item in child_candidates if item.candidate_key}
    assert len(root_keys) == 3
    assert len(child_keys) == 3
    assert root_keys.isdisjoint(child_keys)

    root_report = next(
        item
        for item in store.artifacts_for_run(workspace_id=workspace_id, run_id=root["id"])
        if item.kind.value == "research_report"
    )
    assert root_report.content["run_metadata"]["precommitted_follow_up_run_id"] == child["id"]
    assert root_report.content["generalization"]["holdout_evidence_state"] == "fresh_sealed"
    assert root_report.content["generalization"]["holdout"]

    child_report = next(
        item
        for item in store.artifacts_for_run(workspace_id=workspace_id, run_id=child["id"])
        if item.kind.value == "research_report"
    )
    assert child_report.content["generalization"]["holdout_evidence_state"] == "not_evaluated"
    assert child_report.content["generalization"]["status"] == "not_evaluated"
    assert "holdout" not in child_report.content["generalization"]
    assert child_report.content["next_step"] == "collect_more_evidence"
    assert "Holdout metrics were computed after selection." not in json.dumps(
        child_report.content["limitations"]
    )

    retry_response = client.post(
        f"/v1/quant/market-runs/{root['id']}/retry",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": root_after["row_version"],
            "reason": "Retry the root attempt without reopening the series budget.",
        },
    )
    assert retry_response.status_code == 409, retry_response.text
    assert "bounded research series" in retry_response.text
    assert len(QuantStore().list_market_runs(workspace_id=workspace_id)) == 2


def test_supported_override_precommits_selected_series_child_and_fresh_restores(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, dataset, project = _provision(
        client,
        principal_id,
        interval=QuantBarInterval.FOUR_HOURS,
    )
    body = _create_body(dataset, project, mode="auto")
    body["research_loop"] = {
        "follow_up_mode": "one_train_only_follow_up",
        "max_versions": 2,
        "max_total_experiments": 6,
        "max_total_agent_actions": 24,
    }
    created = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=body,
    ).json()
    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    for _ in range(9):
        assert run_quant_agent_once(store=store, workspace_id=workspace_id)
    run = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    completed = [
        item
        for item in store.experiments_for_run(workspace_id=workspace_id, run_id=run.id)
        if item.state == "completed"
    ]
    ranked = sorted(
        completed,
        key=lambda item: store._comparison_ranking_key(  # pyright: ignore[reportPrivateUsage]
            {"candidate_id": item.id, **item.metrics},
            run.selection_objective,
        ),
        reverse=True,
    )
    objective_leader, override_candidate = ranked[:2]
    override_spec = store._strategy_spec(  # pyright: ignore[reportPrivateUsage]
        override_candidate.template, override_candidate.parameters
    )
    original_walk_forward = store._walk_forward_candidate  # pyright: ignore[reportPrivateUsage]

    def decisive_walk_forward(*args: Any, **kwargs: Any) -> dict[str, Any]:
        projected = original_walk_forward(*args, **kwargs)
        strategy = args[1]
        for fold in projected["folds"]:
            fold["status"] = "pass" if strategy == override_spec else "fail"
        return projected

    monkeypatch.setattr(store, "_walk_forward_candidate", decisive_walk_forward)
    assert run_quant_agent_once(store=store, workspace_id=workspace_id)
    comparison = store.agent_context_data(workspace_id=workspace_id, run_id=run.id)[
        "latest_comparison"
    ]
    assert comparison["ranking"][0] == objective_leader.id
    assert (
        next(
            item
            for item in comparison["candidates"]
            if item["candidate_id"] == override_candidate.id
        )["walk_forward_pass_folds"]
        == 3
    )
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="p19-override")
    assert lease is not None
    research_decision = QuantResearchDecision(
        selected_candidate_id=override_candidate.id,
        source_comparison_artifact_id=comparison["artifact_id"],
        decision_basis="robustness_override",
        deviation=QuantResearchDecisionDeviation(
            reason="walk_forward_stability",
            reference_candidate_id=objective_leader.id,
        ),
    )
    series_decision = QuantResearchSeriesDecision(
        action="refine_selected",
        source_comparison_artifact_id=comparison["artifact_id"],
        seed_candidate_id=override_candidate.id,
        focus="improve_walk_forward_stability",
        refinement_reason="Refine the server-validated robust selection once.",
    )
    report, _, error = store.finish_agent_research(
        lease,
        selected_candidate_id=override_candidate.id,
        conclusion="Use the uniquely strongest walk-forward candidate.",
        next_step="stop",
        series_decision=series_decision,
        research_decision=research_decision,
    )
    assert error is None and report is not None
    assert report["research_decision"] == research_decision.model_dump(mode="json")
    assert report["generalization"]["selected_candidate_id"] == override_candidate.id
    child_id = report["run_metadata"]["precommitted_follow_up_run_id"]
    assert child_id is not None
    assert store.get_run(workspace_id=workspace_id, run_id=child_id).seed_candidate_id == (
        override_candidate.id
    )
    restored = QuantStore()
    assert restored.get_run(workspace_id=workspace_id, run_id=run.id).state.value == "completed"
    assert (
        restored.get_run(workspace_id=workspace_id, run_id=child_id).seed_candidate_id
        == override_candidate.id
    )
    restored_report = next(
        item
        for item in restored.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
        if item.kind.value == "research_report"
    )
    assert restored_report.content["research_decision"] == research_decision.model_dump(mode="json")


def test_research_loop_finish_restores_child_precommit_on_later_failure(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, dataset, project = _provision(
        client,
        principal_id,
        interval=QuantBarInterval.FOUR_HOURS,
    )
    body = _create_body(dataset, project, mode="auto")
    body["research_loop"] = {
        "follow_up_mode": "one_train_only_follow_up",
        "max_versions": 2,
        "max_total_experiments": 6,
        "max_total_agent_actions": 24,
    }
    created = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=body,
    ).json()
    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    for _ in range(10):
        assert run_quant_agent_once(store=store, workspace_id=workspace_id)

    original = store._precommit_research_series_child  # pyright: ignore[reportPrivateUsage]

    def fail_after_child_precommit(**kwargs: Any) -> QuantRunRecord:
        original(**kwargs)
        raise RuntimeError("injected post-child finish failure")

    monkeypatch.setattr(store, "_precommit_research_series_child", fail_after_child_precommit)
    assert run_quant_agent_once(store=store, workspace_id=workspace_id)

    root = store.get_run(workspace_id=workspace_id, run_id=created["id"])
    assert root.state == QuantRunState.RUNNING_EXPERIMENTS
    assert root.research_series_child_run_id is None
    assert root.research_series_decision is None
    assert [
        run for run in store.list_market_runs(workspace_id=workspace_id) if run.id != root.id
    ] == []

    restored_root = QuantStore().get_run(workspace_id=workspace_id, run_id=root.id)
    assert restored_root.research_series_child_run_id is None
    assert restored_root.research_series_decision is None


def _complete_public_market_source(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    dataset: dict[str, Any],
    project: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project, mode="auto"),
    )
    assert response.status_code == 201, response.text
    source = response.json()
    actions = 0
    while actions < 12 and run_quant_agent_once(workspace_id=workspace_id):
        actions += 1
    completed = client.get(
        f"/v1/quant/market-runs/{source['id']}",
        headers=_headers(principal_id, workspace_id),
    )
    assert completed.status_code == 200, completed.text
    source = completed.json()
    assert source["state"] == QuantRunState.COMPLETED.value
    candidates = QuantStore().experiments_for_run(workspace_id=workspace_id, run_id=source["id"])
    seed = next(candidate for candidate in candidates if candidate.state == "completed")
    return source, seed


def _create_legacy_run(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    *,
    mode: str,
    label: str,
) -> dict[str, Any]:
    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": f"Legacy lease {label}",
            "objective": "Exercise run-scoped worker lease isolation.",
        },
    )
    assert project_response.status_code == 201, project_response.text
    project = project_response.json()
    run_response = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "mode": mode,
            "question": f"Legacy worker lease isolation {label}.",
            "expected_project_row_version": project["row_version"],
        },
    )
    assert run_response.status_code == 201, run_response.text
    return run_response.json()


def _agent_decision() -> QuantAgentDecision:
    return QuantAgentDecision(
        action=QuantAgentAction.INSPECT_RESEARCH_CONTEXT,
        arguments={},
        decision_summary="Continue the lease isolation probe.",
        expected_result="The owning Run retains its fenced write.",
    )


def _persisted_state(workspace_id: str) -> dict[str, Any]:
    store = QuantStore()
    store.list_projects(workspace_id=workspace_id)
    return store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]


def _fail_next_persist(
    monkeypatch: pytest.MonkeyPatch,
    store: QuantStore,
    *,
    after_commit: bool = False,
) -> None:
    original = store._persist_workspace  # pyright: ignore[reportPrivateUsage]
    pending = True

    def fail_once(workspace_id: str) -> None:
        nonlocal pending
        if pending:
            pending = False
            if after_commit:
                original(workspace_id)
            raise RuntimeError("injected market-run persist failure")
        original(workspace_id)

    monkeypatch.setattr(store, "_persist_workspace", fail_once)
    monkeypatch.setattr(routes_quant, "_store", lambda: store)


@pytest.mark.parametrize(
    ("interval", "periods_per_year"),
    [
        (QuantBarInterval.HOUR, 8_760),
        (QuantBarInterval.FOUR_HOURS, 2_190),
        (QuantBarInterval.DAILY, 365),
    ],
)
def test_public_market_run_plan_create_read_reload_and_legacy_separation(
    client: TestClient,
    principal_id: str,
    interval: QuantBarInterval,
    periods_per_year: int,
) -> None:
    workspace_id, dataset, project = _provision(client, principal_id, interval=interval)
    assert dataset["research_eligible"] is True

    response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project),
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["schema_version"] == "quant-market-run-v2"
    assert run["dataset_id"] == dataset["dataset_id"]
    assert run["dataset_digest"] == dataset["digest"]
    assert run["symbol"] == "BTCUSDT"
    assert run["interval"] == interval.value
    assert run["periods_per_year"] == periods_per_year
    assert run["research_start_utc"] == dataset["covered_start"]
    assert run["research_end_utc"] == dataset["covered_end"]
    assert run["runtime_descriptor_digest"].startswith("sha256:")
    assert run["sealed_split_digest"].startswith("sha256:")
    assert run["state"] == "waiting_plan_approval"
    assert not ({"holdout", "generalization", "validation"} & set(run))

    read = client.get(
        f"/v1/quant/market-runs/{run['id']}",
        headers=_headers(principal_id, workspace_id),
    )
    assert read.status_code == 200, read.text
    assert read.json() == run
    listed = client.get("/v1/quant/market-runs", headers=_headers(principal_id, workspace_id))
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [run["id"]]
    reloaded_store = QuantStore()
    restored = reloaded_store.get_market_run(workspace_id=workspace_id, run_id=run["id"])
    assert restored.market_run_contract_version == "quant-market-run-v2"
    assert restored.runtime_descriptor_digest == run["runtime_descriptor_digest"]
    assert restored.runtime_split_digest == run["sealed_split_digest"]
    persisted = reloaded_store._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    tampered = json.loads(json.dumps(persisted))
    next(item for item in tampered["runs"] if item["id"] == run["id"])[
        "market_run_contract_version"
    ] = "unknown-market-run-v9"
    with pytest.raises(ValueError, match="contract version"):
        QuantStore()._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, tampered
        )

    legacy_get = client.get(
        f"/v1/quant/runs/{run['id']}", headers=_headers(principal_id, workspace_id)
    )
    assert legacy_get.status_code == 409
    assert "dedicated market-run endpoint" in legacy_get.json()["error"]["message"]
    legacy_list = client.get("/v1/quant/runs", headers=_headers(principal_id, workspace_id))
    assert all(item["id"] != run["id"] for item in legacy_list.json())


def test_public_market_run_pins_an_aligned_utc_subrange_end_to_end(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR, count=2290
    )
    requested_start = (
        (datetime.fromisoformat(dataset["covered_start"]) + timedelta(hours=100))
        .isoformat()
        .replace("+00:00", "Z")
    )
    body = _create_body(dataset, project)
    body["research_start_utc"] = requested_start

    response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=body,
    )
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["research_start_utc"] == requested_start
    assert run["research_end_utc"] == dataset["covered_end"]

    snapshot_response = client.get(
        f"/v1/quant/runs/{run['id']}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot = snapshot_response.json()
    assert datetime.fromisoformat(
        snapshot["scope"]["dateRange"]["start"]
    ) == datetime.fromisoformat(requested_start)
    assert datetime.fromisoformat(snapshot["scope"]["dateRange"]["end"]) == datetime.fromisoformat(
        dataset["covered_end"]
    )
    assert snapshot["dataset"]["barCount"] == 2190
    assert snapshot["dataset"]["digest"] == dataset["digest"]
    assert snapshot["dataset"]["runtimeDescriptorDigest"] == run["runtime_descriptor_digest"]
    assert snapshot["dataset"]["sealedSplitDigest"] == run["sealed_split_digest"]

    restored = QuantStore().get_market_run(workspace_id=workspace_id, run_id=run["id"])
    assert restored.research_start_utc == datetime.fromisoformat(requested_start)
    assert restored.runtime_descriptor_digest == run["runtime_descriptor_digest"]


def test_public_market_run_continue_uses_source_seed_and_allows_a_new_bounded_window(
    client: TestClient, principal_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS, count=600
    )
    source, seed = _complete_public_market_source(
        client, principal_id, workspace_id, dataset, project
    )
    omitted_seed_family = next(
        family
        for family in ("sma_crossover", "rsi_mean_reversion", "breakout")
        if family != seed.template
    )
    planner_plan = routes_quant._generate_agent_plan(  # pyright: ignore[reportPrivateUsage]
        "Continue the source evidence with a stricter drawdown objective."
    ).model_copy(update={"candidate_families": [omitted_seed_family]})

    def forced_continue_plan(_question: str) -> Any:
        return planner_plan

    monkeypatch.setattr(routes_quant, "_generate_agent_plan", forced_continue_plan)
    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    source_before = store.to_market_run_response(
        store.get_market_run(workspace_id=workspace_id, run_id=source["id"])
    )
    current_project = store.get_project(workspace_id=workspace_id, project_id=project["id"])
    body = {
        **_create_body(
            dataset,
            {**project, "row_version": current_project.row_version},
            mode="plan",
        ),
        "question": "Continue the source evidence with a stricter drawdown objective.",
        "parent_run_id": source["id"],
        "seed_candidate_id": seed.id,
        "refinement_reason": "Test a distinct version while retaining the source market data.",
    }
    body["research_start_utc"] = (
        (datetime.fromisoformat(dataset["covered_start"]) + timedelta(hours=4 * 24))
        .isoformat()
        .replace("+00:00", "Z")
    )
    response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=body,
    )
    assert response.status_code == 201, response.text
    child = response.json()
    store = QuantStore()
    assert child["id"] != source["id"]
    assert child["parent_run_id"] == source["id"]
    assert child["seed_candidate_id"] == seed.id
    assert child["refinement_reason"] == body["refinement_reason"]
    for field in (
        "project_id",
        "dataset_id",
        "dataset_digest",
        "symbol",
        "interval",
        "periods_per_year",
        "research_end_utc",
        "data_authenticity",
    ):
        assert child[field] == source[field]
    assert child["research_start_utc"] == body["research_start_utc"]
    assert child["research_start_utc"] != source["research_start_utc"]
    assert child["runtime_descriptor_digest"] != source["runtime_descriptor_digest"]
    assert child["sealed_split_digest"] != source["sealed_split_digest"]
    assert (
        store.to_market_run_response(
            store.get_market_run(workspace_id=workspace_id, run_id=source["id"])
        )
        == source_before
    )

    context = store.agent_context_data(workspace_id=workspace_id, run_id=child["id"])
    assert context["refinement"] == {
        "parent_run_id": source["id"],
        "seed_candidate_id": seed.id,
        "refinement_reason": body["refinement_reason"],
        "source_research_goal": source["question"],
        "seed_candidate": {
            "name": seed.name,
            "template": seed.template,
            "parameters": seed.parameters,
        },
    }
    refinement_json = json.dumps(context["refinement"]).lower()
    for forbidden in ("holdout", "generalization", "validation", "benchmark_delta"):
        assert forbidden not in refinement_json

    snapshot = client.get(
        f"/v1/quant/runs/{child['id']}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot.status_code == 200, snapshot.text
    continued_from = snapshot.json()["run"]["continuedFrom"]
    assert continued_from["parentRunId"] == source["id"]
    assert continued_from["seedCandidateId"] == seed.id
    assert continued_from["reason"] == body["refinement_reason"]

    restored = QuantStore().get_market_run(workspace_id=workspace_id, run_id=child["id"])
    assert restored.parent_run_id == source["id"]
    assert restored.seed_candidate_id == seed.id
    assert restored.runtime_descriptor_digest == child["runtime_descriptor_digest"]
    assert restored.runtime_split_digest == child["sealed_split_digest"]
    assert restored.planned_candidate_families == [omitted_seed_family, seed.template]
    plan_artifact = next(
        artifact
        for artifact in QuantStore().artifacts_for_run(
            workspace_id=workspace_id, run_id=child["id"]
        )
        if artifact.id == restored.plan_artifact_id
    )
    assert plan_artifact.content["candidate_families"] == restored.planned_candidate_families

    guarded = QuantStore()
    guarded.get_market_run(workspace_id=workspace_id, run_id=child["id"])
    restore_baseline = guarded._workspace_state(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )

    def child_row(state: dict[str, Any]) -> dict[str, Any]:
        return next(item for item in state["runs"] if item["id"] == child["id"])

    def source_row(state: dict[str, Any]) -> dict[str, Any]:
        return next(item for item in state["runs"] if item["id"] == source["id"])

    tampered_states: list[dict[str, Any]] = []
    partial_lineage = json.loads(json.dumps(restore_baseline))
    child_row(partial_lineage)["seed_candidate_id"] = None
    tampered_states.append(partial_lineage)
    wrong_contract = json.loads(json.dumps(restore_baseline))
    child_row(wrong_contract)["market_run_contract_version"] = None
    tampered_states.append(wrong_contract)
    wrong_split = json.loads(json.dumps(restore_baseline))
    child_row(wrong_split)["runtime_split_digest"] = "sha256:tampered-refinement-split"
    tampered_states.append(wrong_split)
    nonterminal_parent = json.loads(json.dumps(restore_baseline))
    source_row(nonterminal_parent)["state"] = QuantRunState.RUNNING_EXPERIMENTS.value
    tampered_states.append(nonterminal_parent)
    self_cycle = json.loads(json.dumps(restore_baseline))
    child_row(self_cycle)["parent_run_id"] = child["id"]
    tampered_states.append(self_cycle)
    for tampered in tampered_states:
        with pytest.raises(ValueError, match="Persisted"):
            guarded._restore_workspace(  # pyright: ignore[reportPrivateUsage]
                workspace_id, tampered
            )
        assert (
            guarded._workspace_state(  # pyright: ignore[reportPrivateUsage]
                workspace_id
            )
            == restore_baseline
        )

    cancelled_response = client.post(
        f"/v1/quant/market-runs/{child['id']}/cancel",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": child["row_version"],
            "reason": "Verify refined market retry identity.",
        },
    )
    assert cancelled_response.status_code == 200, cancelled_response.text
    cancelled = cancelled_response.json()
    retry_response = client.post(
        f"/v1/quant/market-runs/{child['id']}/retry",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": cancelled["row_version"],
            "reason": "Retry the same refined version.",
        },
    )
    assert retry_response.status_code == 201, retry_response.text
    retry = retry_response.json()
    assert retry["retry_of_run_id"] == child["id"]
    assert retry["attempt_number"] == 2
    assert retry["parent_run_id"] == source["id"]
    assert retry["seed_candidate_id"] == seed.id
    assert retry["refinement_reason"] == body["refinement_reason"]
    assert retry["runtime_descriptor_digest"] == child["runtime_descriptor_digest"]
    assert retry["sealed_split_digest"] == child["sealed_split_digest"]
    retry_store = QuantStore()
    assert retry_store.experiments_for_run(workspace_id=workspace_id, run_id=retry["id"]) == []
    assert all(
        artifact.kind.value == "plan"
        for artifact in retry_store.artifacts_for_run(workspace_id=workspace_id, run_id=retry["id"])
    )


def test_public_market_run_overlap_continue_marks_holdout_as_development_only(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS, count=600
    )
    source, seed = _complete_public_market_source(
        client, principal_id, workspace_id, dataset, project
    )
    current_project = QuantStore().get_project(workspace_id=workspace_id, project_id=project["id"])
    body = {
        **_create_body(
            dataset,
            {**project, "row_version": current_project.row_version},
            mode="auto",
        ),
        "question": "Continue overlapping holdout evidence without pretending it is fresh.",
        "parent_run_id": source["id"],
        "seed_candidate_id": seed.id,
        "refinement_reason": "Reuse a partly overlapping range.",
    }
    body["research_start_utc"] = (
        (datetime.fromisoformat(dataset["covered_start"]) + timedelta(hours=4 * 24))
        .isoformat()
        .replace("+00:00", "Z")
    )
    created = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=body,
    )
    assert created.status_code == 201, created.text
    child = created.json()

    actions = 0
    while actions < 12 and run_quant_agent_once(workspace_id=workspace_id):
        actions += 1
    completed = client.get(
        f"/v1/quant/market-runs/{child['id']}",
        headers=_headers(principal_id, workspace_id),
    )
    assert completed.status_code == 200, completed.text
    completed_child = completed.json()
    assert completed_child["state"] == QuantRunState.COMPLETED.value

    artifacts = QuantStore().artifacts_for_run(workspace_id=workspace_id, run_id=child["id"])
    report = next(item for item in artifacts if item.kind.value == "research_report").content
    assert report["generalization"]["holdout_evidence_state"] == "development_only"
    assert report["generalization"]["status"] == "not_evaluated"
    assert "holdout" not in report["generalization"]
    assert report["next_step"] == "collect_more_evidence"
    assert "fresh sealed holdout" not in report["conclusion"].lower()
    assert "Holdout metrics were computed after selection." not in json.dumps(report["limitations"])

    snapshot = client.get(
        f"/v1/quant/runs/{child['id']}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot.status_code == 200, snapshot.text
    generalization = snapshot.json()["report"]["generalization"]
    assert generalization["status"] == "not_evaluated"
    assert generalization["holdout"] is None

    export = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers=_headers(principal_id, workspace_id),
        json={
            "export_type": "strategy_report_markdown",
            "run_id": child["id"],
            "candidate_id": report["selected_candidate_id"],
        },
    )
    assert export.status_code == 200, export.text
    markdown = export.json()["rendered_content"].lower()
    assert "holdout outcome: not evaluated" in markdown
    assert "sealed holdout period" not in markdown
    assert "passed sealed holdout" not in markdown


def test_public_market_run_golden_identity_chain_preserves_exact_history(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS, count=700
    )
    assert dataset["interval"] == QuantBarInterval.FOUR_HOURS.value
    assert dataset["periods_per_year"] == 2_190

    def run_until_completed(run_id: str, *, limit: int = 12) -> dict[str, Any]:
        actions = 0
        while actions < limit and run_quant_agent_once(workspace_id=workspace_id):
            actions += 1
        response = client.get(
            f"/v1/quant/market-runs/{run_id}",
            headers=_headers(principal_id, workspace_id),
        )
        assert response.status_code == 200, response.text
        completed = response.json()
        assert completed["id"] == run_id
        assert completed["state"] == QuantRunState.COMPLETED.value
        return completed

    root_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project, mode="auto"),
    )
    assert root_response.status_code == 201, root_response.text
    root_created = root_response.json()
    root = run_until_completed(root_created["id"])

    store = QuantStore()
    root_artifacts = store.artifacts_for_run(workspace_id=workspace_id, run_id=root["id"])
    root_report = next(
        artifact for artifact in root_artifacts if artifact.kind.value == "research_report"
    )
    root_comparison = max(
        (artifact for artifact in root_artifacts if artifact.kind.value == "validation_report"),
        key=lambda artifact: artifact.ordinal,
    )
    root_decision = root_report.content["research_decision"]
    root_selected_candidate_id = root_report.content["selected_candidate_id"]
    assert (
        root_report.content["generalization"]["selected_candidate_id"] == root_selected_candidate_id
    )
    assert root_report.content["generalization"]["holdout_evidence_state"] == "fresh_sealed"
    assert root_report.content["generalization"]["holdout"]
    assert root_decision["selected_candidate_id"] == root_selected_candidate_id
    assert root_decision["source_comparison_artifact_id"] == root_comparison.id
    assert root_comparison.run_id == root["id"]
    assert root_selected_candidate_id in root_comparison.content["ranking"]

    root_snapshot_response = client.get(
        f"/v1/quant/runs/{root['id']}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert root_snapshot_response.status_code == 200, root_snapshot_response.text
    root_snapshot = root_snapshot_response.json()
    assert root_snapshot["run"]["id"] == root["id"]
    assert root_snapshot["dataset"]["id"] == dataset["dataset_id"]
    assert root_snapshot["dataset"]["digest"] == dataset["digest"]
    assert root_snapshot["dataset"]["interval"] == dataset["interval"]
    assert root_snapshot["dataset"]["periodsPerYear"] == 2_190
    assert root_snapshot["dataset"]["dateRange"] == {
        "start": datetime.fromisoformat(dataset["covered_start"]).isoformat(),
        "end": datetime.fromisoformat(dataset["covered_end"]).isoformat(),
    }
    assert root_snapshot["report"]["selectionDecision"]["selectedCandidateId"] == (
        root_selected_candidate_id
    )
    assert root_snapshot["report"]["generalization"]["selectedCandidateId"] == (
        root_selected_candidate_id
    )

    current_project = store.get_project(workspace_id=workspace_id, project_id=project["id"])
    child_body = {
        **_create_body(
            dataset,
            {**project, "row_version": current_project.row_version},
            mode="auto",
        ),
        "question": "Continue the retained root evidence on an overlapping bounded range.",
        "parent_run_id": root["id"],
        "seed_candidate_id": root_selected_candidate_id,
        "refinement_reason": "Verify the exact Data → Research → History identity chain.",
    }
    child_body["research_start_utc"] = (
        (datetime.fromisoformat(dataset["covered_start"]) + timedelta(hours=4 * 24))
        .isoformat()
        .replace("+00:00", "Z")
    )
    child_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=child_body,
    )
    assert child_response.status_code == 201, child_response.text
    child_created = child_response.json()
    child = run_until_completed(child_created["id"])
    assert child["parent_run_id"] == root["id"]
    assert child["seed_candidate_id"] == root_selected_candidate_id
    assert child["dataset_id"] == root["dataset_id"]
    assert child["dataset_digest"] == root["dataset_digest"]
    assert child["interval"] == root["interval"]
    assert child["periods_per_year"] == root["periods_per_year"]
    assert child["research_end_utc"] == root["research_end_utc"]

    retry_response = client.post(
        f"/v1/quant/market-runs/{child['id']}/retry",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": child["row_version"],
            "reason": "Re-run the exact continued version as a new attempt.",
        },
    )
    assert retry_response.status_code == 201, retry_response.text
    retry_created = retry_response.json()
    retry = run_until_completed(retry_created["id"])
    assert retry["retry_of_run_id"] == child["id"]
    assert retry["attempt_number"] == 2
    assert retry["parent_run_id"] == root["id"]
    assert retry["seed_candidate_id"] == root_selected_candidate_id
    assert retry["dataset_id"] == child["dataset_id"]
    assert retry["dataset_digest"] == child["dataset_digest"]
    assert retry["interval"] == child["interval"]
    assert retry["periods_per_year"] == child["periods_per_year"]
    assert retry["research_start_utc"] == child["research_start_utc"]
    assert retry["research_end_utc"] == child["research_end_utc"]
    assert retry["runtime_descriptor_digest"] == child["runtime_descriptor_digest"]
    assert retry["sealed_split_digest"] == child["sealed_split_digest"]

    directory_response = client.get(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
    )
    assert directory_response.status_code == 200, directory_response.text
    directory_runs = {item["id"]: item for item in directory_response.json()}
    assert {root["id"], child["id"], retry["id"]}.issubset(directory_runs)

    historical_snapshots = {
        run_id: client.get(
            f"/v1/quant/runs/{run_id}/workspace-snapshot",
            headers=_headers(principal_id, workspace_id),
        )
        for run_id in (root["id"], child["id"], retry["id"])
    }
    for run_id, response in historical_snapshots.items():
        assert response.status_code == 200, response.text
        assert response.json()["run"]["id"] == run_id

    root_historical = historical_snapshots[root["id"]].json()
    child_historical = historical_snapshots[child["id"]].json()
    retry_historical = historical_snapshots[retry["id"]].json()

    assert root_historical["report"]["selectionDecision"]["selectedCandidateId"] == (
        root_selected_candidate_id
    )
    assert root_historical["report"]["generalization"]["selectedCandidateId"] == (
        root_selected_candidate_id
    )

    for snapshot in (child_historical, retry_historical):
        assert (
            snapshot["report"]["selectionDecision"]["selectedCandidateId"]
            == (snapshot["report"]["generalization"]["selectedCandidateId"])
        )
        assert snapshot["report"]["generalization"]["status"] == "not_evaluated"
        assert snapshot["report"]["generalization"]["holdout"] is None

    assert child_historical["run"]["continuedFrom"]["parentRunId"] == root["id"]
    assert child_historical["run"]["continuedFrom"]["seedCandidateId"] == root_selected_candidate_id
    assert child_historical["run"]["continuedFrom"]["reason"] == child_body["refinement_reason"]
    assert child_historical["run"]["continuedFrom"]["sourceQuestion"] == root["question"]
    assert child_historical["run"]["attemptNumber"] == 1
    assert retry_historical["run"]["attemptNumber"] == 2
    assert retry_historical["run"]["retryOfRunId"] == child["id"]
    assert retry_historical["run"]["continuedFrom"]["parentRunId"] == root["id"]
    assert retry_historical["run"]["continuedFrom"]["seedCandidateId"] == root_selected_candidate_id
    assert retry_historical["run"]["continuedFrom"]["reason"] == child_body["refinement_reason"]
    assert retry_historical["run"]["continuedFrom"]["sourceQuestion"] == root["question"]


def test_public_market_run_non_overlapping_continue_keeps_fresh_holdout_evidence(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS, count=700
    )
    source, seed = _complete_public_market_source(
        client, principal_id, workspace_id, dataset, project
    )
    current_project = QuantStore().get_project(workspace_id=workspace_id, project_id=project["id"])
    child_end = (
        (datetime.fromisoformat(dataset["covered_start"]) + timedelta(hours=4 * (548 - 1)))
        .isoformat()
        .replace("+00:00", "Z")
    )
    body = {
        **_create_body(
            dataset,
            {**project, "row_version": current_project.row_version},
            mode="auto",
        ),
        "question": "Continue a disjoint window with a still-fresh holdout.",
        "parent_run_id": source["id"],
        "seed_candidate_id": seed.id,
        "refinement_reason": "Use an earlier non-overlapping range.",
        "research_end_utc": child_end,
    }
    created = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=body,
    )
    assert created.status_code == 201, created.text
    child = created.json()

    actions = 0
    while actions < 12 and run_quant_agent_once(workspace_id=workspace_id):
        actions += 1
    completed = client.get(
        f"/v1/quant/market-runs/{child['id']}",
        headers=_headers(principal_id, workspace_id),
    )
    assert completed.status_code == 200, completed.text
    completed_child = completed.json()
    assert completed_child["state"] == QuantRunState.COMPLETED.value

    artifacts = QuantStore().artifacts_for_run(workspace_id=workspace_id, run_id=child["id"])
    report = next(item for item in artifacts if item.kind.value == "research_report").content
    assert report["generalization"]["holdout_evidence_state"] == "fresh_sealed"
    assert report["generalization"]["holdout"]


def test_public_market_retry_holdout_state_tracks_consumed_vs_cancelled_source(
    client: TestClient,
    principal_id: str,
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS, count=700
    )
    source, _ = _complete_public_market_source(client, principal_id, workspace_id, dataset, project)
    consumed_retry = client.post(
        f"/v1/quant/market-runs/{source['id']}/retry",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": source["row_version"],
            "reason": "Retry a completed run with the same pinned split.",
        },
    )
    assert consumed_retry.status_code == 201, consumed_retry.text
    consumed = consumed_retry.json()

    actions = 0
    while actions < 12 and run_quant_agent_once(workspace_id=workspace_id):
        actions += 1
    completed_retry = client.get(
        f"/v1/quant/market-runs/{consumed['id']}",
        headers=_headers(principal_id, workspace_id),
    )
    assert completed_retry.status_code == 200, completed_retry.text
    consumed_report = next(
        item
        for item in QuantStore().artifacts_for_run(workspace_id=workspace_id, run_id=consumed["id"])
        if item.kind.value == "research_report"
    ).content
    assert consumed_report["generalization"]["holdout_evidence_state"] == "development_only"
    assert consumed_report["generalization"]["status"] == "not_evaluated"
    assert "holdout" not in consumed_report["generalization"]

    fresh_workspace_id, fresh_dataset, fresh_project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS, count=700
    )
    fresh_body = _create_body(fresh_dataset, fresh_project, mode="auto")
    fresh_created = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, fresh_workspace_id),
        json=fresh_body,
    )
    assert fresh_created.status_code == 201, fresh_created.text
    fresh_source = fresh_created.json()
    cancelled = client.post(
        f"/v1/quant/market-runs/{fresh_source['id']}/cancel",
        headers=_headers(principal_id, fresh_workspace_id),
        json={
            "expected_row_version": fresh_source["row_version"],
            "reason": "Cancel before any evaluated report exists.",
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    fresh_retry = client.post(
        f"/v1/quant/market-runs/{fresh_source['id']}/retry",
        headers=_headers(principal_id, fresh_workspace_id),
        json={
            "expected_row_version": cancelled.json()["row_version"],
            "reason": "Retry a never-evaluated terminal source.",
        },
    )
    assert fresh_retry.status_code == 201, fresh_retry.text
    retry = fresh_retry.json()
    actions = 0
    while actions < 12 and run_quant_agent_once(workspace_id=fresh_workspace_id):
        actions += 1
    completed = client.get(
        f"/v1/quant/market-runs/{retry['id']}",
        headers=_headers(principal_id, fresh_workspace_id),
    )
    assert completed.status_code == 200, completed.text
    completed_report = next(
        item
        for item in QuantStore().artifacts_for_run(
            workspace_id=fresh_workspace_id,
            run_id=retry["id"],
        )
        if item.kind.value == "research_report"
    ).content
    assert completed_report["generalization"]["holdout_evidence_state"] == "fresh_sealed"
    assert completed_report["generalization"]["holdout"]


@pytest.mark.parametrize(
    "lineage",
    [
        {"parent_run_id": str(uuid4())},
        {"parent_run_id": str(uuid4()), "seed_candidate_id": str(uuid4())},
        {
            "parent_run_id": str(uuid4()),
            "seed_candidate_id": str(uuid4()),
            "refinement_reason": "   ",
        },
    ],
)
def test_public_market_run_continue_contract_rejects_partial_lineage(
    client: TestClient,
    principal_id: str,
    lineage: dict[str, Any],
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    baseline = _persisted_state(workspace_id)
    response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json={**_create_body(dataset, project), **lineage},
    )
    assert response.status_code == 422, response.text
    assert _persisted_state(workspace_id) == baseline


def test_public_market_run_continue_rejects_nonterminal_source_before_provider(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    source_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project),
    )
    assert source_response.status_code == 201, source_response.text
    source = source_response.json()
    current_project = routes_quant._store().get_project(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id, project_id=project["id"]
    )
    baseline = _persisted_state(workspace_id)

    def provider_must_not_run(_: str):
        raise AssertionError("invalid market continuation reached the Agent provider")

    monkeypatch.setattr(routes_quant, "_generate_agent_plan", provider_must_not_run)
    response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json={
            **_create_body(
                dataset,
                {**project, "row_version": current_project.row_version},
            ),
            "parent_run_id": source["id"],
            "seed_candidate_id": str(uuid4()),
            "refinement_reason": "This must fail before provider work.",
        },
    )
    assert response.status_code == 409, response.text
    assert "terminal source run" in response.json()["error"]["message"].lower()
    assert _persisted_state(workspace_id) == baseline


def test_public_market_run_plan_mutations_retry_and_wrong_endpoints_fail_closed(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    created = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project),
    ).json()

    changed_response = client.post(
        f"/v1/quant/market-runs/{created['id']}/request-plan-changes",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": created["row_version"],
            "plan_revision": created["plan_revision"],
            "change_request": "Focus the revised plan on mean reversion and lower drawdown.",
        },
    )
    assert changed_response.status_code == 200, changed_response.text
    changed = changed_response.json()
    assert changed["state"] == "waiting_plan_approval"
    assert changed["plan_revision"] == created["plan_revision"] + 1
    store = QuantStore()
    changed_context = store.agent_context_data(workspace_id=workspace_id, run_id=created["id"])
    assert changed_context["approved_plan"]["candidate_families"] == [
        "rsi_mean_reversion",
        "sma_crossover",
    ]
    assert changed_context["approved_plan"]["selection_objective"] == "drawdown_control"
    plan_artifacts = [
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=created["id"])
        if artifact.kind.value == "plan"
    ]
    assert plan_artifacts[-1].content["candidate_families"] == [
        "rsi_mean_reversion",
        "sma_crossover",
    ]
    assert plan_artifacts[-1].content["selection_objective"] == "drawdown_control"

    approved_response = client.post(
        f"/v1/quant/market-runs/{created['id']}/approve-plan",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": changed["row_version"],
            "plan_revision": changed["plan_revision"],
            "reason": "Approved for cadence-aware research.",
        },
    )
    assert approved_response.status_code == 200, approved_response.text
    approved = approved_response.json()
    assert approved["state"] == "running_experiments"

    baseline = _persisted_state(workspace_id)
    wrong_endpoint = client.post(
        f"/v1/quant/runs/{created['id']}/cancel",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": approved["row_version"],
            "reason": "The legacy endpoint must not mutate this run.",
        },
    )
    assert wrong_endpoint.status_code == 409
    assert _persisted_state(workspace_id) == baseline
    wrong_workspace_command = client.post(
        "/v1/quant/workspace-snapshot/commands",
        headers=_headers(principal_id, workspace_id),
        json={
            "command": "cancel_run",
            "expected_row_version": approved["row_version"],
            "payload": {"reason": "Legacy commands must not mutate public market runs."},
        },
    )
    assert wrong_workspace_command.status_code == 409
    assert _persisted_state(workspace_id) == baseline

    cancelled_response = client.post(
        f"/v1/quant/market-runs/{created['id']}/cancel",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": approved["row_version"],
            "reason": "Stop this controlled run.",
        },
    )
    assert cancelled_response.status_code == 200, cancelled_response.text
    cancelled = cancelled_response.json()
    assert cancelled["state"] == "cancelled"
    assert cancelled["agent_status"] == "cancelled"

    retry_response = client.post(
        f"/v1/quant/market-runs/{created['id']}/retry",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": cancelled["row_version"],
            "reason": "Retry the same pinned research.",
        },
    )
    assert retry_response.status_code == 201, retry_response.text
    retry = retry_response.json()
    assert retry["attempt_number"] == 2
    assert retry["retry_of_run_id"] == created["id"]
    assert retry["dataset_id"] == created["dataset_id"]
    assert retry["runtime_descriptor_digest"] == created["runtime_descriptor_digest"]
    assert retry["sealed_split_digest"] == created["sealed_split_digest"]
    assert retry["schema_version"] == "quant-market-run-v2"
    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    assert store.experiments_for_run(workspace_id=workspace_id, run_id=retry["id"]) == []
    assert all(
        artifact.kind.value == "plan"
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=retry["id"])
    )


def test_public_market_replan_provider_failure_has_zero_state_mutation(
    client: TestClient, principal_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS
    )
    created = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project),
    ).json()
    baseline = _persisted_state(workspace_id)

    def fail_replan(_: str, __: str) -> None:
        raise routes_quant.invalid_state("The revised plan provider failed.")

    monkeypatch.setattr(routes_quant, "_generate_revised_agent_plan", fail_replan)
    response = client.post(
        f"/v1/quant/market-runs/{created['id']}/request-plan-changes",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": created["row_version"],
            "plan_revision": created["plan_revision"],
            "change_request": "Focus the revised plan on mean reversion.",
        },
    )

    assert response.status_code == 409, response.text
    assert _persisted_state(workspace_id) == baseline


@pytest.mark.parametrize("failure_timing", ["precommit", "postcommit"])
def test_public_market_create_reconciles_persist_exceptions(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
    failure_timing: str,
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    store.list_projects(workspace_id=workspace_id)
    project_reference = store.get_project(workspace_id=workspace_id, project_id=project["id"])
    project_reference_baseline = (
        project_reference.latest_run_id,
        project_reference.row_version,
    )
    baseline = _persisted_state(workspace_id)
    _fail_next_persist(monkeypatch, store, after_commit=failure_timing == "postcommit")

    if failure_timing == "precommit":
        with pytest.raises(RuntimeError, match="injected market-run persist failure"):
            client.post(
                "/v1/quant/market-runs",
                headers=_headers(principal_id, workspace_id),
                json=_create_body(dataset, project),
            )

        assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
        assert _persisted_state(workspace_id) == baseline
        assert (
            project_reference.latest_run_id,
            project_reference.row_version,
        ) == project_reference_baseline
        response = client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=_create_body(dataset, project),
        )
    else:
        response = client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=_create_body(dataset, project),
        )
        assert store._workspace_state(workspace_id) != baseline  # pyright: ignore[reportPrivateUsage]
        assert _persisted_state(workspace_id) == store._workspace_state(  # pyright: ignore[reportPrivateUsage]
            workspace_id
        )
        assert project_reference.latest_run_id == response.json()["id"]
    assert response.status_code == 201, response.text
    assert response.json()["state"] == "waiting_plan_approval"
    follow_up = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": f"Post-create reconciliation {failure_timing}",
            "objective": "Prove the repository version remains writable.",
        },
    )
    assert follow_up.status_code == 201, follow_up.text


def test_public_market_create_reloads_unexpected_durable_truth(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    project_reference = store.get_project(workspace_id=workspace_id, project_id=project["id"])
    project_reference_baseline = (
        project_reference.latest_run_id,
        project_reference.row_version,
    )

    def commit_concurrent_state_then_raise(_workspace_id: str) -> None:
        QuantStore().create_project(
            workspace_id=workspace_id,
            name="Concurrent durable truth",
            objective="Represent a third committed payload during reconciliation.",
        )
        raise RuntimeError("injected divergent market-run persist failure")

    monkeypatch.setattr(store, "_persist_workspace", commit_concurrent_state_then_raise)
    monkeypatch.setattr(routes_quant, "_store", lambda: store)

    with pytest.raises(
        RuntimeError,
        match="diverged from both the baseline and attempted state",
    ):
        client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=_create_body(dataset, project),
        )

    durable = _persisted_state(workspace_id)
    assert store._workspace_state(workspace_id) == durable  # pyright: ignore[reportPrivateUsage]
    assert (
        project_reference.latest_run_id,
        project_reference.row_version,
    ) == project_reference_baseline
    assert any(item["name"] == "Concurrent durable truth" for item in durable["projects"])
    assert not any(item["question"] == "Run a bounded intraday study." for item in durable["runs"])


@pytest.mark.parametrize("failure_timing", ["precommit", "postcommit"])
@pytest.mark.parametrize("operation", ["approve", "change", "cancel", "retry"])
def test_public_market_mutation_reconciles_persist_exceptions(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failure_timing: str,
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS
    )
    created_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project),
    )
    assert created_response.status_code == 201, created_response.text
    target = created_response.json()
    if operation == "cancel":
        approved_response = client.post(
            f"/v1/quant/market-runs/{target['id']}/approve-plan",
            headers=_headers(principal_id, workspace_id),
            json={
                "expected_row_version": target["row_version"],
                "plan_revision": target["plan_revision"],
                "reason": "Prepare cancellation persistence testing.",
            },
        )
        assert approved_response.status_code == 200, approved_response.text
        target = approved_response.json()
    elif operation == "retry":
        cancelled_response = client.post(
            f"/v1/quant/market-runs/{target['id']}/cancel",
            headers=_headers(principal_id, workspace_id),
            json={
                "expected_row_version": target["row_version"],
                "reason": "Prepare retry persistence testing.",
            },
        )
        assert cancelled_response.status_code == 200, cancelled_response.text
        target = cancelled_response.json()

    path_and_body: dict[str, tuple[str, dict[str, object]]] = {
        "approve": (
            f"/v1/quant/market-runs/{target['id']}/approve-plan",
            {
                "expected_row_version": target["row_version"],
                "plan_revision": target["plan_revision"],
                "reason": "Approve after a recoverable write failure.",
            },
        ),
        "change": (
            f"/v1/quant/market-runs/{target['id']}/request-plan-changes",
            {
                "expected_row_version": target["row_version"],
                "plan_revision": target["plan_revision"],
                "change_request": "Keep the plan bounded after persistence recovery.",
            },
        ),
        "cancel": (
            f"/v1/quant/market-runs/{target['id']}/cancel",
            {
                "expected_row_version": target["row_version"],
                "reason": "Cancel after a recoverable write failure.",
            },
        ),
        "retry": (
            f"/v1/quant/market-runs/{target['id']}/retry",
            {
                "expected_row_version": target["row_version"],
                "reason": "Retry after a recoverable write failure.",
            },
        ),
    }
    path, body = path_and_body[operation]
    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    run_reference = store.get_market_run(workspace_id=workspace_id, run_id=target["id"])
    run_reference_baseline = (run_reference.state, run_reference.row_version)
    baseline = _persisted_state(workspace_id)
    _fail_next_persist(monkeypatch, store, after_commit=failure_timing == "postcommit")

    if failure_timing == "precommit":
        with pytest.raises(RuntimeError, match="injected market-run persist failure"):
            client.post(path, headers=_headers(principal_id, workspace_id), json=body)
        assert store._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]
        assert _persisted_state(workspace_id) == baseline
        assert (run_reference.state, run_reference.row_version) == run_reference_baseline
        response = client.post(path, headers=_headers(principal_id, workspace_id), json=body)
    else:
        response = client.post(path, headers=_headers(principal_id, workspace_id), json=body)
        assert store._workspace_state(workspace_id) != baseline  # pyright: ignore[reportPrivateUsage]
        assert _persisted_state(workspace_id) == store._workspace_state(  # pyright: ignore[reportPrivateUsage]
            workspace_id
        )
    assert response.status_code in {200, 201}, response.text
    follow_up = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": f"Post-{operation} reconciliation {failure_timing}",
            "objective": "Prove the repository version remains writable.",
        },
    )
    assert follow_up.status_code == 201, follow_up.text


@pytest.mark.parametrize("lease_owner_kind", ["legacy", "market"])
def test_cancel_without_target_lease_preserves_other_run_claim(
    client: TestClient,
    principal_id: str,
    lease_owner_kind: str,
) -> None:
    workspace_id, dataset, market_project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    if lease_owner_kind == "legacy":
        owner = _create_legacy_run(
            client,
            principal_id,
            workspace_id,
            mode="auto",
            label="owner-a",
        )
        target_response = client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=_create_body(dataset, market_project),
        )
        assert target_response.status_code == 201, target_response.text
        target = target_response.json()
        target_kind = "market"
    else:
        owner_response = client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=_create_body(dataset, market_project, mode="auto"),
        )
        assert owner_response.status_code == 201, owner_response.text
        owner = owner_response.json()
        target = _create_legacy_run(
            client,
            principal_id,
            workspace_id,
            mode="plan",
            label="target-b",
        )
        target_kind = "legacy"

    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="lease-owner-a")
    assert claim is not None and claim.run_id == owner["id"]
    durable_before = store._durable_workspace_truth(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    assert durable_before.worker_lease_run_id == owner["id"]

    endpoint = (
        f"/v1/quant/market-runs/{target['id']}/cancel"
        if target_kind == "market"
        else f"/v1/quant/runs/{target['id']}/cancel"
    )
    response = client.post(
        endpoint,
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": target["row_version"],
            "reason": "Cancel only the target Run.",
        },
    )
    assert response.status_code == 200, response.text

    durable_after = store._durable_workspace_truth(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    assert (
        durable_after.worker_lease_token,
        durable_after.worker_lease_run_id,
        durable_after.worker_lease_worker_id,
        durable_after.worker_lease_attempt_number,
        durable_after.worker_fencing_version,
    ) == (
        durable_before.worker_lease_token,
        durable_before.worker_lease_run_id,
        durable_before.worker_lease_worker_id,
        durable_before.worker_lease_attempt_number,
        durable_before.worker_fencing_version,
    )
    assert (
        store.get_run(workspace_id=workspace_id, run_id=owner["id"]).state
        is QuantRunState.RUNNING_EXPERIMENTS
    )
    assert store._fixture_lease_is_current(claim)  # pyright: ignore[reportPrivateUsage]
    assert (
        durable_after.storage_version
        == store._storage_versions[  # pyright: ignore[reportPrivateUsage]
            workspace_id
        ]
    )
    assert store.heartbeat_fixture_run(claim)
    assert store._fixture_lease_is_current(claim)  # pyright: ignore[reportPrivateUsage]
    assert store.record_agent_decision(claim, _agent_decision())
    store.release_agent_claim(claim)


def test_cancel_in_another_workspace_preserves_the_claimed_run(
    client: TestClient,
    principal_id: str,
) -> None:
    owner_workspace, _, _ = _provision(client, principal_id, interval=QuantBarInterval.HOUR)
    owner = _create_legacy_run(
        client,
        principal_id,
        owner_workspace,
        mode="auto",
        label="cross-workspace-owner",
    )
    target_workspace, target_dataset, target_project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS
    )
    target_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, target_workspace),
        json=_create_body(target_dataset, target_project),
    )
    assert target_response.status_code == 201, target_response.text
    target = target_response.json()

    owner_store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    claim = owner_store.claim_agent_run(
        workspace_id=owner_workspace, worker_id="cross-workspace-owner"
    )
    assert claim is not None and claim.run_id == owner["id"]
    before = owner_store._durable_workspace_truth(  # pyright: ignore[reportPrivateUsage]
        owner_workspace
    )

    cancelled = client.post(
        f"/v1/quant/market-runs/{target['id']}/cancel",
        headers=_headers(principal_id, target_workspace),
        json={
            "expected_row_version": target["row_version"],
            "reason": "Cancel only the other workspace target.",
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    after = owner_store._durable_workspace_truth(  # pyright: ignore[reportPrivateUsage]
        owner_workspace
    )
    assert after == before
    assert owner_store.heartbeat_fixture_run(claim)
    assert owner_store.record_agent_decision(claim, _agent_decision())
    owner_store.release_agent_claim(claim)


def test_cancel_retries_worker_lease_invalidation_without_duplicate_run_mutation(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    created_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project, mode="auto"),
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="cancel-lease-probe")
    assert claim is not None
    original_invalidate = store._invalidate_worker_lease  # pyright: ignore[reportPrivateUsage]
    pending = True

    def fail_once(target_run: QuantRunRecord) -> None:
        nonlocal pending
        if pending:
            pending = False
            raise RuntimeError("injected worker lease invalidation failure")
        original_invalidate(target_run)

    monkeypatch.setattr(store, "_invalidate_worker_lease", fail_once)
    monkeypatch.setattr(routes_quant, "_store", lambda: store)
    request_body = {
        "expected_row_version": created["row_version"],
        "reason": "Cancel while proving lease cleanup convergence.",
    }

    with pytest.raises(RuntimeError, match="injected worker lease invalidation failure"):
        client.post(
            f"/v1/quant/market-runs/{created['id']}/cancel",
            headers=_headers(principal_id, workspace_id),
            json=request_body,
        )

    cancelled = store.get_market_run(workspace_id=workspace_id, run_id=created["id"])
    assert cancelled.state is QuantRunState.CANCELLED
    cancelled_row_version = cancelled.row_version
    cancelled_events = store.events_for_run(workspace_id=workspace_id, run_id=created["id"])
    durable_before_retry = store._durable_workspace_truth(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    assert durable_before_retry.worker_lease_token == claim.token
    assert durable_before_retry.worker_lease_run_id == created["id"]

    retried = client.post(
        f"/v1/quant/market-runs/{created['id']}/cancel",
        headers=_headers(principal_id, workspace_id),
        json=request_body,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["row_version"] == cancelled_row_version
    assert store.events_for_run(workspace_id=workspace_id, run_id=created["id"]) == cancelled_events
    durable_after_retry = store._durable_workspace_truth(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    assert durable_after_retry.worker_lease_token is None
    assert durable_after_retry.worker_lease_expires_at is None
    assert durable_after_retry.worker_lease_run_id is None
    assert (
        store.create_agent_candidate(
            claim,
            name="Stale candidate",
            template="breakout",
            hypothesis="A cancelled lease cannot write.",
            parameters={"lookback_window": 55},
        )[2]
        == "STALE_CLAIM"
    )


@pytest.mark.parametrize("cancelled_owner_kind", ["legacy", "market"])
def test_cancel_cleanup_retry_cannot_clear_a_replacement_run_lease(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
    cancelled_owner_kind: str,
) -> None:
    workspace_id, dataset, market_project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS
    )
    if cancelled_owner_kind == "market":
        target_response = client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=_create_body(dataset, market_project, mode="auto"),
        )
        assert target_response.status_code == 201, target_response.text
        target = target_response.json()
        replacement = _create_legacy_run(
            client,
            principal_id,
            workspace_id,
            mode="auto",
            label="replacement-a",
        )
        endpoint = f"/v1/quant/market-runs/{target['id']}/cancel"
    else:
        target = _create_legacy_run(
            client,
            principal_id,
            workspace_id,
            mode="auto",
            label="cancelled-b",
        )
        replacement_response = client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=_create_body(dataset, market_project, mode="auto"),
        )
        assert replacement_response.status_code == 201, replacement_response.text
        replacement = replacement_response.json()
        endpoint = f"/v1/quant/runs/{target['id']}/cancel"

    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    target_claim = store.claim_agent_run(workspace_id=workspace_id, worker_id="cancelled-owner-b")
    assert target_claim is not None and target_claim.run_id == target["id"]
    original_invalidate = store._invalidate_worker_lease  # pyright: ignore[reportPrivateUsage]
    pending = True

    def fail_target_cleanup_once(target_run: QuantRunRecord) -> None:
        nonlocal pending
        if pending:
            pending = False
            raise RuntimeError("injected target lease cleanup failure")
        original_invalidate(target_run)

    monkeypatch.setattr(store, "_invalidate_worker_lease", fail_target_cleanup_once)
    monkeypatch.setattr(routes_quant, "_store", lambda: store)
    request_body = {
        "expected_row_version": target["row_version"],
        "reason": "Cancel B before a replacement lease is acquired.",
    }
    with pytest.raises(RuntimeError, match="injected target lease cleanup failure"):
        client.post(
            endpoint,
            headers=_headers(principal_id, workspace_id),
            json=request_body,
        )

    cancelled = store.get_run(workspace_id=workspace_id, run_id=target["id"])
    assert cancelled.state is QuantRunState.CANCELLED
    cancelled_events = store.events_for_run(workspace_id=workspace_id, run_id=target["id"])
    with store._session_factory() as db:  # pyright: ignore[reportPrivateUsage]
        row = db.get(QuantRepositoryState, workspace_id)
        assert row is not None and row.worker_lease_run_id == target["id"]
        row.worker_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    replacement_claim = store.claim_agent_run(
        workspace_id=workspace_id, worker_id="replacement-owner-a"
    )
    assert replacement_claim is not None
    assert replacement_claim.run_id == replacement["id"]
    replacement_truth = store._durable_workspace_truth(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    replacement_version = replacement_truth.storage_version
    assert replacement_truth.worker_lease_run_id == replacement["id"]
    assert replacement_truth.worker_lease_token == replacement_claim.token

    retry = client.post(
        endpoint,
        headers=_headers(principal_id, workspace_id),
        json=request_body,
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["row_version"] == cancelled.row_version
    assert store.events_for_run(workspace_id=workspace_id, run_id=target["id"]) == cancelled_events
    after_retry = store._durable_workspace_truth(  # pyright: ignore[reportPrivateUsage]
        workspace_id
    )
    assert after_retry.storage_version == replacement_version
    assert after_retry.worker_lease_run_id == replacement["id"]
    assert after_retry.worker_lease_token == replacement_claim.token
    assert store.heartbeat_fixture_run(replacement_claim)
    assert store.record_agent_decision(replacement_claim, _agent_decision())
    store.release_agent_claim(replacement_claim)


def test_market_retry_restore_requires_closed_bidirectional_identity_and_is_atomic(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    alternate_project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": "Wrong retry project",
            "objective": "Provide a valid but mismatched project identity for restore testing.",
        },
    )
    assert alternate_project_response.status_code == 201
    alternate_project = alternate_project_response.json()
    created = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project),
    ).json()
    cancelled = client.post(
        f"/v1/quant/market-runs/{created['id']}/cancel",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": created["row_version"],
            "reason": "Prepare a durable retry relation.",
        },
    ).json()
    retry_response = client.post(
        f"/v1/quant/market-runs/{created['id']}/retry",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": cancelled["row_version"],
            "reason": "Create one valid retry child.",
        },
    )
    assert retry_response.status_code == 201, retry_response.text
    retry = retry_response.json()

    guarded = QuantStore()
    source_record = guarded.get_market_run(workspace_id=workspace_id, run_id=created["id"])
    child_record = guarded.get_market_run(workspace_id=workspace_id, run_id=retry["id"])
    assert source_record.retry_child_run_id == child_record.id
    assert child_record.retry_of_run_id == source_record.id
    assert child_record.selection_objective == source_record.selection_objective
    baseline = guarded._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]

    def run_rows(state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        source = next(item for item in state["runs"] if item["id"] == created["id"])
        child = next(item for item in state["runs"] if item["id"] == retry["id"])
        return source, child

    tampered_states: list[dict[str, Any]] = []
    missing_child = json.loads(json.dumps(baseline))
    run_rows(missing_child)[0]["retry_child_run_id"] = str(uuid4())
    tampered_states.append(missing_child)
    reverse_mismatch = json.loads(json.dumps(baseline))
    run_rows(reverse_mismatch)[1]["retry_of_run_id"] = None
    tampered_states.append(reverse_mismatch)
    attempt_mismatch = json.loads(json.dumps(baseline))
    run_rows(attempt_mismatch)[1]["attempt_number"] += 1
    tampered_states.append(attempt_mismatch)
    identity_mismatch = json.loads(json.dumps(baseline))
    run_rows(identity_mismatch)[1]["question"] = "Tampered retry identity"
    tampered_states.append(identity_mismatch)
    project_mismatch = json.loads(json.dumps(baseline))
    run_rows(project_mismatch)[1]["project_id"] = alternate_project["id"]
    tampered_states.append(project_mismatch)
    dataset_mismatch = json.loads(json.dumps(baseline))
    run_rows(dataset_mismatch)[1]["dataset_digest"] = "sha256:tampered-retry-dataset"
    tampered_states.append(dataset_mismatch)
    workspace_mismatch = json.loads(json.dumps(baseline))
    run_rows(workspace_mismatch)[1]["workspace_id"] = str(uuid4())
    tampered_states.append(workspace_mismatch)
    contract_mismatch = json.loads(json.dumps(baseline))
    run_rows(contract_mismatch)[1]["market_run_contract_version"] = None
    tampered_states.append(contract_mismatch)
    selection_mismatch = json.loads(json.dumps(baseline))
    run_rows(selection_mismatch)[1]["selection_objective"] = "total_return"
    tampered_states.append(selection_mismatch)
    self_cycle = json.loads(json.dumps(baseline))
    run_rows(self_cycle)[0]["retry_child_run_id"] = created["id"]
    tampered_states.append(self_cycle)

    for tampered in tampered_states:
        with pytest.raises(ValueError, match="Persisted"):
            guarded._restore_workspace(  # pyright: ignore[reportPrivateUsage]
                workspace_id, tampered
            )
        assert guarded._workspace_state(workspace_id) == baseline  # pyright: ignore[reportPrivateUsage]

    source_record = guarded.get_market_run(workspace_id=workspace_id, run_id=created["id"])
    child_record = guarded.get_market_run(workspace_id=workspace_id, run_id=retry["id"])
    original_digest = child_record.runtime_split_digest
    child_record.runtime_split_digest = "sha256:tampered-retry-split"
    with pytest.raises(ApiError, match="retain its source Run identity"):
        guarded.retry_market_run(
            workspace_id=workspace_id,
            run_id=source_record.id,
            expected_row_version=1,
            reason="A corrupt child must not use the idempotent return path.",
        )
    child_record.runtime_split_digest = original_digest
    reloaded = QuantStore()
    assert (
        reloaded.get_market_run(workspace_id=workspace_id, run_id=retry["id"]).retry_of_run_id
        == created["id"]
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("research_start_utc", "2024-01-01T00:00:00"),
        ("research_start_utc", "2024-01-01"),
        ("research_start_utc", "2024-01-01T08:00:00+08:00"),
        ("research_end_utc", "not-a-timestamp"),
    ],
)
def test_public_market_run_rejects_non_strict_utc_without_side_effects(
    client: TestClient,
    principal_id: str,
    field: str,
    value: str,
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.FOUR_HOURS
    )
    body = _create_body(dataset, project)
    body[field] = value
    baseline = _persisted_state(workspace_id)
    response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=body,
    )
    assert response.status_code == 422, response.text
    assert _persisted_state(workspace_id) == baseline


def test_public_market_plan_changes_require_exact_row_and_plan_versions(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    created = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project),
    ).json()
    baseline = _persisted_state(workspace_id)
    invalid_versions = (
        (created["row_version"] + 1, created["plan_revision"]),
        (created["row_version"], created["plan_revision"] + 1),
        (created["row_version"] + 1, created["plan_revision"] + 1),
    )
    for row_version, plan_revision in invalid_versions:
        response = client.post(
            f"/v1/quant/market-runs/{created['id']}/request-plan-changes",
            headers=_headers(principal_id, workspace_id),
            json={
                "expected_row_version": row_version,
                "plan_revision": plan_revision,
                "change_request": "Reject every stale version combination.",
            },
        )
        assert response.status_code == 409, response.text
        assert _persisted_state(workspace_id) == baseline
    accepted = client.post(
        f"/v1/quant/market-runs/{created['id']}/request-plan-changes",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": created["row_version"],
            "plan_revision": created["plan_revision"],
            "change_request": "Accept only the exact current versions.",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["plan_revision"] == created["plan_revision"] + 1


def test_legacy_daily_plan_changes_require_exact_row_and_plan_versions(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "Legacy plan concurrency")
    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Legacy plan", "objective": "Preserve exact v1 concurrency."},
    )
    assert project_response.status_code == 201
    project = project_response.json()
    created_response = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "mode": "plan",
            "question": "Verify legacy plan-change concurrency.",
            "expected_project_row_version": project["row_version"],
        },
    )
    assert created_response.status_code == 201, created_response.text
    created = created_response.json()
    baseline = _persisted_state(workspace_id)
    invalid_versions = (
        (created["row_version"] + 1, created["plan_revision"]),
        (created["row_version"], created["plan_revision"] + 1),
        (created["row_version"] + 1, created["plan_revision"] + 1),
    )
    for row_version, plan_revision in invalid_versions:
        response = client.post(
            f"/v1/quant/runs/{created['id']}/request-plan-changes",
            headers=_headers(principal_id, workspace_id),
            json={
                "expected_row_version": row_version,
                "plan_revision": plan_revision,
                "change_request": "Reject every stale legacy version combination.",
            },
        )
        assert response.status_code == 409, response.text
        assert _persisted_state(workspace_id) == baseline
    accepted = client.post(
        f"/v1/quant/runs/{created['id']}/request-plan-changes",
        headers=_headers(principal_id, workspace_id),
        json={
            "expected_row_version": created["row_version"],
            "plan_revision": created["plan_revision"],
            "change_request": "Accept only the exact current legacy versions.",
        },
    )
    assert accepted.status_code == 200, accepted.text


def test_public_market_run_rejects_misaligned_range_client_cadence_and_ineligible_data(
    client: TestClient, principal_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    body = _create_body(dataset, project)
    body["research_start_utc"] = "2024-01-01T00:30:00Z"
    baseline = _persisted_state(workspace_id)
    plan_called = False

    def unexpected_plan(_question: str) -> Any:
        nonlocal plan_called
        plan_called = True
        raise AssertionError("invalid market data must fail before provider planning")

    monkeypatch.setattr(routes_quant, "_generate_agent_plan", unexpected_plan)
    stale = _create_body(dataset, project)
    stale["expected_project_row_version"] = project["row_version"] + 1
    stale_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=stale,
    )
    assert stale_response.status_code == 412
    assert plan_called is False
    assert (
        client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=body,
        ).status_code
        == 409
    )
    assert plan_called is False
    too_short = _create_body(dataset, project)
    too_short["research_start_utc"] = "2024-01-03T21:00:00Z"
    assert (
        client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=too_short,
        ).status_code
        == 409
    )
    outside = _create_body(dataset, project)
    outside["research_start_utc"] = "2023-12-31T23:00:00Z"
    assert (
        client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=outside,
        ).status_code
        == 409
    )
    assert plan_called is False
    override = _create_body(dataset, project)
    override["interval"] = "1D"
    override["periods_per_year"] = 252
    assert (
        client.post(
            "/v1/quant/market-runs",
            headers=_headers(principal_id, workspace_id),
            json=override,
        ).status_code
        == 422
    )
    assert _persisted_state(workspace_id) == baseline

    short_workspace, short_dataset, short_project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR, count=2189
    )
    assert short_dataset["research_eligible"] is False
    short_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, short_workspace),
        json=_create_body(short_dataset, short_project),
    )
    assert short_response.status_code == 409

    gap_workspace, gap_dataset, gap_project = _provision(
        client,
        principal_id,
        interval=QuantBarInterval.HOUR,
        gap_after=100,
    )
    assert gap_dataset["research_eligible"] is False
    gap_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, gap_workspace),
        json=_create_body(gap_dataset, gap_project),
    )
    assert gap_response.status_code == 409
    assert plan_called is False

    other_workspace = _workspace(client, principal_id, "Market run isolation")
    other_project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, other_workspace),
        json={"name": "Isolated project", "objective": "Do not reveal foreign datasets."},
    )
    assert other_project_response.status_code == 201
    foreign_body = _create_body(dataset, other_project_response.json())
    foreign_response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, other_workspace),
        json=foreign_body,
    )
    assert foreign_response.status_code == 404


def test_public_market_run_rejects_a_547_bar_4h_subrange_before_planner_or_mutation(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id, dataset, project = _provision(
        client,
        principal_id,
        interval=QuantBarInterval.FOUR_HOURS,
        count=600,
    )
    accepted = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project),
    )
    assert accepted.status_code == 201, accepted.text

    second_project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": "4h boundary rejection project",
            "objective": "Reject a sub-threshold public research window before planning.",
        },
    )
    assert second_project_response.status_code == 201, second_project_response.text
    second_project = second_project_response.json()
    baseline = _persisted_state(workspace_id)
    plan_called = False

    def unexpected_plan(_question: str) -> Any:
        nonlocal plan_called
        plan_called = True
        raise AssertionError("sub-threshold public market data must fail before provider planning")

    monkeypatch.setattr(routes_quant, "_generate_agent_plan", unexpected_plan)
    subrange = _create_body(dataset, second_project)
    start = datetime.fromisoformat(dataset["covered_start"].replace("Z", "+00:00"))
    subrange["research_end_utc"] = (
        (start + timedelta(hours=4 * 546)).isoformat().replace("+00:00", "Z")
    )
    rejected = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=subrange,
    )
    assert rejected.status_code == 409, rejected.text
    assert "548" in rejected.json()["error"]["message"]
    assert plan_called is False
    assert _persisted_state(workspace_id) == baseline


def test_private_and_daily_runs_are_rejected_by_market_endpoints_without_mutation(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    store = QuantStore()
    private = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=project["id"],
        question="Keep this internal runtime private.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=project["row_version"],
        dataset_id=dataset["dataset_id"],
    )
    private_read = client.get(
        f"/v1/quant/market-runs/{private.id}",
        headers=_headers(principal_id, workspace_id),
    )
    assert private_read.status_code == 409
    assert (
        client.get("/v1/quant/market-runs", headers=_headers(principal_id, workspace_id)).json()
        == []
    )
    baseline = _persisted_state(workspace_id)
    for suffix, body in (
        ("approve-plan", {"expected_row_version": private.row_version, "plan_revision": 1}),
        (
            "request-plan-changes",
            {
                "expected_row_version": private.row_version,
                "plan_revision": 1,
                "change_request": "This must remain private.",
            },
        ),
        ("cancel", {"expected_row_version": private.row_version, "reason": "No mutation."}),
        ("retry", {"expected_row_version": private.row_version, "reason": "No mutation."}),
    ):
        response = client.post(
            f"/v1/quant/market-runs/{private.id}/{suffix}",
            headers=_headers(principal_id, workspace_id),
            json=body,
        )
        assert response.status_code == 409, response.text
        assert _persisted_state(workspace_id) == baseline

    daily_project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Daily project", "objective": "Keep daily runs on the v1 contract."},
    )
    assert daily_project_response.status_code == 201
    daily_project = daily_project_response.json()
    daily_response = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": daily_project["id"],
            "mode": "plan",
            "question": "Run the legacy daily fixture path.",
            "expected_project_row_version": daily_project["row_version"],
        },
    )
    assert daily_response.status_code == 201, daily_response.text
    daily = daily_response.json()
    daily_baseline = _persisted_state(workspace_id)
    assert (
        client.get(
            f"/v1/quant/market-runs/{daily['id']}",
            headers=_headers(principal_id, workspace_id),
        ).status_code
        == 409
    )
    daily_cancel = client.post(
        f"/v1/quant/market-runs/{daily['id']}/cancel",
        headers=_headers(principal_id, workspace_id),
        json={"expected_row_version": daily["row_version"], "reason": "Wrong endpoint."},
    )
    assert daily_cancel.status_code == 409
    assert _persisted_state(workspace_id) == daily_baseline


def test_stale_event_cursor_resets_to_the_readable_run_contract(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, dataset, project = _provision(
        client, principal_id, interval=QuantBarInterval.HOUR
    )
    public = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project),
    ).json()

    store = routes_quant._store()  # pyright: ignore[reportPrivateUsage]
    private_project = store.create_project(
        workspace_id=workspace_id,
        name="Private reset target",
        objective="Keep reset recovery read-only.",
    )
    private = store._create_market_runtime_run(  # pyright: ignore[reportPrivateUsage]
        workspace_id=workspace_id,
        project_id=private_project.id,
        question="Keep this private runtime readable through a snapshot.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=private_project.row_version,
        dataset_id=dataset["dataset_id"],
    )
    legacy_project = store.create_project(
        workspace_id=workspace_id,
        name="Legacy reset target",
        objective="Keep the existing daily reset link.",
    )
    legacy = store.create_run(
        workspace_id=workspace_id,
        project_id=legacy_project.id,
        question="Keep this legacy run on the daily read route.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=legacy_project.row_version,
    )

    expected_urls = {
        public["id"]: f"/v1/quant/market-runs/{public['id']}",
        private.id: f"/v1/quant/runs/{private.id}/workspace-snapshot",
        legacy.id: f"/v1/quant/runs/{legacy.id}",
    }
    for run_id, expected_url in expected_urls.items():
        response = client.get(
            f"/v1/quant/runs/{run_id}/events",
            headers={
                "Authorization": f"Bearer {principal_id}",
                "X-Workspace-ID": workspace_id,
                "Last-Event-ID": "missing",
            },
        )
        assert response.status_code == 200, response.text
        assert f'"snapshot_url":"{expected_url}"' in response.text


@pytest.mark.parametrize(
    ("interval", "periods_per_year"),
    [
        (QuantBarInterval.HOUR, 8_760),
        (QuantBarInterval.FOUR_HOURS, 2_190),
    ],
)
def test_public_market_auto_run_uses_worker_and_retains_public_identity(
    client: TestClient,
    principal_id: str,
    interval: QuantBarInterval,
    periods_per_year: int,
) -> None:
    workspace_id, dataset, project = _provision(client, principal_id, interval=interval)
    response = client.post(
        "/v1/quant/market-runs",
        headers=_headers(principal_id, workspace_id),
        json=_create_body(dataset, project, mode="auto"),
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["state"] == QuantRunState.RUNNING_EXPERIMENTS.value

    actions = 0
    while actions < 12 and run_quant_agent_once(workspace_id=workspace_id):
        actions += 1
    completed = client.get(
        f"/v1/quant/market-runs/{created['id']}",
        headers=_headers(principal_id, workspace_id),
    ).json()
    assert completed["state"] == QuantRunState.COMPLETED.value
    assert actions <= 12
    assert completed["used_experiments"] == 3
    assert completed["runtime_descriptor_digest"] == created["runtime_descriptor_digest"]
    assert completed["sealed_split_digest"] == created["sealed_split_digest"]
    snapshot = client.get(
        f"/v1/quant/runs/{created['id']}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot.status_code == 200, snapshot.text
    snapshot_body = snapshot.json()
    assert snapshot_body["run"]["id"] == created["id"]
    assert snapshot_body["dataset"]["interval"] == interval.value
    assert snapshot_body["dataset"]["periodsPerYear"] == periods_per_year
    assert all(
        artifact.get("type") != "iteration_feedback"
        for artifact in snapshot_body.get("primaryArtifacts", [])
    )
    completed_store = QuantStore()
    experiments = completed_store.experiments_for_run(
        workspace_id=workspace_id, run_id=created["id"]
    )
    assert len(experiments) == 3
    assert len({candidate.candidate_key for candidate in experiments}) == 3
    artifacts = completed_store.artifacts_for_run(workspace_id=workspace_id, run_id=created["id"])
    feedback = [artifact for artifact in artifacts if artifact.kind.value == "iteration_feedback"]
    reports = [artifact for artifact in artifacts if artifact.kind.value == "research_report"]
    comparisons = [artifact for artifact in artifacts if artifact.kind.value == "validation_report"]
    assert len(feedback) == 1
    assert len(reports) == 1
    assert len(comparisons) == 2
    assert "holdout" not in json.dumps(feedback[0].content).lower()
    assert reports[0].content["selected_candidate_id"] in comparisons[-1].content["ranking"]
    assert reports[0].content["generalization"]["holdout"]
    retained_decision = reports[0].content["research_decision"]
    projected_decision = snapshot_body["report"]["selectionDecision"]
    assert projected_decision["basis"] == retained_decision["decision_basis"]
    if retained_decision["decision_basis"] == "robustness_override":
        assert projected_decision["reason"] == retained_decision["deviation"]["reason"]
        assert (
            projected_decision["referenceCandidateId"]
            == retained_decision["deviation"]["reference_candidate_id"]
        )
    selected_candidate_id = snapshot_body["report"]["generalization"]["selectedCandidateId"]
    projected_candidates = {item["id"]: item for item in snapshot_body["candidates"]}
    feedback_candidate = next(item for item in experiments if item.feedback_artifact_id is not None)
    feedback_evolution = projected_candidates[feedback_candidate.id]["evolution"]
    assert feedback_evolution["origin"] == "training_feedback"
    assert feedback_evolution["hypothesis"] == feedback_candidate.hypothesis
    assert feedback_evolution["changeRationale"] == feedback_candidate.change_rationale
    assert feedback_evolution["feedbackReferenceCandidateId"] in {
        item.id for item in experiments if item.feedback_artifact_id is None
    }
    assert feedback_evolution["comparisonCandidateCount"] == 3
    assert (
        "holdout evidence was not available"
        in projected_candidates[selected_candidate_id]["evolution"]["selectionReason"]
    )
    export = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers=_headers(principal_id, workspace_id),
        json={
            "export_type": "strategy_report_markdown",
            "run_id": created["id"],
            "candidate_id": selected_candidate_id,
        },
    )
    assert export.status_code == 200, export.text
    assert export.json()["data_authenticity"] == created["data_authenticity"]
    markdown = export.json()["rendered_content"]
    assert f"BTCUSDT · {interval.value}" in markdown
    assert f"Annualization: {periods_per_year} periods per year" in markdown
    assert "## Selection Decision" in markdown
    assert "Selection basis:" in markdown
    assert "Deviation:" in markdown
    assert "Reference candidate:" in markdown
    historical = client.get(
        f"/v1/quant/runs/{created['id']}/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert historical.status_code == 200, historical.text
    assert (
        historical.json()["report"]["generalization"]["selectedCandidateId"]
        == selected_candidate_id
    )
    assert historical.json()["performanceSeries"] == snapshot_body["performanceSeries"]
    restored = QuantStore().get_market_run(workspace_id=workspace_id, run_id=created["id"])
    assert restored.market_run_contract_version == "quant-market-run-v2"
    assert restored.runtime_split_digest == created["sealed_split_digest"]
