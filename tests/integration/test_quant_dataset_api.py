from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.modules.quant.store import get_quant_store
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.provider import MockQuantAgentProvider


def _daily_csv(*, last_close_adjustment: float = 0) -> str:
    rows = ["date,open,high,low,close,volume"]
    start = date(2023, 1, 1)
    for index in range(300):
        trading_date = start + timedelta(days=index)
        baseline = 100 + index / 50
        open_price = baseline + 8 * math.sin((index - 1) / 8)
        close_price = baseline + 8 * math.sin(index / 8)
        if index == 299:
            close_price += last_close_adjustment
        rows.append(
            f"{trading_date.isoformat()},{open_price:.2f},{max(open_price, close_price) + 1:.2f},"
            f"{min(open_price, close_price) - 1:.2f},{close_price:.2f},{1200 + index}"
        )
    return "\n".join(rows) + "\n"


CSV_V1 = _daily_csv()
CSV_V2 = _daily_csv(last_close_adjustment=0.25)


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _workspace(client: TestClient, principal_id: str, name: str) -> dict[str, Any]:
    response = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={"name": name, "data_region": "local", "retention_policy_version": "retention-v1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _project(client: TestClient, principal_id: str, workspace_id: str) -> dict[str, Any]:
    response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Imported OHLCV", "objective": "Research this pinned local dataset."},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _import(
    client: TestClient, principal_id: str, workspace_id: str, csv_text: str
) -> dict[str, Any]:
    response = client.post(
        "/v1/quant/datasets/import-csv",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Acme daily bars", "symbol": "acme", "csv_text": csv_text},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_run(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    project: dict[str, Any],
    dataset_id: str,
) -> Any:
    return client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "question": "Compare the bounded imported ACME dataset.",
            "mode": "auto",
            "expected_project_row_version": project["row_version"],
            "dataset_id": dataset_id,
        },
    )


def test_imported_ohlcv_dataset_is_listed_pinned_and_exposed_to_agent_context(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, "Dataset import workspace")
    workspace_id = workspace["workspace_id"]
    dataset = _import(client, principal_id, workspace_id, CSV_V1)

    listed = client.get("/v1/quant/datasets", headers=_headers(principal_id, workspace_id))
    assert listed.status_code == 200, listed.text
    assert listed.json() == [dataset]
    assert dataset["symbol"] == "ACME"
    assert dataset["bar_count"] == 300
    assert dataset["digest"].startswith("sha256:")

    project = _project(client, principal_id, workspace_id)
    created = _create_run(client, principal_id, workspace_id, project, dataset["dataset_id"])
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["dataset_id"] == dataset["dataset_id"]
    assert run["dataset_digest"] == dataset["digest"]

    context = get_quant_store().agent_context_data(
        workspace_id=workspace_id, run_id=run["id"]
    )
    assert context["dataset_summary"] == {
        "dataset_id": dataset["dataset_id"],
        "symbol": "ACME",
        "interval": "1D",
        "bars": 300,
        "start": "2023-01-01",
        "end": "2023-10-27",
        "digest": dataset["digest"],
        "authenticity": "imported_fixture",
    }
    snapshot = client.get(
        "/v1/quant/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["authenticity"] == "imported_fixture"
    assert snapshot.json()["dataset"] == {
        "id": dataset["dataset_id"],
        "name": "Acme daily bars",
        "symbol": "ACME",
        "interval": "1D",
        "dateRange": {"start": "2023-01-01", "end": "2023-10-27"},
        "barCount": 300,
        "schemaVersion": "quant-daily-bars-v1",
        "parserVersion": "quant-ohlcv-csv-v1",
        "digest": dataset["digest"],
        "authenticity": "imported_fixture",
    }
    assert snapshot.json()["kernelCheck"]["datasetId"] == dataset["dataset_id"]
    assert snapshot.json()["kernelCheck"]["datasetDigest"] == dataset["digest"]
    assert snapshot.json()["kernelCheck"]["barCount"] == 300

    for _ in range(12):
        if not run_quant_agent_once(
            provider=MockQuantAgentProvider(), workspace_id=workspace_id
        ):
            break
    completed = client.get(
        "/v1/quant/workspace-snapshot",
        headers=_headers(principal_id, workspace_id),
    )
    assert completed.status_code == 200, completed.text
    completed_snapshot = completed.json()
    assert completed_snapshot["run"]["state"] == "completed"
    assert completed_snapshot["kernelCheck"]["status"] == "verified"
    assert completed_snapshot["kernelCheck"]["datasetId"] == dataset["dataset_id"]
    assert completed_snapshot["kernelCheck"]["benchmark"] is not None
    assert completed_snapshot["kernelCheck"]["strategies"]
    assert completed_snapshot["trades"]
    assert any("marker" in bar for bar in completed_snapshot["bars"])


def test_changed_csv_creates_new_dataset_while_existing_run_remains_pinned(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, "Immutable dataset workspace")
    workspace_id = workspace["workspace_id"]
    first = _import(client, principal_id, workspace_id, CSV_V1)
    project = _project(client, principal_id, workspace_id)
    response = _create_run(client, principal_id, workspace_id, project, first["dataset_id"])
    assert response.status_code == 201, response.text
    old_run = response.json()

    replacement = _import(client, principal_id, workspace_id, CSV_V2)
    assert replacement["dataset_id"] != first["dataset_id"]
    assert replacement["digest"] != first["digest"]

    retrieved = client.get(
        f"/v1/quant/runs/{old_run['id']}", headers=_headers(principal_id, workspace_id)
    )
    assert retrieved.status_code == 200, retrieved.text
    assert retrieved.json()["dataset_id"] == first["dataset_id"]
    assert retrieved.json()["dataset_digest"] == first["digest"]
    assert get_quant_store().agent_context_data(
        workspace_id=workspace_id, run_id=old_run["id"]
    )["dataset_summary"]["digest"] == first["digest"]


def test_unknown_or_cross_workspace_dataset_cannot_be_bound_to_a_run(
    client: TestClient, principal_id: str
) -> None:
    first_workspace = _workspace(client, principal_id, "Dataset owner workspace")
    first_dataset = _import(client, principal_id, first_workspace["workspace_id"], CSV_V1)
    second_workspace = _workspace(client, principal_id, "Dataset consumer workspace")
    second_workspace_id = second_workspace["workspace_id"]
    project = _project(client, principal_id, second_workspace_id)

    cross_workspace = _create_run(
        client, principal_id, second_workspace_id, project, first_dataset["dataset_id"]
    )
    assert cross_workspace.status_code == 404
    assert cross_workspace.json()["error"]["code"] == "NOT_FOUND"

    unknown = _create_run(client, principal_id, second_workspace_id, project, "ohlcv-ACME-missing")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "NOT_FOUND"


def test_too_short_import_is_retained_but_rejected_for_autonomous_research(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, "Short dataset workspace")
    workspace_id = workspace["workspace_id"]
    dataset = _import(
        client,
        principal_id,
        workspace_id,
        "date,open,high,low,close\n2024-01-02,100,102,99,101\n",
    )
    project = _project(client, principal_id, workspace_id)

    response = _create_run(
        client, principal_id, workspace_id, project, dataset["dataset_id"]
    )

    assert response.status_code == 409
    assert "at least 252 daily bars" in response.json()["error"]["message"]
