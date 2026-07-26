from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from packages.contracts.quant import QuantRunState
from packages.domain.canonical import canonical_digest
from services.api.app.modules.quant import snapshot as quant_snapshot_module
from services.api.app.modules.quant.kernel_check import build_quant_kernel_check
from services.api.app.modules.quant.snapshot import FIXTURE_STATES, quant_workspace_fixture
from services.api.app.modules.quant.store import QuantStore
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.pipelines.quant_fixture import run_quant_fixture_once


def _workspace(
    client: TestClient, principal_id: str, name: str = "Quant workspace"
) -> dict[str, Any]:
    response = client.post(
        "/v1/workspaces",
        headers={"Authorization": f"Bearer {principal_id}", "Idempotency-Key": str(UUID(int=1))},
        json={"name": name, "data_region": "local", "retention_policy_version": "retention-v1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _project(
    client: TestClient, principal_id: str, workspace_id: str, name: str = "Alpha"
) -> dict[str, Any]:
    response = client.post(
        "/v1/quant/projects",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=2)),
            "X-Workspace-ID": workspace_id,
        },
        json={"name": name, "objective": "Validate a deterministic quant surface."},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    project: dict[str, Any],
    question: str = "Which fixture path is most robust?",
) -> dict[str, Any]:
    response = client.post(
        "/v1/quant/runs",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=3)),
            "X-Workspace-ID": workspace_id,
        },
        json={
            "project_id": project["id"],
            "question": question,
            "mode": "plan",
            "expected_project_row_version": project["row_version"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _events(
    client: TestClient, principal_id: str, workspace_id: str, run_id: str
) -> list[dict[str, Any]]:
    response = client.get(
        f"/v1/quant/runs/{run_id}/events",
        headers={"Authorization": f"Bearer {principal_id}", "X-Workspace-ID": workspace_id},
    )
    assert response.status_code == 200, response.text
    return [line for line in response.text.splitlines() if line.startswith("data: ")]


def _contains_forbidden_key_recursive(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            key in forbidden or _contains_forbidden_key_recursive(item, forbidden)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key_recursive(item, forbidden) for item in value)
    return False


def test_quant_surface_round_trip_and_event_recovery(client: TestClient, principal_id: str) -> None:
    workspace = _workspace(client, principal_id)
    project = _project(client, principal_id, workspace["workspace_id"])
    run = _run(client, principal_id, workspace["workspace_id"], project)
    assert run["state"] == "waiting_plan_approval"
    assert run["latest_sequence"] == 3

    events = _events(client, principal_id, workspace["workspace_id"], run["id"])
    assert len(events) == 3

    response = client.get(
        f"/v1/quant/runs/{run['id']}/events",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
            "Last-Event-ID": "missing",
        },
    )
    assert response.status_code == 200, response.text
    assert "stream.reset" in response.text

    approve = client.post(
        f"/v1/quant/runs/{run['id']}/approve-plan",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=4)),
            "X-Workspace-ID": workspace["workspace_id"],
        },
        json={
            "expected_row_version": run["row_version"],
            "plan_revision": run["plan_revision"],
            "reason": "Approved for deterministic completion.",
        },
    )
    assert approve.status_code == 200, approve.text
    run = approve.json()
    assert run["state"] == "running_experiments"

    assert run_quant_fixture_once(workspace_id=workspace["workspace_id"], fixture_state="completed")

    completed = client.get(
        f"/v1/quant/runs/{run['id']}",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    assert completed.status_code == 200, completed.text
    completed_run = completed.json()
    assert completed_run["state"] == "completed"
    assert completed_run["latest_sequence"] >= 6

    artifacts = client.get(
        f"/v1/quant/runs/{run['id']}/artifacts",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    experiments = client.get(
        f"/v1/quant/runs/{run['id']}/experiments",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    assert artifacts.status_code == 200 and len(artifacts.json()) == 7
    assert experiments.status_code == 200 and len(experiments.json()) == 3
    completed_events = client.get(
        f"/v1/quant/runs/{run['id']}/events",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    ).text
    assert "backtest.failed" in completed_events
    assert "repair.started" in completed_events
    assert "run.failed" not in completed_events


def test_refinement_creates_an_independent_run_with_server_owned_seed_context(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, name="Refinement")
    project = _project(client, principal_id, workspace["workspace_id"], name="Refinement project")
    created = client.post(
        "/v1/quant/runs",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=81)),
            "X-Workspace-ID": workspace["workspace_id"],
        },
        json={
            "project_id": project["id"],
            "question": "Which retained trend rule should be refined?",
            "mode": "auto",
            "expected_project_row_version": project["row_version"],
        },
    )
    assert created.status_code == 201, created.text
    parent = created.json()
    for _ in range(20):
        if not run_quant_agent_once(workspace_id=workspace["workspace_id"]):
            break
        if (
            QuantStore()
            .get_run(workspace_id=workspace["workspace_id"], run_id=parent["id"])
            .state.value
            == "completed"
        ):
            break
    experiments = client.get(
        f"/v1/quant/runs/{parent['id']}/experiments",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    assert experiments.status_code == 200, experiments.text
    seed = next(
        item for item in experiments.json() if item["state"] == "completed" and item["parameters"]
    )
    projects = client.get(
        "/v1/quant/projects",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    source_project = next(item for item in projects.json() if item["id"] == project["id"])
    response = client.post(
        "/v1/quant/runs",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=82)),
            "X-Workspace-ID": workspace["workspace_id"],
        },
        json={
            "project_id": project["id"],
            "question": "Test a slower trend filter after the retained holdout result.",
            "mode": "auto",
            "expected_project_row_version": source_project["row_version"],
            "parent_run_id": parent["id"],
            "seed_candidate_id": seed["id"],
            "refinement_reason": "Reduce holdout drawdown without treating the source as a winner.",
        },
    )
    assert response.status_code == 201, response.text
    child = response.json()
    assert child["id"] != parent["id"]
    assert child["parent_run_id"] == parent["id"]
    assert child["seed_candidate_id"] == seed["id"]
    store = QuantStore()
    context = store.agent_context_data(workspace_id=workspace["workspace_id"], run_id=child["id"])
    assert context["refinement"]["seed_candidate"]["parameters"] == seed["parameters"]
    assert context["refinement"]["source_research_goal"] == parent["question"]
    assert set(context["refinement"]) == {
        "parent_run_id",
        "seed_candidate_id",
        "refinement_reason",
        "source_research_goal",
        "seed_candidate",
    }
    assert set(context["refinement"]["seed_candidate"]) == {
        "name",
        "template",
        "parameters",
    }
    assert not _contains_forbidden_key_recursive(
        context["refinement"],
        {
            "holdout",
            "generalization",
            "validation",
            "recommendation",
            "metrics",
            "benchmark_delta",
        },
    )
    child_record = store.get_run(workspace_id=workspace["workspace_id"], run_id=child["id"])
    child_record.max_experiments = 3
    lease = store.claim_agent_run(
        workspace_id=workspace["workspace_id"], worker_id="refinement-feedback"
    )
    assert lease is not None
    first, _, error = store.create_agent_candidate(
        lease,
        name="SMA 15/80",
        template="sma_crossover",
        hypothesis="Test a canonical-distinct medium trend filter.",
        parameters={"fast_window": 15, "slow_window": 80},
    )
    assert error is None and first is not None
    child_record.state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(lease, candidate_id=first.id)[2] is None
    second, _, error = store.create_agent_candidate(
        lease,
        name="SMA 30/150",
        template="sma_crossover",
        hypothesis="Test a canonical-distinct slower trend filter.",
        parameters={"fast_window": 30, "slow_window": 150},
    )
    assert error is None and second is not None
    child_record.state = QuantRunState.RUNNING_EXPERIMENTS
    assert store.run_agent_backtest(lease, candidate_id=second.id)[2] is None
    assert store.compare_agent_candidates(lease)[2] is None
    assert any(
        artifact.kind.value == "iteration_feedback"
        for artifact in store.artifacts_for_run(
            workspace_id=workspace["workspace_id"], run_id=child["id"]
        )
    )
    current_child = store.get_run(workspace_id=workspace["workspace_id"], run_id=child["id"])
    store.cancel_run(
        workspace_id=workspace["workspace_id"],
        run_id=child["id"],
        expected_row_version=current_child.row_version,
        reason="Retry the refined attempt without carrying prior observations.",
    )
    retry = store.retry_run(
        workspace_id=workspace["workspace_id"],
        run_id=child["id"],
        expected_row_version=store.get_run(
            workspace_id=workspace["workspace_id"], run_id=child["id"]
        ).row_version,
        reason="Retry the same refinement.",
    )
    assert retry.parent_run_id == parent["id"]
    assert retry.seed_candidate_id == seed["id"]
    assert retry.refinement_reason == child["refinement_reason"]
    retry_context = store.agent_context_data(
        workspace_id=workspace["workspace_id"], run_id=retry.id
    )
    assert retry_context["iteration_feedback"] is None
    assert not store.experiments_for_run(workspace_id=workspace["workspace_id"], run_id=retry.id)
    partial = client.post(
        "/v1/quant/runs",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=83)),
            "X-Workspace-ID": workspace["workspace_id"],
        },
        json={
            "project_id": project["id"],
            "question": "Invalid partial continuation",
            "mode": "plan",
            "expected_project_row_version": source_project["row_version"],
            "parent_run_id": parent["id"],
        },
    )
    assert partial.status_code == 422


def test_refinement_restore_is_closed_atomic_and_preserves_refined_retry_lineage(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, name="Refinement restore")
    workspace_id = workspace["workspace_id"]
    project = _project(client, principal_id, workspace_id, name="Refinement restore project")
    alternate_project_response = client.post(
        "/v1/quant/projects",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=806)),
            "X-Workspace-ID": workspace_id,
        },
        json={
            "name": "Unrelated restore project",
            "objective": "Supply a valid but unrelated project identity.",
        },
    )
    assert alternate_project_response.status_code == 201, alternate_project_response.text
    alternate_project = alternate_project_response.json()
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "X-Workspace-ID": workspace_id,
    }
    created = client.post(
        "/v1/quant/runs",
        headers={**headers, "Idempotency-Key": str(UUID(int=801))},
        json={
            "project_id": project["id"],
            "question": "Which completed strategy should begin this research series?",
            "mode": "auto",
            "expected_project_row_version": project["row_version"],
        },
    )
    assert created.status_code == 201, created.text
    root = created.json()
    for _ in range(20):
        if not run_quant_agent_once(workspace_id=workspace_id):
            break
        current = QuantStore().get_run(workspace_id=workspace_id, run_id=root["id"])
        if current.state is QuantRunState.COMPLETED:
            break
    root_record = QuantStore().get_run(workspace_id=workspace_id, run_id=root["id"])
    assert root_record.state is QuantRunState.COMPLETED
    seed = next(
        item
        for item in QuantStore().experiments_for_run(
            workspace_id=workspace_id,
            run_id=root["id"],
        )
        if item.state == "completed" and item.template != "fixture" and item.parameters
    )
    current_project = next(
        item
        for item in client.get("/v1/quant/projects", headers=headers).json()
        if item["id"] == project["id"]
    )
    continued = client.post(
        "/v1/quant/runs",
        headers={**headers, "Idempotency-Key": str(UUID(int=802))},
        json={
            "project_id": project["id"],
            "question": "Refine the retained strategy as an independent version.",
            "mode": "plan",
            "expected_project_row_version": current_project["row_version"],
            "parent_run_id": root["id"],
            "seed_candidate_id": seed.id,
            "refinement_reason": "Test a slower signal without inheriting source evidence.",
        },
    )
    assert continued.status_code == 201, continued.text
    child = continued.json()
    cancelled = client.post(
        f"/v1/quant/runs/{child['id']}/cancel",
        headers={**headers, "Idempotency-Key": str(UUID(int=803))},
        json={
            "expected_row_version": child["row_version"],
            "reason": "Make the refined version terminal before retrying it.",
        },
    )
    assert cancelled.status_code == 200, cancelled.text
    retried = client.post(
        f"/v1/quant/runs/{child['id']}/retry",
        headers={**headers, "Idempotency-Key": str(UUID(int=804))},
        json={
            "expected_row_version": cancelled.json()["row_version"],
            "reason": "Retry the same refined version.",
        },
    )
    assert retried.status_code == 201, retried.text
    retry = retried.json()

    restored = QuantStore()
    restored_retry = restored.get_run(workspace_id=workspace_id, run_id=retry["id"])
    restored_child = restored.get_run(workspace_id=workspace_id, run_id=child["id"])
    restored_root = restored.get_run(workspace_id=workspace_id, run_id=root["id"])
    assert restored_child.parent_run_id == restored_root.id
    assert restored_child.seed_candidate_id == seed.id
    assert restored_child.retry_child_run_id == restored_retry.id
    assert restored_retry.retry_of_run_id == restored_child.id
    assert restored_retry.parent_run_id == restored_root.id
    assert restored_retry.seed_candidate_id == seed.id
    assert restored_retry.refinement_reason == restored_child.refinement_reason
    contract_mismatch = replace(
        restored_child,
        market_run_contract_version="quant-market-run-v2",
    )
    assert (
        restored._refinement_pair_error(  # pyright: ignore[reportPrivateUsage]
            restored_root,
            contract_mismatch,
        )
        == "A Quant refinement must retain its source Run contract family."
    )

    baseline = restored._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    baseline_versions = dict(
        restored._storage_versions  # pyright: ignore[reportPrivateUsage]
    )
    baseline_loaded = set(
        restored._loaded_workspaces  # pyright: ignore[reportPrivateUsage]
    )
    cached_root = restored_root

    def cloned_state() -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(json.dumps(baseline)))

    def run_row(state: dict[str, Any], run_id: str) -> dict[str, Any]:
        return next(item for item in state["runs"] if item["id"] == run_id)

    def seed_row(state: dict[str, Any]) -> dict[str, Any]:
        return next(item for item in state["experiments"] if item["id"] == seed.id)

    tampered_states: list[tuple[str, dict[str, Any], str]] = []

    partial = cloned_state()
    run_row(partial, child["id"])["seed_candidate_id"] = None
    tampered_states.append(("partial", partial, "must contain parent, seed and reason"))

    blank_reason = cloned_state()
    run_row(blank_reason, child["id"])["refinement_reason"] = "  "
    tampered_states.append(("blank reason", blank_reason, "reason must contain 1 to 2,000"))

    cross_workspace = cloned_state()
    run_row(cross_workspace, child["id"])["workspace_id"] = "another-workspace"
    tampered_states.append(("cross workspace", cross_workspace, "does not belong"))

    cross_project = cloned_state()
    run_row(cross_project, child["id"])["project_id"] = alternate_project["id"]
    tampered_states.append(("cross project", cross_project, "source project"))

    cross_dataset = cloned_state()
    run_row(cross_dataset, child["id"])["dataset_digest"] = "sha256:other-dataset"
    tampered_states.append(("cross dataset", cross_dataset, "dataset identity"))

    nonterminal_parent = cloned_state()
    run_row(nonterminal_parent, root["id"])["state"] = "running_experiments"
    tampered_states.append(("nonterminal parent", nonterminal_parent, "terminal source Run"))

    missing_seed = cloned_state()
    run_row(missing_seed, child["id"])["seed_candidate_id"] = str(UUID(int=805))
    run_row(missing_seed, retry["id"])["seed_candidate_id"] = str(UUID(int=805))
    tampered_states.append(("missing seed", missing_seed, "missing seed candidate"))

    wrong_seed_owner = cloned_state()
    seed_row(wrong_seed_owner)["run_id"] = child["id"]
    tampered_states.append(("wrong seed owner", wrong_seed_owner, "completed source Run"))

    wrong_seed_status = cloned_state()
    seed_row(wrong_seed_status)["state"] = "created"
    tampered_states.append(("wrong seed status", wrong_seed_status, "completed source Run"))

    fixture_seed = cloned_state()
    seed_row(fixture_seed)["template"] = "fixture"
    seed_row(fixture_seed)["candidate_key"] = None
    tampered_states.append(("fixture seed", fixture_seed, "completed source Run"))

    invalid_seed_parameters = cloned_state()
    invalid_seed_row = seed_row(invalid_seed_parameters)
    invalid_seed_row["parameters"] = {
        "sma_crossover": {"fast_window": 200, "slow_window": 20},
        "rsi_mean_reversion": {
            "period": 14,
            "entry_threshold": 80,
            "exit_threshold": 20,
        },
        "breakout": {"lookback_window": 0},
    }[invalid_seed_row["template"]]
    invalid_seed_row["candidate_key"] = QuantStore.canonical_candidate_key(
        invalid_seed_row["template"],
        invalid_seed_row["parameters"],
    )
    tampered_states.append(
        ("invalid seed parameters", invalid_seed_parameters, "invalid strategy parameters")
    )

    self_cycle = cloned_state()
    run_row(self_cycle, child["id"])["parent_run_id"] = child["id"]
    tampered_states.append(("self cycle", self_cycle, "cannot reference itself"))

    multi_node_cycle = cloned_state()
    root_cycle = run_row(multi_node_cycle, root["id"])
    root_cycle["parent_run_id"] = child["id"]
    root_cycle["seed_candidate_id"] = seed.id
    root_cycle["refinement_reason"] = "Create a deliberately cyclic persisted graph."
    tampered_states.append(("multi-node cycle", multi_node_cycle, "contains a cycle"))

    retry_lineage_tamper = cloned_state()
    run_row(retry_lineage_tamper, retry["id"])["refinement_reason"] = (
        "Change only the retry lineage reason."
    )
    tampered_states.append(
        ("retry lineage", retry_lineage_tamper, "retry child must retain its source Run identity")
    )

    for label, tampered, expected_error in tampered_states:
        with pytest.raises(ValueError, match=expected_error):
            restored._restore_workspace(  # pyright: ignore[reportPrivateUsage]
                workspace_id,
                tampered,
            )
        assert (
            restored._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
            == baseline
        ), label
        assert (
            restored._storage_versions  # pyright: ignore[reportPrivateUsage]
            == baseline_versions
        ), label
        assert (
            restored._loaded_workspaces  # pyright: ignore[reportPrivateUsage]
            == baseline_loaded
        ), label
        assert restored.get_run(workspace_id=workspace_id, run_id=root["id"]) is cached_root


def test_strategy_report_markdown_export_is_deterministic_and_scoped(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, name="Report export")
    project = _project(client, principal_id, workspace["workspace_id"])
    run = client.post(
        "/v1/quant/runs",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
            "Idempotency-Key": str(UUID(int=201)),
        },
        json={
            "project_id": project["id"],
            "mode": "auto",
            "question": "Reduce maximum drawdown with a durable report.",
            "expected_project_row_version": project["row_version"],
        },
    ).json()
    for _ in range(20):
        if not run_quant_agent_once(workspace_id=workspace["workspace_id"]):
            break
        current = QuantStore().get_run(workspace_id=workspace["workspace_id"], run_id=run["id"])
        if current.state.value == "completed":
            break
    store = QuantStore()
    candidates = store.experiments_for_run(workspace_id=workspace["workspace_id"], run_id=run["id"])
    artifacts = store.artifacts_for_run(workspace_id=workspace["workspace_id"], run_id=run["id"])
    assert candidates
    candidate_id = candidates[0].id
    payload = {
        "export_type": "strategy_report_markdown",
        "run_id": run["id"],
        "candidate_id": candidate_id,
    }
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "X-Workspace-ID": workspace["workspace_id"],
    }
    first = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(UUID(int=202))},
        json=payload,
    )
    second = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(UUID(int=203))},
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    exported = first.json()
    assert exported["candidate_id"] == candidate_id
    assert exported["data_authenticity"] == "generated"
    assert exported["filename"].endswith(".md")
    assert "## Strategy vs Benchmark" in exported["rendered_content"]
    assert "## Strategy Specification" in exported["rendered_content"]
    assert exported["content_digest"].startswith("sha256:")

    spoofed = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(UUID(int=208))},
        json={**payload, "data_authenticity": "collected"},
    )
    assert spoofed.status_code == 422

    report_artifact = next(
        artifact for artifact in artifacts if artifact.kind.value == "research_report"
    )
    final_candidate_id = report_artifact.content["selected_candidate_id"]
    report_artifact.content["conclusion"] = (
        "The iteration_feedback artifact directed a tool call for the selected strategy."
    )
    report_artifact.content["limitations"] = [
        "The iteration feedback and tool invocation remain internal process details."
    ]
    report_artifact.digest = canonical_digest(report_artifact.content)
    store._persist_workspace(workspace["workspace_id"])  # pyright: ignore[reportPrivateUsage]
    safe_payload = {**payload, "candidate_id": final_candidate_id}
    safe_export = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(UUID(int=205))},
        json=safe_payload,
    )
    safe_snapshot = client.get("/v1/quant/workspace-snapshot", headers=headers)
    assert safe_export.status_code == 200, safe_export.text
    assert safe_snapshot.status_code == 200, safe_snapshot.text
    for rendered in (
        safe_export.json()["rendered_content"],
        safe_snapshot.json()["report"]["conclusion"],
        " ".join(safe_snapshot.json()["report"]["limitations"]),
    ):
        lowered = rendered.lower()
        assert "iteration_feedback" not in lowered
        assert "iteration feedback" not in lowered
        assert "feedback artifact" not in lowered
        assert "tool call" not in lowered
    assert "final training comparison" in safe_export.json()["rendered_content"]

    invalid = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(UUID(int=204))},
        json={**payload, "candidate_id": str(UUID(int=999))},
    )
    assert invalid.status_code == 404
    isolated_response = client.post(
        "/v1/workspaces",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=207)),
        },
        json={
            "name": "Isolated export",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert isolated_response.status_code == 201, isolated_response.text
    isolated_workspace = isolated_response.json()
    isolated = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": isolated_workspace["workspace_id"],
            "Idempotency-Key": str(UUID(int=205)),
        },
        json=payload,
    )
    assert isolated.status_code == 404

    empty_project = _project(
        client, principal_id, isolated_workspace["workspace_id"], name="No report"
    )
    empty_run = _run(client, principal_id, isolated_workspace["workspace_id"], empty_project)
    no_report = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": isolated_workspace["workspace_id"],
            "Idempotency-Key": str(UUID(int=206)),
        },
        json={**payload, "run_id": empty_run["id"]},
    )
    assert no_report.status_code == 409


def test_historical_run_workspace_snapshot_is_selected_and_read_only(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, name="Quant history")
    workspace_id = workspace["workspace_id"]
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "X-Workspace-ID": workspace_id,
    }

    first_project = _project(client, principal_id, workspace_id, name="First research")
    first_run = _run(
        client,
        principal_id,
        workspace_id,
        first_project,
        question="Inspect the first retained hypothesis.",
    )
    second_project_response = client.post(
        "/v1/quant/projects",
        headers={**headers, "Idempotency-Key": str(UUID(int=12))},
        json={"name": "Second research", "objective": "Retain another project."},
    )
    assert second_project_response.status_code == 201, second_project_response.text
    second_project = second_project_response.json()
    second_run_response = client.post(
        "/v1/quant/runs",
        headers={**headers, "Idempotency-Key": str(UUID(int=13))},
        json={
            "project_id": second_project["id"],
            "question": "Inspect the newest retained hypothesis.",
            "mode": "plan",
            "expected_project_row_version": second_project["row_version"],
        },
    )
    assert second_run_response.status_code == 201, second_run_response.text
    second_run = second_run_response.json()

    latest = client.get("/v1/quant/workspace-snapshot", headers=headers).json()
    historical_response = client.get(
        f"/v1/quant/runs/{first_run['id']}/workspace-snapshot", headers=headers
    )
    assert historical_response.status_code == 200, historical_response.text
    historical = historical_response.json()

    assert latest["run"]["id"] == second_run["id"]
    assert historical["run"]["id"] == first_run["id"]
    assert historical["project"]["title"] == "First research"
    assert historical["project"]["latestRunId"] == first_run["id"]
    assert historical["run"]["legalCommands"] == []
    assert historical["composerLegalCommands"] == []
    assert [item["title"] for item in historical["recentProjects"]] == [
        "Second research",
        "First research",
    ]
    assert [item["latestRunId"] for item in historical["recentProjects"]] == [
        second_run["id"],
        first_run["id"],
    ]


@pytest.mark.parametrize(("strip_selected_trades", "expect_marker"), [(True, False), (False, True)])
def test_final_report_selected_candidate_controls_trade_markers(
    client: TestClient, principal_id: str, strip_selected_trades: bool, expect_marker: bool
) -> None:
    workspace = _workspace(client, principal_id, name="Final report identity")
    workspace_id = workspace["workspace_id"]
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "X-Workspace-ID": workspace_id,
    }
    project = _project(client, principal_id, workspace_id, name="Final report project")
    run = _run(
        client,
        principal_id,
        workspace_id,
        project,
        question="Keep the final report tied to the selected candidate.",
    )
    store = QuantStore()
    recorded = store.get_run(workspace_id=workspace_id, run_id=run["id"])
    recorded.state = QuantRunState.RUNNING_EXPERIMENTS
    recorded.max_experiments = 2
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="final-report-trades")
    assert lease is not None

    created: list[Any] = []
    for name, template, parameters in (
        ("SMA 20/100", "sma_crossover", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", "sma_crossover", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template=template,
            hypothesis="Check final selected trade identity.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        created.append(candidate)
        recorded.state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None

    selected_candidate = created[0]
    if strip_selected_trades:
        selected_trade_log = next(
            artifact
            for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run["id"])
            if artifact.kind.value == "trade_log"
            and artifact.content.get("candidate_id") == selected_candidate.id
        )
        selected_trade_log.content["trades"] = []

    comparison, artifact_ids, error = store.compare_agent_candidates(lease)
    assert error is None and comparison is not None
    assert artifact_ids
    report, report_artifacts, error = store.finish_agent_research(
        lease,
        selected_candidate_id=selected_candidate.id,
        conclusion="Use the selected candidate for the final report.",
        next_step="stop",
    )
    assert error is None and report is not None
    assert report["selected_candidate_id"] == selected_candidate.id
    assert report_artifacts
    assert store.get_run(workspace_id=workspace_id, run_id=run["id"]).state.value == "completed"

    snapshot = client.get("/v1/quant/workspace-snapshot", headers=headers)
    assert snapshot.status_code == 200, snapshot.text
    historical_snapshot = client.get(
        f"/v1/quant/runs/{run['id']}/workspace-snapshot",
        headers=headers,
    )
    assert historical_snapshot.status_code == 200, historical_snapshot.text
    export = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(UUID(int=206))},
        json={
            "export_type": "strategy_report_markdown",
            "run_id": run["id"],
            "candidate_id": selected_candidate.id,
        },
    )
    assert export.status_code == 200, export.text
    export_payload = export.json()

    for payload in (snapshot.json(), historical_snapshot.json()):
        assert payload["run"]["state"] == "completed"
        assert payload["report"]["generalization"]["selectedCandidateId"] == selected_candidate.id
        assert payload["report"]["conclusion"]
        assert payload["artifacts"]
        assert any(item["candidateId"] != selected_candidate.id for item in payload["trades"])
        bar_dates = {bar["date"] for bar in payload["bars"]}
        all_trade_dates = {
            trade[date_key] for trade in payload["trades"] for date_key in ("entryDate", "exitDate")
        }
        assert all_trade_dates <= bar_dates
        markers = [bar for bar in payload["bars"] if "marker" in bar]
        if expect_marker:
            assert markers
        else:
            assert markers == []
        assert export_payload["candidate_id"] == selected_candidate.id


def test_iteration_feedback_stays_out_of_workspace_snapshot_primary_surfaces(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, name="Feedback snapshot")
    project = _project(client, principal_id, workspace["workspace_id"], name="Feedback project")
    run = _run(
        client,
        principal_id,
        workspace["workspace_id"],
        project,
        question="Check internal iteration feedback projection.",
    )
    store = QuantStore()
    recorded = store.get_run(workspace_id=workspace["workspace_id"], run_id=run["id"])
    recorded.max_experiments = 3
    recorded.state = QuantRunState.RUNNING_EXPERIMENTS
    lease = store.claim_agent_run(workspace_id=workspace["workspace_id"], worker_id="snapshot")
    assert lease is not None
    for name, parameters in (
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template="sma_crossover",
            hypothesis="Compare train-only evidence.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        recorded.state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    assert store.compare_agent_candidates(lease)[2] is None
    feedback = next(
        artifact
        for artifact in store.artifacts_for_run(
            workspace_id=workspace["workspace_id"], run_id=run["id"]
        )
        if artifact.kind.value == "iteration_feedback"
    )

    workspace_snapshot = client.get(
        "/v1/quant/workspace-snapshot",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    assert workspace_snapshot.status_code == 200, workspace_snapshot.text
    snapshot = workspace_snapshot.json()
    historical_snapshot = client.get(
        f"/v1/quant/runs/{run['id']}/workspace-snapshot",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    assert historical_snapshot.status_code == 200, historical_snapshot.text
    historical = historical_snapshot.json()

    for payload in (snapshot, historical):
        artifact_ids = {item["id"] for item in payload["artifacts"]}
        event_artifact_ids = {
            item["artifactId"] for item in payload["events"] if "artifactId" in item
        }
        assert feedback.id not in artifact_ids
        assert feedback.id not in event_artifact_ids
        assert any(item["type"] != "iteration_feedback" for item in payload["artifacts"])
        assert all(item["type"] != "iteration_feedback" for item in payload["artifacts"])
        assert all(item.get("artifactId") != feedback.id for item in payload["events"])


def test_iteration_feedback_snapshot_filters_old_feedback_events_but_keeps_other_artifacts(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, name="Old feedback events")
    project = _project(client, principal_id, workspace["workspace_id"], name="Event project")
    run = _run(
        client,
        principal_id,
        workspace["workspace_id"],
        project,
        question="Check legacy feedback event projection.",
    )
    store = QuantStore()
    recorded = store.get_run(workspace_id=workspace["workspace_id"], run_id=run["id"])
    recorded.max_experiments = 3
    recorded.state = QuantRunState.RUNNING_EXPERIMENTS
    lease = store.claim_agent_run(workspace_id=workspace["workspace_id"], worker_id="legacy")
    assert lease is not None
    for name, parameters in (
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template="sma_crossover",
            hypothesis="Compare train-only evidence.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        recorded.state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    assert store.compare_agent_candidates(lease)[2] is None
    feedback = next(
        artifact
        for artifact in store.artifacts_for_run(
            workspace_id=workspace["workspace_id"], run_id=run["id"]
        )
        if artifact.kind.value == "iteration_feedback"
    )
    normal_artifact = next(
        artifact
        for artifact in store.artifacts_for_run(
            workspace_id=workspace["workspace_id"], run_id=run["id"]
        )
        if artifact.kind.value != "iteration_feedback"
    )
    legacy = cast(Any, store)
    legacy._append_event(
        recorded,
        "artifact.published",
        {
            "artifact_id": feedback.id,
            "safe_summary": "Artifact published: Train-only iteration feedback.",
        },
    )
    legacy._append_event(
        recorded,
        "artifact.published",
        {
            "artifact_ids": [feedback.id, normal_artifact.id],
            "safe_summary": "Artifact published: mixed artifact batch.",
        },
    )
    legacy._append_event(
        recorded,
        "tool.completed",
        {
            "action": "compare_candidates",
            "artifact_ids": [feedback.id, normal_artifact.id],
            "safe_summary": (
                "Candidate comparison completed with prior training comparison retained."
            ),
        },
    )
    legacy._append_event(
        recorded,
        "agent.action_selected",
        {
            "action": "create_candidate",
            "expected_result": "Candidate created successfully.",
            "safe_summary": (
                "Creating a candidate from iteration_feedback after the training comparison."
            ),
        },
    )
    legacy._persist_workspace(workspace["workspace_id"])

    current_snapshot = client.get(
        "/v1/quant/workspace-snapshot",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    assert current_snapshot.status_code == 200, current_snapshot.text
    historical_snapshot = client.get(
        f"/v1/quant/runs/{run['id']}/workspace-snapshot",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    assert historical_snapshot.status_code == 200, historical_snapshot.text
    for payload in (current_snapshot.json(), historical_snapshot.json()):
        artifact_ids = {item["id"] for item in payload["artifacts"]}
        assert feedback.id not in artifact_ids
        assert all(
            item.get("artifactId") != feedback.id and feedback.id not in item.get("artifactIds", [])
            for item in payload["events"]
        )
        assert normal_artifact.id in artifact_ids
        assert any(item.get("artifactId") == normal_artifact.id for item in payload["events"])
        comparison_outcome = next(
            item
            for item in payload["events"]
            if item["type"] == "tool.completed"
            and item.get("action") == "compare_candidates"
        )
        assert comparison_outcome["artifactIds"] == [normal_artifact.id]
        assert feedback.id not in comparison_outcome["safeSummary"]
        action_summary = next(
            item["safeSummary"]
            for item in payload["events"]
            if item.get("action") == "create_candidate"
        )
        assert "iteration_feedback" not in action_summary
        assert "prior training comparison" in action_summary


def test_artifact_kind_mapping_is_fail_fast_for_unknown_values() -> None:
    with pytest.raises(ValueError, match="Unsupported artifact kind"):
        quant_snapshot_module.artifact_type_for_kind("totally_new_kind")


@pytest.mark.parametrize(
    ("fixture_state", "expected_state", "expected_command"),
    [
        ("quant-ready", "draft", "generate_plan"),
        ("quant-plan-approval", "waiting_plan_approval", "approve_plan"),
        ("quant-loading-data", "loading_data", None),
        ("quant-generating-candidates", "generating_candidates", None),
        ("quant-running", "running_experiments", "cancel_run"),
        ("quant-repairing", "repairing", "cancel_run"),
        ("quant-validating", "validating", "cancel_run"),
        ("quant-generating-report", "generating_report", None),
        ("quant-waiting-review", "waiting_for_review", "complete_review"),
        ("quant-completed", "completed", None),
        ("quant-no-viable-candidate", "completed", None),
        ("quant-failed-safe", "failed", "retry_run"),
        ("quant-cancelled", "cancelled", "retry_run"),
    ],
)
def test_server_owned_workspace_fixture_states(
    client: TestClient,
    principal_id: str,
    monkeypatch: Any,
    fixture_state: str,
    expected_state: str,
    expected_command: str | None,
) -> None:
    workspace = _workspace(client, principal_id, name=f"{fixture_state} snapshot")
    monkeypatch.setenv("POKIEQUANT_E2E_RUN_STATE", fixture_state)
    response = client.get(
        "/v1/quant/workspace-snapshot",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    )
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert snapshot["run"]["state"] == expected_state
    assert snapshot["authenticity"] == "synthetic_fixture"
    assert snapshot["limits"] == {
        "maxExperiments": 3,
        "maxRepairAttempts": 2,
        "maxRuntimeMinutes": 5,
        "internetAccess": False,
        "arbitraryPython": False,
        "paperTrading": False,
    }
    if expected_state in {
        "loading_data",
        "generating_candidates",
        "running_experiments",
        "repairing",
        "validating",
        "generating_report",
    }:
        assert snapshot["liveResearch"]["phase"] == expected_state
        assert snapshot["liveResearch"]["nextStep"]
        assert isinstance(snapshot["liveResearch"]["candidates"], list)
    else:
        assert snapshot["liveResearch"] is None
    if expected_command:
        assert expected_command in (
            snapshot["run"]["legalCommands"] + snapshot["composerLegalCommands"]
        )
    if fixture_state == "quant-no-viable-candidate":
        assert all(candidate["verdict"] != "promising" for candidate in snapshot["candidates"])
        assert "still completed normally" in snapshot["report"]["conclusion"]
    assert all(
        artifact["authenticity"] == "synthetic_fixture" for artifact in snapshot["artifacts"]
    )
    if expected_state in {
        "draft",
        "waiting_plan_approval",
        "running_experiments",
        "repairing",
        "failed",
        "cancelled",
    }:
        assert snapshot["candidates"] == []
        assert snapshot["trades"] == []
        assert snapshot["benchmark"] is None
        assert snapshot["report"] is None
        assert snapshot["kernelCheck"]["status"] == "available"
        assert snapshot["kernelCheck"]["strategies"] == []
        assert all("marker" not in bar for bar in snapshot["bars"])


def test_workspace_fixture_exposes_computed_kernel_research_evidence() -> None:
    snapshot = quant_workspace_fixture("quant-completed")
    check = snapshot["kernelCheck"]

    assert check == build_quant_kernel_check()
    assert check["status"] == "verified"
    assert check["datasetDigest"] == snapshot["dataset"]["digest"]
    assert check["barCount"] == snapshot["dataset"]["barCount"] == 1564
    assert len(snapshot["bars"]) < snapshot["dataset"]["barCount"]
    assert check["benchmark"]["annualizedReturnPct"] == pytest.approx(
        snapshot["benchmark"]["annualizedReturn"], abs=0.05
    )
    assert [result["id"] for result in check["strategies"]] == [
        "candidate-a",
        "candidate-b",
        "candidate-c",
    ]
    assert snapshot["candidates"][1]["metrics"] == {
        "annualizedReturn": 18.4,
        "maxDrawdown": -11.1,
        "sharpe": 5.07,
        "trades": 2,
    }
    assert "computed" in snapshot["report"]["generationMethod"].lower()
    assert "synthetic" in snapshot["report"]["limitations"][0].lower()


def test_pre_execution_snapshot_does_not_run_research_kernel(monkeypatch: Any) -> None:
    def fail_if_called(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("pre-execution snapshot must not run the research kernel")

    monkeypatch.setattr(quant_snapshot_module, "build_quant_kernel_check", fail_if_called)
    monkeypatch.setattr(quant_snapshot_module, "build_quant_research_projection", fail_if_called)

    snapshot = quant_workspace_fixture("quant-ready")
    assert snapshot["kernelCheck"]["status"] == "available"
    assert snapshot["benchmark"] is None
    assert snapshot["candidates"] == []


def test_workspace_fixture_command_is_api_owned_and_refreshable(
    client: TestClient, principal_id: str, monkeypatch: Any
) -> None:
    workspace = _workspace(client, principal_id, name="Fixture command workspace")
    monkeypatch.setenv("POKIEQUANT_E2E_RUN_STATE", "quant-ready")
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "X-Workspace-ID": workspace["workspace_id"],
    }
    ready = client.get("/v1/quant/workspace-snapshot", headers=headers).json()
    custom_goal = "Compare a bounded SPY trend hypothesis with synthetic evidence."
    response = client.post(
        "/v1/quant/workspace-snapshot/commands",
        headers={**headers, "Idempotency-Key": str(UUID(int=10))},
        json={
            "command": "generate_plan",
            "expected_row_version": ready["run"]["rowVersion"],
            "payload": {"goal": custom_goal},
        },
    )
    assert response.status_code == 200, response.text
    planned = response.json()
    assert planned["run"]["state"] == "waiting_plan_approval"
    assert planned["project"]["goal"] == custom_goal
    assert planned["run"]["rowVersion"] == ready["run"]["rowVersion"] + 1
    refreshed = client.get("/v1/quant/workspace-snapshot", headers=headers).json()
    assert refreshed["run"] == planned["run"]
    assert refreshed["project"]["goal"] == custom_goal

    stale = client.post(
        "/v1/quant/workspace-snapshot/commands",
        headers={**headers, "Idempotency-Key": str(UUID(int=11))},
        json={
            "command": "approve_plan",
            "expected_row_version": ready["run"]["rowVersion"],
            "payload": {},
        },
    )
    assert stale.status_code == 409


def test_synthetic_agent_runs_only_after_plan_approval_and_waits_for_review(
    client: TestClient, principal_id: str, monkeypatch: Any
) -> None:
    workspace = _workspace(client, principal_id, name="Agent workflow workspace")
    monkeypatch.setenv("POKIEQUANT_E2E_RUN_STATE", "quant-ready")
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "X-Workspace-ID": workspace["workspace_id"],
    }

    snapshot = client.get("/v1/quant/workspace-snapshot", headers=headers).json()
    for index, command in enumerate(
        ("generate_plan", "approve_plan", "run_fixture", "complete_review"), start=20
    ):
        response = client.post(
            "/v1/quant/workspace-snapshot/commands",
            headers={**headers, "Idempotency-Key": str(UUID(int=index))},
            json={
                "command": command,
                "expected_row_version": snapshot["run"]["rowVersion"],
                "payload": (
                    {"goal": "Synthetic Agent end-to-end research."}
                    if command == "generate_plan"
                    else {}
                ),
            },
        )
        assert response.status_code == 200, response.text
        snapshot = response.json()
        if command == "run_fixture":
            assert snapshot["run"]["state"] == "waiting_for_review"
            assert "complete_review" in snapshot["run"]["legalCommands"]

    assert snapshot["run"]["state"] == "completed"
    assert snapshot["project"]["goal"] == "Synthetic Agent end-to-end research."


def test_approved_fixture_goal_cannot_change_during_execution(
    client: TestClient, principal_id: str, monkeypatch: Any
) -> None:
    workspace = _workspace(client, principal_id, name="Immutable approved goal workspace")
    monkeypatch.setenv("POKIEQUANT_E2E_RUN_STATE", "quant-ready")
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "X-Workspace-ID": workspace["workspace_id"],
    }
    snapshot = client.get("/v1/quant/workspace-snapshot", headers=headers).json()
    approved_goal = "Evaluate the approved synthetic trend scope."
    for index, (command, payload) in enumerate(
        (("generate_plan", {"goal": approved_goal}), ("approve_plan", {})), start=40
    ):
        response = client.post(
            "/v1/quant/workspace-snapshot/commands",
            headers={**headers, "Idempotency-Key": str(UUID(int=index))},
            json={
                "command": command,
                "expected_row_version": snapshot["run"]["rowVersion"],
                "payload": payload,
            },
        )
        assert response.status_code == 200, response.text
        snapshot = response.json()

    rejected = client.post(
        "/v1/quant/workspace-snapshot/commands",
        headers={**headers, "Idempotency-Key": str(UUID(int=42))},
        json={
            "command": "run_fixture",
            "expected_row_version": snapshot["run"]["rowVersion"],
            "payload": {"goal": "Replace the approved goal."},
        },
    )
    assert rejected.status_code == 409
    refreshed = client.get("/v1/quant/workspace-snapshot", headers=headers).json()
    assert refreshed["run"]["state"] == "running_experiments"
    assert refreshed["project"]["goal"] == approved_goal


def test_quant_repository_survives_fresh_adapter_and_is_workspace_scoped(
    client: TestClient, principal_id: str
) -> None:
    first = _workspace(client, principal_id, name="Durable Quant workspace")
    project = _project(client, principal_id, first["workspace_id"], name="Durable project")
    fresh = QuantStore()
    restored = fresh.get_project(workspace_id=first["workspace_id"], project_id=project["id"])
    assert restored.name == "Durable project"

    second_response = client.post(
        "/v1/workspaces",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=14)),
        },
        json={
            "name": "Isolated Quant workspace",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert second_response.status_code == 201
    second = second_response.json()
    hidden = client.get(
        f"/v1/quant/projects/{project['id']}",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": second["workspace_id"],
        },
    )
    assert hidden.status_code == 404


def test_cancel_advances_fence_and_old_worker_claim_cannot_emit(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, name="Fenced Quant workspace")
    project = _project(client, principal_id, workspace["workspace_id"], name="Fence project")
    run = _run(client, principal_id, workspace["workspace_id"], project, question="Fence?")
    approved_response = client.post(
        f"/v1/quant/runs/{run['id']}/approve-plan",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=12)),
            "X-Workspace-ID": workspace["workspace_id"],
        },
        json={
            "expected_row_version": run["row_version"],
            "plan_revision": run["plan_revision"],
            "reason": "Approve fenced fixture.",
        },
    )
    assert approved_response.status_code == 200
    approved = approved_response.json()
    worker_store = QuantStore()
    lease = worker_store.claim_fixture_run(
        workspace_id=workspace["workspace_id"], worker_id="worker-old"
    )
    assert lease is not None
    sequence_before_cancel = approved["latest_sequence"]
    assert worker_store.heartbeat_fixture_run(lease)
    after_heartbeat = client.get(
        f"/v1/quant/runs/{run['id']}",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    ).json()
    assert after_heartbeat["latest_sequence"] == sequence_before_cancel

    cancelled_response = client.post(
        f"/v1/quant/runs/{run['id']}/cancel",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=13)),
            "X-Workspace-ID": workspace["workspace_id"],
        },
        json={
            "expected_row_version": approved["row_version"],
            "reason": "Fence the active worker.",
        },
    )
    assert cancelled_response.status_code == 200
    assert worker_store.execute_fixture_claim(lease, fixture_state="completed") is False
    cancelled = client.get(
        f"/v1/quant/runs/{run['id']}",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    ).json()
    assert cancelled["state"] == "cancelled"
    assert cancelled["latest_sequence"] == sequence_before_cancel + 1


def test_browser_fixture_bundle_matches_server_fixture_contract() -> None:
    bundle_path = Path(__file__).parents[2] / "apps/mac/e2e/fixtures/quant-workspace-fixtures.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert set(bundle) == set(FIXTURE_STATES)
    assert bundle == {state: quant_workspace_fixture(state) for state in sorted(FIXTURE_STATES)}

    mac_fixture_path = (
        Path(__file__).parents[2] / "apps/mac/src/features/quant/quant-fixture.generated.json"
    )
    mac_fixture = json.loads(mac_fixture_path.read_text(encoding="utf-8"))
    assert mac_fixture == quant_workspace_fixture("quant-completed")


def test_quant_commands_are_idempotent_and_retry_returns_one_child(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, name="Retry workspace")
    project = _project(client, principal_id, workspace["workspace_id"], name="Retry project")
    run = _run(client, principal_id, workspace["workspace_id"], project, question="Retry?")

    cancel_headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(UUID(int=5)),
        "X-Workspace-ID": workspace["workspace_id"],
    }
    cancel = client.post(
        f"/v1/quant/runs/{run['id']}/cancel",
        headers=cancel_headers,
        json={"expected_row_version": run["row_version"], "reason": "No longer needed."},
    )
    assert cancel.status_code == 200, cancel.text
    cancelled = cancel.json()
    assert cancelled["state"] == "cancelled"

    second_cancel = client.post(
        f"/v1/quant/runs/{run['id']}/cancel",
        headers={**cancel_headers, "Idempotency-Key": str(UUID(int=6))},
        json={"expected_row_version": cancelled["row_version"], "reason": "No longer needed."},
    )
    assert second_cancel.status_code == 200, second_cancel.text
    assert second_cancel.json()["id"] == cancelled["id"]

    retry = client.post(
        f"/v1/quant/runs/{run['id']}/retry",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=7)),
            "X-Workspace-ID": workspace["workspace_id"],
        },
        json={"expected_row_version": cancelled["row_version"], "reason": "Retry after cancel."},
    )
    assert retry.status_code == 201, retry.text
    child = retry.json()
    second_retry = client.post(
        f"/v1/quant/runs/{run['id']}/retry",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=8)),
            "X-Workspace-ID": workspace["workspace_id"],
        },
        json={
            "expected_row_version": cancelled["row_version"] + 1,
            "reason": "Retry after cancel.",
        },
    )
    assert second_retry.status_code == 201, second_retry.text
    assert second_retry.json()["id"] == child["id"]


@pytest.mark.parametrize(
    ("fixture_state", "expected_state", "artifact_count", "experiment_count"),
    [
        ("completed", "completed", 7, 3),
        ("completed_no_viable_candidates", "completed", 7, 3),
        ("completed_rejected_candidate", "completed", 7, 3),
        ("failed", "failed", 4, 0),
    ],
)
def test_quant_fixture_runner_state_matrix(
    client: TestClient,
    principal_id: str,
    monkeypatch: Any,
    fixture_state: str,
    expected_state: str,
    artifact_count: int,
    experiment_count: int,
) -> None:
    workspace = _workspace(client, principal_id, name=f"{fixture_state} workspace")
    project = _project(
        client, principal_id, workspace["workspace_id"], name=f"{fixture_state} project"
    )
    run = _run(client, principal_id, workspace["workspace_id"], project, question="Matrix?")

    approve = client.post(
        f"/v1/quant/runs/{run['id']}/approve-plan",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(UUID(int=9)),
            "X-Workspace-ID": workspace["workspace_id"],
        },
        json={
            "expected_row_version": run["row_version"],
            "plan_revision": run["plan_revision"],
            "reason": "Approved for fixture matrix.",
        },
    )
    assert approve.status_code == 200, approve.text

    monkeypatch.setenv("POKIEQUANT_E2E_RUN_STATE", fixture_state)
    assert run_quant_fixture_once(workspace_id=workspace["workspace_id"])
    stored_run = client.get(
        f"/v1/quant/runs/{run['id']}",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace["workspace_id"],
        },
    ).json()
    assert stored_run["state"] == expected_state
    assert (
        len(
            client.get(
                f"/v1/quant/runs/{run['id']}/artifacts",
                headers={
                    "Authorization": f"Bearer {principal_id}",
                    "X-Workspace-ID": workspace["workspace_id"],
                },
            ).json()
        )
        == artifact_count
    )
    assert (
        len(
            client.get(
                f"/v1/quant/runs/{run['id']}/experiments",
                headers={
                    "Authorization": f"Bearer {principal_id}",
                    "X-Workspace-ID": workspace["workspace_id"],
                },
            ).json()
        )
        == experiment_count
    )
