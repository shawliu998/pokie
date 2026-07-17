from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.modules.quant.store import QuantStore
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
    assert drawdown_actions != opportunity_actions
    assert "revise_candidate" in opportunity_actions

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
    assert store.claim_agent_run(
        workspace_id=workspace_id, worker_id="tool-failure-recovery"
    ) is not None
