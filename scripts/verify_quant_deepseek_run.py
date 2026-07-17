#!/usr/bin/env python3
"""Run one secret-gated DeepSeek Quant Agent over an imported local CSV fixture."""

from __future__ import annotations

import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.api.app.main import app
from services.api.app.modules.quant.store import QuantStore
from services.worker.app.pipelines.quant_agent import run_quant_agent_once
from services.worker.app.quant_agent.provider import load_quant_agent_provider


def _csv() -> str:
    rows = ["date,open,high,low,close,volume"]
    start = date(2022, 1, 3)
    for index in range(420):
        trading_date = start + timedelta(days=index)
        baseline = 100 + index * 0.08
        opening = baseline + 4 * math.sin((index - 1) / 13)
        closing = baseline + 4 * math.sin(index / 13)
        rows.append(
            f"{trading_date.isoformat()},{opening:.4f},"
            f"{max(opening, closing) + 1:.4f},{min(opening, closing) - 1:.4f},"
            f"{closing:.4f},{100000 + index}"
        )
    return "\n".join(rows)


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def main() -> int:
    if not (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("POKIEQUANT_AGENT_API_KEY")):
        raise SystemExit("DeepSeek credential is not configured.")
    os.environ["POKIEQUANT_AGENT_PROVIDER"] = "deepseek"
    os.environ["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] = "false"
    os.environ.setdefault("POKIEQUANT_AGENT_MODEL", "deepseek-v4-flash")

    principal_id = str(uuid4())
    with TestClient(app) as client:
        workspace_response = client.post(
            "/v1/workspaces",
            headers=_headers(principal_id),
            json={
                "name": "DeepSeek Quant verification",
                "data_region": "local",
                "retention_policy_version": "retention-v1",
            },
        )
        workspace_response.raise_for_status()
        workspace_id = workspace_response.json()["workspace_id"]
        csv_text = _csv()
        dataset_response = client.post(
            "/v1/quant/datasets/import-csv",
            headers=_headers(principal_id, workspace_id),
            json={
                "name": "DeepSeek imported daily fixture",
                "symbol": "DSQ",
                "csv_text": csv_text,
                "file_name": "deepseek-quant-verification.csv",
                "source_name": "Deterministic local verification generator",
                "source_reference": "script:verify_quant_deepseek_run.py",
                "price_adjustment": "unadjusted",
            },
        )
        dataset_response.raise_for_status()
        dataset = dataset_response.json()
        project_response = client.post(
            "/v1/quant/projects",
            headers=_headers(principal_id, workspace_id),
            json={
                "name": "DeepSeek autonomous imported-data research",
                "objective": "Reduce drawdown while retaining positive returns.",
            },
        )
        project_response.raise_for_status()
        project = project_response.json()
        run_response = client.post(
            "/v1/quant/runs",
            headers=_headers(principal_id, workspace_id),
            json={
                "project_id": project["id"],
                "mode": "auto",
                "question": (
                    "Research simple long-or-cash strategies that reduce maximum drawdown "
                    "while retaining positive returns on this pinned imported dataset."
                ),
                "expected_project_row_version": project["row_version"],
                "dataset_id": dataset["dataset_id"],
            },
        )
        run_response.raise_for_status()
        run_id = run_response.json()["id"]
        provider = load_quant_agent_provider()
        for _ in range(16):
            run_quant_agent_once(provider=provider, workspace_id=workspace_id)
            current = QuantStore().get_run(workspace_id=workspace_id, run_id=run_id)
            if current.state.value in {"completed", "failed", "cancelled"}:
                break

        current = QuantStore().get_run(workspace_id=workspace_id, run_id=run_id)
        events = QuantStore().events_for_run(workspace_id=workspace_id, run_id=run_id)
        snapshot_response = client.get(
            "/v1/quant/workspace-snapshot",
            headers=_headers(principal_id, workspace_id),
        )
        snapshot_response.raise_for_status()
        snapshot = snapshot_response.json()
        event_types = {event["event_type"] for event in events}
        report = snapshot.get("report") or {}
        walk_forward = report.get("walkForward") or {}
        generalization = report.get("generalization") or {}
        summary = {
            "run_id": run_id,
            "state": current.state.value,
            "provider": current.provider,
            "model": current.model,
            "agent_iterations": current.agent_iteration,
            "candidate_count": len(snapshot.get("candidates", [])),
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["digest"],
            "source_name": dataset["source_metadata"]["source_name"],
            "walk_forward_rule": walk_forward.get("ruleVersion"),
            "walk_forward_folds": walk_forward.get("foldCount"),
            "generalization_status": generalization.get("status"),
            "provider_fallback": "agent.provider_fallback" in event_types,
            "provider_failure": "agent.decision_failed" in event_types,
        }
        print(summary)
        if (
            current.state.value != "completed"
            or current.provider != "deepseek"
            or summary["provider_fallback"]
            or summary["provider_failure"]
            or summary["walk_forward_folds"] != 3
            or not summary["generalization_status"]
        ):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
