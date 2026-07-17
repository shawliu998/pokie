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
            "name": f"Comparison {uuid4().hex[:8]}",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert workspace_response.status_code == 201
    workspace_id = workspace_response.json()["workspace_id"]
    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Comparison test", "objective": goal},
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


def test_comparison_includes_difference_fields(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run = _create_auto_run(
        client, principal_id, "Reduce maximum drawdown compared with buy and hold."
    )
    for _ in range(25):
        if not run_quant_agent_once(workspace_id=workspace_id):
            break
        store = QuantStore()
        current = store.get_run(workspace_id=workspace_id, run_id=run["id"])
        if current.state.value in {"completed", "failed", "cancelled"}:
            break

    store = QuantStore()
    artifacts = store.artifacts_for_run(workspace_id=workspace_id, run_id=run["id"])
    comparison_artifacts = [
        item for item in artifacts if item.kind.value == "validation_report"
    ]
    assert comparison_artifacts, "Expected a comparison artifact"
    comparison = comparison_artifacts[-1].content
    assert comparison["evaluation_partition"] == "train"
    assert comparison["split"]["rule_version"] == "chronological-80-20-v1"
    assert "holdout" not in comparison
    assert "benchmark" in comparison
    assert "candidates" in comparison
    for candidate in comparison["candidates"]:
        assert "drawdown_improvement_pct" in candidate
        assert "return_difference" in candidate
        assert "drawdown_difference" in candidate
        assert "sharpe_difference" in candidate
        assert "trade_count_difference" in candidate
        benchmark = comparison["benchmark"]
        assert candidate["return_difference"] == round(
            candidate["total_return_pct"] - benchmark["total_return_pct"], 4
        )
        walk_forward = candidate["walk_forward"]
        assert walk_forward["evaluation_partition"] == "train"
        assert walk_forward["rule_version"] == "expanding-3fold-20pct-regime-v1"
        assert walk_forward["fold_count"] == 3
        assert walk_forward["state_rule_version"] == "trailing-60bar-trend-vol-v1"
        assert walk_forward["state_lookback_bars"] == 60
        assert len(walk_forward["folds"]) == 3
        assert walk_forward["aggregate"]["evaluated_folds"] == 3
        assert all("holdout" not in fold for fold in walk_forward["folds"])
        assert all(
            fold["market_regime"]["history_end"] < fold["evaluation_start"]
            and fold["market_regime"]["history_bar_count"] <= 60
            for fold in walk_forward["folds"]
        )
        by_regime = walk_forward["aggregate"]["by_market_regime"]
        assert [item["label"] for item in by_regime] == sorted(
            item["label"] for item in by_regime
        )
        assert sum(item["fold_count"] for item in by_regime) == 3
        assert walk_forward["aggregate"]["distinct_market_regimes"] == len(by_regime)

    research_report = next(
        item for item in artifacts if item.kind.value == "research_report"
    ).content
    generalization = research_report["generalization"]
    assert generalization["split"] == comparison["split"]
    assert generalization["status"] in {"pass", "fail", "inconclusive"}
    assert generalization["train"]["benchmark"] == comparison["benchmark"]
    assert generalization["holdout"]["candidate"]
    assert generalization["holdout"]["benchmark"]
    selected_walk_forward = next(
        item["walk_forward"]
        for item in comparison["candidates"]
        if item["candidate_id"] == research_report["selected_candidate_id"]
    )
    assert research_report["walk_forward"] == selected_walk_forward
