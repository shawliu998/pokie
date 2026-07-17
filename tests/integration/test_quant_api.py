from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from services.api.app.modules.quant.snapshot import FIXTURE_STATES, quant_workspace_fixture
from services.api.app.modules.quant.store import QuantStore
from services.worker.app.pipelines.quant_fixture import run_quant_fixture_once


def _workspace(client: TestClient, principal_id: str, name: str = "Quant workspace") -> dict[str, Any]:
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


def test_quant_surface_round_trip_and_event_recovery(
    client: TestClient, principal_id: str
) -> None:
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
        headers={"Authorization": f"Bearer {principal_id}", "X-Workspace-ID": workspace["workspace_id"]},
    )
    assert completed.status_code == 200, completed.text
    completed_run = completed.json()
    assert completed_run["state"] == "completed"
    assert completed_run["latest_sequence"] >= 6

    artifacts = client.get(
        f"/v1/quant/runs/{run['id']}/artifacts",
        headers={"Authorization": f"Bearer {principal_id}", "X-Workspace-ID": workspace["workspace_id"]},
    )
    experiments = client.get(
        f"/v1/quant/runs/{run['id']}/experiments",
        headers={"Authorization": f"Bearer {principal_id}", "X-Workspace-ID": workspace["workspace_id"]},
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


@pytest.mark.parametrize(
    ("fixture_state", "expected_state", "expected_command"),
    [
        ("quant-ready", "draft", "generate_plan"),
        ("quant-plan-approval", "waiting_plan_approval", "approve_plan"),
        ("quant-running", "running_experiments", "cancel_run"),
        ("quant-repairing", "repairing", "cancel_run"),
        ("quant-validating", "validating", "cancel_run"),
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
    if expected_command:
        assert expected_command in (
            snapshot["run"]["legalCommands"] + snapshot["composerLegalCommands"]
        )
    if fixture_state == "quant-no-viable-candidate":
        assert all(candidate["verdict"] != "promising" for candidate in snapshot["candidates"])
        assert "still completed normally" in snapshot["report"]["conclusion"]
    assert all(artifact["authenticity"] == "synthetic_fixture" for artifact in snapshot["artifacts"])


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
    response = client.post(
        "/v1/quant/workspace-snapshot/commands",
        headers={**headers, "Idempotency-Key": str(UUID(int=10))},
        json={
            "command": "generate_plan",
            "expected_row_version": ready["run"]["rowVersion"],
            "payload": {},
        },
    )
    assert response.status_code == 200, response.text
    planned = response.json()
    assert planned["run"]["state"] == "waiting_plan_approval"
    assert planned["run"]["rowVersion"] == ready["run"]["rowVersion"] + 1
    refreshed = client.get("/v1/quant/workspace-snapshot", headers=headers).json()
    assert refreshed["run"] == planned["run"]

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


def test_quant_repository_survives_fresh_adapter_and_is_workspace_scoped(
    client: TestClient, principal_id: str
) -> None:
    first = _workspace(client, principal_id, name="Durable Quant workspace")
    project = _project(client, principal_id, first["workspace_id"], name="Durable project")
    fresh = QuantStore()
    restored = fresh.get_project(
        workspace_id=first["workspace_id"], project_id=project["id"]
    )
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
    bundle_path = (
        Path(__file__).parents[2]
        / "apps/mac/e2e/fixtures/quant-workspace-fixtures.json"
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert set(bundle) == set(FIXTURE_STATES)
    assert bundle == {state: quant_workspace_fixture(state) for state in sorted(FIXTURE_STATES)}


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
        json={"expected_row_version": cancelled["row_version"] + 1, "reason": "Retry after cancel."},
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
    project = _project(client, principal_id, workspace["workspace_id"], name=f"{fixture_state} project")
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
    assert len(
        client.get(
            f"/v1/quant/runs/{run['id']}/artifacts",
            headers={
                "Authorization": f"Bearer {principal_id}",
                "X-Workspace-ID": workspace["workspace_id"],
            },
        ).json()
    ) == artifact_count
    assert len(
        client.get(
            f"/v1/quant/runs/{run['id']}/experiments",
            headers={
                "Authorization": f"Bearer {principal_id}",
                "X-Workspace-ID": workspace["workspace_id"],
            },
        ).json()
    ) == experiment_count
