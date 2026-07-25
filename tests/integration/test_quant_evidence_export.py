from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from packages.contracts.quant import QuantBarInterval
from packages.domain.canonical import canonical_digest
from services.api.app.modules.quant import evidence_export as evidence_export_module
from services.api.app.modules.quant import store as quant_store_module
from services.api.app.modules.quant.store import QuantStore
from services.worker.app.pipelines.quant_agent import run_quant_agent_once


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {principal_id}", "Idempotency-Key": str(uuid4())}
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _workspace(client: TestClient, principal_id: str, name: str) -> str:
    response = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={"name": name, "data_region": "local", "retention_policy_version": "retention-v1"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["workspace_id"])


def _market_csv() -> str:
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    rows = ["timestamp,open,high,low,close,volume"]
    for index in range(548):
        opening = Decimal("100") + Decimal(index % 17) / Decimal("10")
        close = opening + Decimal((index % 5) - 2) / Decimal("20")
        rows.append(
            f"{timestamp.isoformat().replace('+00:00', 'Z')},{opening},"
            f"{max(opening, close) + Decimal('0.25')},{min(opening, close) - Decimal('0.25')},"
            f"{close},{Decimal('12.3') + index}"
        )
        timestamp += timedelta(hours=4)
    return "\n".join(rows) + "\n"


def _completed_run(client: TestClient, principal_id: str, *, market: bool) -> tuple[str, str, str]:
    workspace_id = _workspace(
        client, principal_id, f"Evidence export {'market' if market else 'daily'}"
    )
    project = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Evidence", "objective": "Retain authoritative evidence."},
    )
    assert project.status_code == 201, project.text
    if market:
        dataset = client.post(
            "/v1/quant/datasets/v2/import-csv",
            headers=_headers(principal_id, workspace_id),
            json={
                "name": "BTCUSDT 4h",
                "symbol": "BTCUSDT",
                "interval": QuantBarInterval.FOUR_HOURS.value,
                "csv_text": _market_csv(),
                "file_name": "btcusdt-4h.csv",
                "source_name": "Controlled CSV",
                "source_reference": "test:evidence-export",
            },
        )
        assert dataset.status_code == 201, dataset.text
        payload = {
            "project_id": project.json()["id"],
            "mode": "auto",
            "question": "Retain exact market evidence.",
            "expected_project_row_version": project.json()["row_version"],
            "dataset_id": dataset.json()["dataset_id"],
            "research_start_utc": dataset.json()["covered_start"],
            "research_end_utc": dataset.json()["covered_end"],
        }
        path = "/v1/quant/market-runs"
    else:
        payload = {
            "project_id": project.json()["id"],
            "mode": "auto",
            "question": "Retain exact daily evidence.",
            "expected_project_row_version": project.json()["row_version"],
        }
        path = "/v1/quant/runs"
    created = client.post(path, headers=_headers(principal_id, workspace_id), json=payload)
    assert created.status_code == 201, created.text
    run_id = str(created.json()["id"])
    for _ in range(12):
        if not run_quant_agent_once(workspace_id=workspace_id):
            break
        current = QuantStore().get_run(workspace_id=workspace_id, run_id=run_id)
        if current.state.value == "completed":
            break
    store = QuantStore()
    report = next(
        item.content
        for item in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if item.kind.value == "research_report"
    )
    return workspace_id, run_id, str(report["selected_candidate_id"])


@pytest.mark.parametrize("market", [False, True], ids=["legacy_daily", "market_v2"])
def test_final_evidence_bundle_is_deterministic_persisted_and_zero_recompute(
    client: TestClient, principal_id: str, monkeypatch: pytest.MonkeyPatch, market: bool
) -> None:
    workspace_id, run_id, selected_id = _completed_run(client, principal_id, market=market)
    headers = _headers(principal_id, workspace_id)
    payload = {
        "export_type": "strategy_evidence_bundle_json",
        "run_id": run_id,
        "candidate_id": selected_id,
    }
    # The exporter must only read retained records; a quantitative recomputation is a failure.
    monkeypatch.setattr(
        quant_store_module,
        "backtest_buy_and_hold",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not backtest")),
    )
    first = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json=payload,
    )
    second = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    response = first.json()
    assert response["filename"].endswith(f"evidence-{run_id[:8]}.json")
    assert response["media_type"] == "application/json"
    assert (
        response["content_digest"]
        == "sha256:" + hashlib.sha256(response["rendered_content"].encode()).hexdigest()
    )
    bundle = json.loads(response["rendered_content"])
    assert bundle["schema_version"] == "strategy_evidence_bundle_v1"
    assert bundle["run"]["run_id"] == run_id
    assert bundle["plan"]["strategy_scope"] == {
        "schema_version": "quant-strategy-scope-v1",
        "status": "supported",
        "reason": "The request fits the registered long-or-cash strategy templates.",
        "proxy_description": None,
        "excluded_behaviors": [],
    }
    assert bundle["selected_result"]["candidate_id"] == selected_id
    assert bundle["validation"]["generalization"]["selected_candidate_id"] == selected_id
    assert (
        bundle["validation"]["robustness_sensitivity"]["content"]["candidate"]["candidate_id"]
        == selected_id
    )
    assert len(bundle["candidate_curves"]) == len(bundle["candidates"])
    assert "benchmark_curve" not in response["rendered_content"]
    forbidden = {
        "learning_trace",
        "repair_memory",
        "iteration_feedback",
        "event_id",
        "trace_id",
        "prompt",
        "raw_bars",
    }

    def _scan(value: Any) -> bool:
        if isinstance(value, dict):
            return any(key in forbidden or _scan(item) for key, item in value.items())
        return isinstance(value, list) and any(_scan(item) for item in value)

    assert not _scan(bundle)
    alternate = next(
        item["candidate_id"] for item in bundle["candidates"] if item["candidate_id"] != selected_id
    )
    rejected = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={**payload, "candidate_id": alternate},
    )
    assert rejected.status_code == 409
    markdown = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "export_type": "strategy_report_markdown",
            "run_id": run_id,
            "candidate_id": alternate,
        },
    )
    assert markdown.status_code == 200, markdown.text
    assert markdown.json()["media_type"] == "text/markdown"


def test_strategy_report_preview_succeeds_without_idempotency_key(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run_id, selected_id = _completed_run(client, principal_id, market=False)
    response = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace_id,
        },
        json={
            "export_type": "strategy_evidence_bundle_json",
            "run_id": run_id,
            "candidate_id": selected_id,
        },
    )
    assert response.status_code == 200, response.text
    assert "X-Request-ID" in response.headers
    payload = response.json()
    assert payload["filename"].endswith(f"evidence-{run_id[:8]}.json")
    assert payload["media_type"] == "application/json"
    assert (
        payload["content_digest"]
        == "sha256:" + hashlib.sha256(payload["rendered_content"].encode()).hexdigest()
    )
    bundle = json.loads(payload["rendered_content"])
    assert bundle["schema_version"] == "strategy_evidence_bundle_v1"
    assert bundle["run"]["run_id"] == run_id
    assert bundle["selected_result"]["candidate_id"] == selected_id


def test_evidence_bundle_uses_updated_at_for_retained_retry_linkage(
    client: TestClient, principal_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id, run_id, selected_id = _completed_run(client, principal_id, market=False)
    headers = _headers(principal_id, workspace_id)
    store = QuantStore()
    source = store.get_run(workspace_id=workspace_id, run_id=run_id)
    # Retry creation mutates only this retained source metadata; the export must
    # describe the persisted update rather than infer a completion timestamp.
    source.retry_child_run_id = "retained-retry-child"
    source.updated_at = source.updated_at + timedelta(seconds=1)
    monkeypatch.setattr(evidence_export_module, "QuantStore", lambda: store)
    response = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={
            "export_type": "strategy_evidence_bundle_json",
            "run_id": run_id,
            "candidate_id": selected_id,
        },
    )
    assert response.status_code == 200, response.text
    run = json.loads(response.json()["rendered_content"])["run"]
    assert "completed_at" not in run
    assert run["updated_at"] == source.updated_at.isoformat()


def test_evidence_bundle_rejects_daily_dataset_runtime_drift(
    client: TestClient, principal_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id, run_id, selected_id = _completed_run(client, principal_id, market=False)
    payload = {
        "export_type": "strategy_evidence_bundle_json",
        "run_id": run_id,
        "candidate_id": selected_id,
    }
    baseline = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers=_headers(principal_id, workspace_id),
        json=payload,
    )
    assert baseline.status_code == 200, baseline.text
    store = QuantStore()
    report = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.kind.value == "research_report"
    )
    report.content["dataset"]["interval"] = "4h"
    report.digest = canonical_digest(report.content)
    monkeypatch.setattr(evidence_export_module, "QuantStore", lambda: store)
    response = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers=_headers(principal_id, workspace_id),
        json=payload,
    )
    assert response.status_code == 409


def test_evidence_bundle_rejects_plan_run_cross_check_drift(
    client: TestClient, principal_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id, run_id, selected_id = _completed_run(client, principal_id, market=False)
    payload = {
        "export_type": "strategy_evidence_bundle_json",
        "run_id": run_id,
        "candidate_id": selected_id,
    }
    baseline = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers=_headers(principal_id, workspace_id),
        json=payload,
    )
    assert baseline.status_code == 200, baseline.text
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=run_id)
    plan = next(
        artifact
        for artifact in store.artifacts_for_run(workspace_id=workspace_id, run_id=run_id)
        if artifact.id == run.plan_artifact_id
    )
    plan.content["objective_summary"] = "Mismatched retained plan summary."
    monkeypatch.setattr(evidence_export_module, "QuantStore", lambda: store)
    response = client.post(
        "/v1/quant/strategy-report-exports/preview",
        headers=_headers(principal_id, workspace_id),
        json=payload,
    )
    assert response.status_code == 409
