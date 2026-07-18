#!/usr/bin/env python3
"""Phase 1C real E2E verification: Binance Spot BTCUSDT -> DeepSeek auto run."""

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

    principal_id = str(uuid4())
    with TestClient(app) as client:
        workspace_response = client.post(
            "/v1/workspaces",
            headers=_headers(principal_id),
            json={
                "name": "Binance DeepSeek E2E verification",
                "data_region": "local",
                "retention_policy_version": "retention-v1",
            },
        )
        workspace_response.raise_for_status()
        workspace_id = workspace_response.json()["workspace_id"]

        dataset_response = client.post(
            "/v1/quant/datasets/fetch-binance-spot",
            headers=_headers(principal_id, workspace_id),
            json={"symbol": "BTCUSDT", "limit": 365},
        )
        dataset_response.raise_for_status()
        dataset = dataset_response.json()

        project_response = client.post(
            "/v1/quant/projects",
            headers=_headers(principal_id, workspace_id),
            json={
                "name": "Binance BTCUSDT DeepSeek autonomous research",
                "objective": (
                    "Reduce drawdown while retaining positive returns on BTCUSDT spot daily bars."
                ),
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
                    "while retaining positive returns on this Binance BTCUSDT spot dataset."
                ),
                "expected_project_row_version": project["row_version"],
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
        snapshot_response = client.get(
            "/v1/quant/workspace-snapshot",
            headers=_headers(principal_id, workspace_id),
        )
        snapshot_response.raise_for_status()
        snapshot = snapshot_response.json()

        event_types = {event["event_type"] for event in events}
        provider_failure_count = sum(
            event["event_type"] == "agent.decision_failed" for event in events
        )
        report = snapshot.get("report") or {}
        walk_forward = report.get("walkForward") or {}
        generalization = report.get("generalization") or {}
        quality = dataset["data_quality"]
        source_metadata = dataset["source_metadata"]
        provider_response_digest = source_metadata.get("provider_response_digest")

        summary = {
            "run_id": run_id,
            "state": current.state.value,
            "provider": current.provider,
            "model": current.model,
            "agent_iterations": current.agent_iteration,
            "candidate_count": len(snapshot.get("candidates", [])),
            "dataset_id": dataset["dataset_id"],
            "dataset_digest": dataset["digest"],
            "provider_response_digest": provider_response_digest,
            "source_kind": source_metadata.get("kind"),
            "provider_id": source_metadata.get("provider_id"),
            "attestation_status": source_metadata.get("attestation_status"),
            "bar_count": dataset["bar_count"],
            "quality_status": quality.get("status"),
            "quality_verification": quality.get("verification_status"),
            "walk_forward_folds": walk_forward.get("foldCount"),
            "walk_forward_status": walk_forward.get("status"),
            "generalization_status": generalization.get("status"),
            "provider_fallback": "agent.provider_fallback" in event_types,
            "provider_failure_count": provider_failure_count,
        }
        print(summary)

        if (
            current.state.value != "completed"
            or current.provider != "deepseek"
            or summary["provider_fallback"]
            or summary["provider_failure_count"]
            or summary["source_kind"] != "provider_fetch"
            or summary["provider_id"] != "binance_spot"
            or summary["attestation_status"] != "provider_retrieved"
            or not provider_response_digest
            or provider_response_digest == dataset["digest"]
            or summary["bar_count"] < 252
            or summary["quality_status"] != "passed"
            or summary["quality_verification"] != "checked"
            or summary["walk_forward_folds"] != 3
            or not summary["generalization_status"]
        ):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
