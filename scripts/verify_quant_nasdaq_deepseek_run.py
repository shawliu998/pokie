#!/usr/bin/env python3
"""Run one opt-in Nasdaq AAPL + DeepSeek Quant Agent verification."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.api.app.main import app
from services.api.app.modules.quant.store import QuantStore
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.provider import load_quant_agent_provider


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {principal_id}", "Idempotency-Key": str(uuid4())}
    if workspace_id:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _run() -> int:
    principal_id = str(uuid4())
    with TestClient(app) as client:
        workspace = client.post(
            "/v1/workspaces", headers=_headers(principal_id),
            json={"name": "Nasdaq DeepSeek Quant verification", "data_region": "local",
                  "retention_policy_version": "retention-v1"},
        )
        workspace.raise_for_status()
        workspace_id = workspace.json()["workspace_id"]
        dataset_response = client.post(
            "/v1/quant/datasets/fetch-nasdaq-equity",
            headers=_headers(principal_id, workspace_id),
            json={"symbol": "AAPL", "lookback_days": 730},
        )
        dataset_response.raise_for_status()
        dataset = dataset_response.json()
        project = client.post(
            "/v1/quant/projects", headers=_headers(principal_id, workspace_id),
            json={"name": "AAPL Nasdaq autonomous research",
                  "objective": "Evaluate bounded long-or-cash strategies on AAPL daily bars."},
        )
        project.raise_for_status()
        project_data = project.json()
        run_response = client.post(
            "/v1/quant/runs", headers=_headers(principal_id, workspace_id),
            json={
                "project_id": project_data["id"], "mode": "auto",
                "question": (
                    "Compare bounded long-or-cash strategies that seek lower drawdown on AAPL."
                ),
                "expected_project_row_version": project_data["row_version"],
                "dataset_id": dataset["dataset_id"],
            },
        )
        run_response.raise_for_status()
        run_id = run_response.json()["id"]
        provider = load_quant_agent_provider()
        for _ in range(24):
            run_quant_agent_once(provider=provider, workspace_id=workspace_id)
            current = QuantStore().get_run(workspace_id=workspace_id, run_id=run_id)
            if current.state.value in {"completed", "failed", "cancelled"}:
                break
        current = QuantStore().get_run(workspace_id=workspace_id, run_id=run_id)
        events = QuantStore().events_for_run(workspace_id=workspace_id, run_id=run_id)
        snapshot = client.get(
            "/v1/quant/workspace-snapshot", headers=_headers(principal_id, workspace_id)
        )
        snapshot.raise_for_status()

    source = dataset["source_metadata"]
    quality = dataset["data_quality"]
    actions = source.get("corporate_actions_attestation") or {}
    report = snapshot.json().get("report") or {}
    event_types = {event["event_type"] for event in events}
    provider_failure_count = sum(
        event["event_type"] == "agent.decision_failed" for event in events
    )
    generalization = report.get("generalization") or {}
    summary = {
        "state": current.state.value,
        "provider": current.provider,
        "model": current.model,
        "agent_iterations": current.agent_iteration,
        "bar_count": dataset.get("bar_count"),
        "provider_id": source.get("provider_id"),
        "attestation_kinds": [
            item.get("kind")
            for item in source.get("provider_response_attestations", [])
        ],
        "dividends_status": actions.get("dividends_status"),
        "splits_status": actions.get("splits_status"),
        "split_completeness_status": actions.get("split_completeness_status"),
        "split_snapshot_as_of_present": bool(actions.get("split_snapshot_as_of")),
        "split_coverage_start_present": "split_coverage_start" in actions,
        "split_coverage_end_present": bool(actions.get("split_coverage_end")),
        "split_history_complete": False,
        "split_evidence_scope": "current_snapshot_only_not_historical_complete",
        "price_adjustment": source.get("price_adjustment"),
        "price_adjustment_verification": source.get("price_adjustment_verification_status"),
        "market_calendar": source.get("market_calendar"),
        "time_zone": source.get("time_zone"),
        "quality_status": quality.get("status"),
        "unexplained_session_gaps": quality.get("calendar_gap_count"),
        "quality_verification": quality.get("verification_status"),
        "walk_forward_folds": (report.get("walkForward") or {}).get("foldCount"),
        "generalization_status": generalization.get("status"),
        "provider_failure_count": provider_failure_count,
        "provider_recovered": provider_failure_count == 1
        and current.state.value == "completed",
        "provider_fallback": "agent.provider_fallback" in event_types,
    }
    print(summary)
    return int(not (
        current.state.value == "completed" and current.provider == "deepseek"
        and summary["provider_failure_count"] == 0
        and not summary["provider_fallback"]
        and summary["provider_id"] == "nasdaq_equity"
        and summary["attestation_kinds"] == [
            "daily_bars", "instrument_info", "dividends", "splits"
        ]
        and summary["dividends_status"] == "retrieved_unverified"
        and summary["splits_status"] == "retrieved_unverified"
        and summary["split_completeness_status"] == "current_snapshot_only"
        and summary["split_snapshot_as_of_present"]
        and summary["split_coverage_start_present"]
        and summary["split_coverage_end_present"]
        and summary["price_adjustment"] == "unadjusted"
        and summary["price_adjustment_verification"] == "not_applicable"
        and summary["market_calendar"] == "XNAS"
        and summary["time_zone"] == "America/New_York"
        and summary["quality_status"] in {"passed", "warning"}
        and summary["quality_verification"] == "checked"
        and int(summary["bar_count"] or 0) >= 252
        and summary["walk_forward_folds"] == 3
        and summary["generalization_status"] in {"pass", "fail", "inconclusive"}
    ))


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("SKIP: DEEPSEEK_API_KEY is not configured.")
        return 2
    os.environ["POKIEQUANT_AGENT_PROVIDER"] = "deepseek"
    os.environ["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] = "false"
    try:
        return _run()
    except Exception:
        print("FAIL: Nasdaq/DeepSeek Quant verification did not complete safely.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
