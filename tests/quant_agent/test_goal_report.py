from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.modules.quant.store import QuantStore
from services.worker.app.pipelines.quant_agent import run_quant_agent_once


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {principal_id}", "Idempotency-Key": str(uuid4())}
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
            "name": f"Goal {uuid4().hex[:8]}",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert workspace_response.status_code == 201
    workspace_id = workspace_response.json()["workspace_id"]
    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Goal differentiation test", "objective": goal},
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


def _finish(workspace_id: str, run_id: str, maximum_polls: int = 25) -> QuantStore:
    for _ in range(maximum_polls):
        if not run_quant_agent_once(workspace_id=workspace_id):
            break
        store = QuantStore()
        run = store.get_run(workspace_id=workspace_id, run_id=run_id)
        if run.state.value in {"completed", "failed", "cancelled"}:
            return store
    return QuantStore()


def test_different_goals_produce_different_reports(
    client: TestClient, principal_id: str
) -> None:
    drawdown_workspace, drawdown_run = _create_auto_run(
        client, principal_id, "Reduce maximum drawdown."
    )
    opportunity_workspace, opportunity_run = _create_auto_run(
        client, principal_id, "Find more trading opportunities."
    )
    drawdown_store = _finish(drawdown_workspace, drawdown_run["id"])
    opportunity_store = _finish(opportunity_workspace, opportunity_run["id"])

    def report(store: QuantStore, workspace_id: str, run_id: str) -> dict[str, Any]:
        artifacts = store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        report_artifacts = [
            item for item in artifacts if item.kind.value == "research_report"
        ]
        assert report_artifacts
        return report_artifacts[-1].content

    drawdown_report = report(drawdown_store, drawdown_workspace, drawdown_run["id"])
    opportunity_report = report(
        opportunity_store, opportunity_workspace, opportunity_run["id"]
    )
    assert drawdown_report["research_goal"] != opportunity_report["research_goal"]
    drawdown_names = {item["name"] for item in drawdown_report["candidates_tested"]}
    opportunity_names = {item["name"] for item in opportunity_report["candidates_tested"]}
    assert drawdown_names != opportunity_names
