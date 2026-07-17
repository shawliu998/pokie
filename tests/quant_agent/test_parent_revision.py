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
            "name": f"Parent {uuid4().hex[:8]}",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert workspace_response.status_code == 201
    workspace_id = workspace_response.json()["workspace_id"]
    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Parent revision test", "objective": goal},
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


def test_revised_candidate_carries_parent_experiment_id(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run = _create_auto_run(
        client, principal_id, "Find more trading opportunities without excessive drawdown."
    )
    for _ in range(25):
        if not run_quant_agent_once(workspace_id=workspace_id):
            break
        store = QuantStore()
        current = store.get_run(workspace_id=workspace_id, run_id=run["id"])
        if current.state.value in {"completed", "failed", "cancelled"}:
            break

    store = QuantStore()
    experiments = store.experiments_for_run(workspace_id=workspace_id, run_id=run["id"])
    revised = [item for item in experiments if item.parent_experiment_id is not None]
    assert revised, "Expected at least one revised candidate"
    for item in revised:
        parent = next(
            (parent for parent in experiments if parent.id == item.parent_experiment_id), None
        )
        assert parent is not None
        assert parent.template == item.template
        assert parent.run_id == item.run_id
        assert parent.metrics is not None
