from __future__ import annotations

import math
from datetime import date, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.api.app.modules.quant.store import QuantStore, get_quant_store
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.provider import MockQuantAgentProvider


def _daily_csv(
    *,
    last_close_adjustment: float = 0,
    holdout_daily_trend: float = 0,
    gap_days_after_150: int = 0,
) -> str:
    rows = ["date,open,high,low,close,volume"]
    start = date(2023, 1, 1)
    for index in range(300):
        trading_date = start + timedelta(
            days=index + (gap_days_after_150 if index >= 150 else 0)
        )
        baseline = 100 + index / 50
        open_price = baseline + 8 * math.sin((index - 1) / 8)
        close_price = baseline + 8 * math.sin(index / 8)
        if index >= 240:
            holdout_adjustment = holdout_daily_trend * (index - 239)
            open_price += holdout_adjustment
            close_price += holdout_adjustment
        if index == 299:
            close_price += last_close_adjustment
        rows.append(
            f"{trading_date.isoformat()},{open_price:.2f},{max(open_price, close_price) + 1:.2f},"
            f"{min(open_price, close_price) - 1:.2f},{close_price:.2f},{1200 + index}"
        )
    return "\n".join(rows) + "\n"


CSV_V1 = _daily_csv()
CSV_V2 = _daily_csv(last_close_adjustment=0.25)
CSV_HOLDOUT_TREND = _daily_csv(holdout_daily_trend=0.5)
CSV_BLOCKED_GAP = _daily_csv(gap_days_after_150=20)


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
        json={
            "name": "Acme daily bars",
            "symbol": "acme",
            "csv_text": csv_text,
            "file_name": "acme-daily.csv",
            "source_name": "ACME Research Export",
            "source_reference": "internal-export:acme-daily-v1",
            "price_adjustment": "split_adjusted",
        },
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


def _quality_snapshot(quality: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": quality["schema_version"],
        "policyVersion": quality["policy_version"],
        "status": quality["status"],
        "verificationStatus": quality["verification_status"],
        "reportDigest": quality["report_digest"],
        "datasetDigest": quality["dataset_digest"],
        "barCount": quality["bar_count"],
        "calendarGapCount": quality["calendar_gap_count"],
        "largestCalendarGapDays": quality["largest_calendar_gap_days"],
        "unexpectedSessionCount": quality["unexpected_session_count"],
        "zeroVolumeBarCount": quality["zero_volume_bar_count"],
        "priceJumpCount": quality["price_jump_count"],
        "issues": quality["issues"],
        "notes": quality["notes"],
    }


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
    assert dataset["source_metadata"] == {
        "kind": "csv_upload",
        "file_name": "acme-daily.csv",
        "source_name": "ACME Research Export",
        "source_reference": "internal-export:acme-daily-v1",
        "submitted_csv_digest": "sha256:"
        + sha256(CSV_V1.strip().encode("utf-8")).hexdigest(),
        "market_calendar": "unknown",
        "time_zone": "UTC",
        "price_adjustment": "split_adjusted",
    }
    assert dataset["data_quality"]["status"] == "warning"
    assert dataset["data_quality"]["verification_status"] == "checked"
    assert dataset["data_quality"]["dataset_digest"] == dataset["digest"]

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
        "source_metadata": dataset["source_metadata"],
        "data_quality": dataset["data_quality"],
        "evaluation_partition": "train",
        "split": {
            "method": "chronological",
            "rule_version": "chronological-80-20-v1",
            "train_bar_count": 240,
            "holdout_bar_count": 60,
            "train_start": "2023-01-01",
            "train_end": "2023-08-28",
            "holdout_start": "2023-08-29",
            "holdout_end": "2023-10-27",
            "cutoff_date": "2023-08-29",
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["digest"],
        },
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
        "source": {
            "kind": "csv_upload",
            "fileName": "acme-daily.csv",
            "sourceName": "ACME Research Export",
            "sourceReference": "internal-export:acme-daily-v1",
            "submittedCsvDigest": dataset["source_metadata"]["submitted_csv_digest"],
            "marketCalendar": "unknown",
            "timeZone": "UTC",
            "priceAdjustment": "split_adjusted",
        },
        "quality": _quality_snapshot(dataset["data_quality"]),
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
    assert completed_snapshot["composerLegalCommands"] == ["start_auto_research"]
    generalization = completed_snapshot["report"]["generalization"]
    assert generalization["status"] in {"pass", "fail", "inconclusive"}
    assert generalization["split"] == {
        "method": "chronological",
        "ruleVersion": "chronological-80-20-v1",
        "trainBarCount": 240,
        "holdoutBarCount": 60,
        "cutoffDate": "2023-08-29",
        "datasetId": dataset["dataset_id"],
        "datasetDigest": dataset["digest"],
    }
    assert generalization["train"]["candidate"]
    assert generalization["train"]["benchmark"]
    assert generalization["holdout"]["candidate"]
    assert generalization["holdout"]["benchmark"]
    walk_forward = completed_snapshot["report"]["walkForward"]
    assert walk_forward["evaluationPartition"] == "train"
    assert walk_forward["ruleVersion"] == "expanding-3fold-20pct-regime-v1"
    assert walk_forward["foldCount"] == 3
    assert walk_forward["windowBarCount"] == 48
    assert walk_forward["stateRuleVersion"] == "trailing-60bar-trend-vol-v1"
    assert walk_forward["stateLookbackBars"] == 60
    assert [
        (fold["historyEnd"], fold["evaluationStart"], fold["evaluationEnd"])
        for fold in walk_forward["folds"]
    ] == [
        ("2023-04-06", "2023-04-07", "2023-05-24"),
        ("2023-05-24", "2023-05-25", "2023-07-11"),
        ("2023-07-11", "2023-07-12", "2023-08-28"),
    ]
    assert all(
        fold["marketRegime"]["historyEnd"] < fold["evaluationStart"]
        and fold["marketRegime"]["historyBarCount"] <= 60
        for fold in walk_forward["folds"]
    )
    assert sum(item["foldCount"] for item in walk_forward["aggregate"]["byMarketRegime"]) == 3

    persisted_artifacts = QuantStore().artifacts_for_run(
        workspace_id=workspace_id, run_id=run["id"]
    )
    restored_dataset = QuantStore().get_dataset(
        workspace_id=workspace_id, dataset_id=dataset["dataset_id"]
    )
    assert restored_dataset is not None
    assert restored_dataset.source_metadata.model_dump(mode="json") == dataset[
        "source_metadata"
    ]
    assert restored_dataset.data_quality is not None
    assert restored_dataset.data_quality.model_dump(mode="json") == dataset["data_quality"]
    with pytest.raises(ValidationError):
        restored_dataset.source_metadata.source_name = "Mutated provenance"
    research_reports = [
        item for item in persisted_artifacts if item.kind.value == "research_report"
    ]
    assert len(research_reports) == 1
    assert research_reports[0].content["dataset"]["digest"] == dataset["digest"]
    assert (
        research_reports[0].content["dataset"]["source_metadata"]
        == dataset["source_metadata"]
    )
    assert research_reports[0].content["dataset"]["data_quality"] == dataset[
        "data_quality"
    ]
    assert research_reports[0].content["generalization"]["split"]["train_bar_count"] == 240
    assert not run_quant_agent_once(
        provider=MockQuantAgentProvider(), workspace_id=workspace_id
    )
    assert len(
        QuantStore().artifacts_for_run(workspace_id=workspace_id, run_id=run["id"])
    ) == len(persisted_artifacts)

    next_run = client.post(
        "/v1/quant/workspace-snapshot/commands",
        headers=_headers(principal_id, workspace_id),
        json={
            "command": "start_auto_research",
            "expected_row_version": completed_snapshot["run"]["rowVersion"],
            "payload": {
                "goal": "Run a second bounded study on the selected ACME dataset.",
                "dataset_id": dataset["dataset_id"],
            },
        },
    )
    assert next_run.status_code == 200, next_run.text
    assert next_run.json()["run"]["id"] != completed_snapshot["run"]["id"]
    assert next_run.json()["dataset"]["id"] == dataset["dataset_id"]


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


def test_holdout_changes_do_not_change_training_selection(
    client: TestClient, principal_id: str
) -> None:
    def complete(csv_text: str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
        workspace_id = _workspace(client, principal_id, name)["workspace_id"]
        dataset = _import(client, principal_id, workspace_id, csv_text)
        project = _project(client, principal_id, workspace_id)
        created = _create_run(
            client, principal_id, workspace_id, project, dataset["dataset_id"]
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["id"]
        for _ in range(12):
            assert run_quant_agent_once(
                provider=MockQuantAgentProvider(), workspace_id=workspace_id
            )
            if (
                QuantStore()
                .get_run(workspace_id=workspace_id, run_id=run_id)
                .state.value
                == "completed"
            ):
                break
        artifacts = QuantStore().artifacts_for_run(
            workspace_id=workspace_id, run_id=run_id
        )
        comparison = next(
            item.content for item in artifacts if item.kind.value == "validation_report"
        )
        report = next(
            item.content for item in artifacts if item.kind.value == "research_report"
        )
        return comparison, report

    baseline_comparison, baseline_report = complete(CSV_V1, "Baseline holdout")
    changed_comparison, changed_report = complete(
        CSV_HOLDOUT_TREND, "Changed holdout"
    )

    def training_evidence(comparison: dict[str, Any]) -> dict[str, Any]:
        return {
            "benchmark": comparison["benchmark"],
            "candidates": [
                {key: value for key, value in row.items() if key != "candidate_id"}
                for row in comparison["candidates"]
            ],
        }

    assert training_evidence(baseline_comparison) == training_evidence(changed_comparison)
    assert [item["walk_forward"] for item in baseline_comparison["candidates"]] == [
        item["walk_forward"] for item in changed_comparison["candidates"]
    ]
    baseline_selected = next(
        item["name"]
        for item in baseline_report["candidates_tested"]
        if item["candidate_id"] == baseline_report["selected_candidate_id"]
    )
    changed_selected = next(
        item["name"]
        for item in changed_report["candidates_tested"]
        if item["candidate_id"] == changed_report["selected_candidate_id"]
    )
    assert baseline_selected == changed_selected
    assert (
        baseline_report["generalization"]["holdout"]["candidate"]
        != changed_report["generalization"]["holdout"]["candidate"]
    )


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


def test_blocking_data_quality_issue_is_retained_but_cannot_start_a_run(
    client: TestClient, principal_id: str
) -> None:
    workspace = _workspace(client, principal_id, "Blocked quality workspace")
    workspace_id = workspace["workspace_id"]
    dataset = _import(client, principal_id, workspace_id, CSV_BLOCKED_GAP)
    assert dataset["data_quality"]["status"] == "blocked"
    assert dataset["data_quality"]["verification_status"] == "rejected"
    assert any(
        issue["code"] == "EXCESSIVE_ELAPSED_GAP"
        for issue in dataset["data_quality"]["issues"]
    )
    project = _project(client, principal_id, workspace_id)

    response = _create_run(
        client, principal_id, workspace_id, project, dataset["dataset_id"]
    )

    assert response.status_code == 409
    assert "EXCESSIVE_ELAPSED_GAP" in response.json()["error"]["message"]
