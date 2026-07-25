from __future__ import annotations

from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient

from packages.contracts.quant import QuantRunState
from services.api.app.modules.quant.store import QuantStore


def headers(principal_id: str, workspace_id: str, **extra: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {principal_id}",
        "X-Workspace-ID": workspace_id,
        **extra,
    }


def command_headers(principal_id: str, workspace_id: str) -> dict[str, str]:
    return headers(
        principal_id,
        workspace_id,
        **{"Idempotency-Key": str(uuid4())},
    )


def completed_research(
    client: TestClient, principal_id: str
) -> tuple[str, dict[str, Any], str]:
    workspace_response = client.post(
        "/v1/workspaces",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "Idempotency-Key": str(uuid4()),
        },
        json={
            "name": "Paper boundary",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert workspace_response.status_code == 201, workspace_response.text
    workspace_id = workspace_response.json()["workspace_id"]
    project_response = client.post(
        "/v1/quant/projects",
        headers=command_headers(principal_id, workspace_id),
        json={"name": "Paper source", "objective": "Retain a candidate for simulation."},
    )
    assert project_response.status_code == 201, project_response.text
    project = project_response.json()
    run_response = client.post(
        "/v1/quant/runs",
        headers=command_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "question": "Which retained candidate may enter paper simulation?",
            "mode": "plan",
            "expected_project_row_version": project["row_version"],
        },
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()
    approve = client.post(
        f"/v1/quant/runs/{run['id']}/approve-plan",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_row_version": run["row_version"],
            "plan_revision": run["plan_revision"],
            "reason": "Approve deterministic paper-boundary fixture.",
        },
    )
    assert approve.status_code == 200, approve.text
    store = QuantStore()
    recorded = store.get_run(workspace_id=workspace_id, run_id=run["id"])
    recorded.state = QuantRunState.RUNNING_EXPERIMENTS
    recorded.max_experiments = 2
    lease = store.claim_agent_run(
        workspace_id=workspace_id,
        worker_id="paper-boundary-test",
    )
    assert lease is not None
    candidates = []
    for name, parameters in (
        ("SMA 20/100", {"fast_window": 20, "slow_window": 100}),
        ("SMA 50/200", {"fast_window": 50, "slow_window": 200}),
    ):
        candidate, _, error = store.create_agent_candidate(
            lease,
            name=name,
            template="sma_crossover",
            hypothesis="Retain a deterministic candidate for paper simulation.",
            parameters=cast(dict[str, int | float], parameters),
        )
        assert error is None and candidate is not None
        candidates.append(candidate)
        recorded.state = QuantRunState.RUNNING_EXPERIMENTS
        assert store.run_agent_backtest(lease, candidate_id=candidate.id)[2] is None
    candidate = candidates[0]
    comparison, _, error = store.compare_agent_candidates(lease)
    assert error is None and comparison is not None
    report, _, error = store.finish_agent_research(
        lease,
        selected_candidate_id=candidate.id,
        conclusion="Retain this candidate for isolated paper simulation.",
        next_step="stop",
    )
    assert error is None and report is not None
    snapshot = client.get(
        f"/v1/quant/runs/{run['id']}/workspace-snapshot",
        headers=headers(principal_id, workspace_id),
    )
    assert snapshot.status_code == 200, snapshot.text
    payload = snapshot.json()
    report = payload["report"]
    selected_candidate_id = (
        report.get("selectedCandidateId")
        or (report.get("selectionDecision") or {}).get("selectedCandidateId")
        or (report.get("generalization") or {}).get("selectedCandidateId")
    )
    assert isinstance(selected_candidate_id, str)
    assert any(
        item["id"] == selected_candidate_id for item in payload["candidates"]
    )
    return workspace_id, run, selected_candidate_id


def test_local_paper_order_fill_position_and_reconcile(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run, candidate_id = completed_research(client, principal_id)
    initial = client.get(
        "/v1/paper/snapshot",
        headers=headers(principal_id, workspace_id),
    )
    assert initial.status_code == 200, initial.text
    assert initial.json()["environment"] == "paper"
    assert initial.json()["account"]["broker"] == "local_simulator"
    assert initial.json()["account"]["cash"] == "100000.00"
    assert initial.json()["positions"] == []

    draft = client.post(
        "/v1/paper/orders/drafts",
        headers=command_headers(principal_id, workspace_id),
        json={
            "source_run_id": run["id"],
            "source_candidate_id": candidate_id,
            "side": "buy",
            "quantity": "10",
            "order_type": "market",
            "time_in_force": "day",
            "expected_account_row_version": 1,
        },
    )
    assert draft.status_code == 201, draft.text
    order = draft.json()
    assert order["state"] == "draft"
    assert order["environment"] == "paper"
    assert order["source_evidence_digest"].startswith("sha256:")

    submit = client.post(
        f"/v1/paper/orders/{order['order_id']}/submit",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_order_row_version": order["row_version"],
            "expected_account_row_version": 1,
        },
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["state"] == "filled"
    assert submit.json()["filled_quantity"] == "10.00000000"

    snapshot = client.get(
        "/v1/paper/snapshot",
        headers=headers(principal_id, workspace_id),
    )
    assert snapshot.status_code == 200, snapshot.text
    payload = snapshot.json()
    assert Decimal(payload["account"]["cash"]) < Decimal("100000.00")
    assert payload["account"]["row_version"] == 2
    assert payload["positions"][0]["symbol"] == "SPY"
    assert payload["positions"][0]["quantity"] == "10.00000000"
    assert len(payload["fills"]) == 1

    reconcile = client.post(
        "/v1/paper/reconcile",
        headers=command_headers(principal_id, workspace_id),
        json={"expected_account_row_version": 2},
    )
    assert reconcile.status_code == 200, reconcile.text
    assert reconcile.json()["account"]["row_version"] == 3
    assert reconcile.json()["account"]["last_reconciled_at"] is not None


def test_paper_draft_rejects_candidate_not_retained_by_final_report(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run, _candidate_id = completed_research(client, principal_id)
    research = client.get(
        f"/v1/quant/runs/{run['id']}/workspace-snapshot",
        headers=headers(principal_id, workspace_id),
    )
    assert research.status_code == 200, research.text
    non_selected_candidate_id = next(
        item["id"]
        for item in research.json()["candidates"]
        if item["id"] != _candidate_id
    )
    response = client.post(
        "/v1/paper/orders/drafts",
        headers=command_headers(principal_id, workspace_id),
        json={
            "source_run_id": run["id"],
            "source_candidate_id": non_selected_candidate_id,
            "side": "buy",
            "quantity": "1",
            "order_type": "market",
            "time_in_force": "day",
            "expected_account_row_version": 1,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE"


def test_paper_order_requires_idempotency_and_matching_versions(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run, candidate_id = completed_research(client, principal_id)
    body = {
        "source_run_id": run["id"],
        "source_candidate_id": candidate_id,
        "side": "buy",
        "quantity": "1",
        "order_type": "market",
        "time_in_force": "day",
        "expected_account_row_version": 1,
    }
    missing = client.post(
        "/v1/paper/orders/drafts",
        headers=headers(principal_id, workspace_id),
        json=body,
    )
    assert missing.status_code == 422
    unsupported_limit = client.post(
        "/v1/paper/orders/drafts",
        headers=command_headers(principal_id, workspace_id),
        json={**body, "order_type": "limit", "limit_price": "100"},
    )
    assert unsupported_limit.status_code == 422
    draft = client.post(
        "/v1/paper/orders/drafts",
        headers=command_headers(principal_id, workspace_id),
        json=body,
    )
    assert draft.status_code == 201, draft.text
    stale = client.post(
        f"/v1/paper/orders/{draft.json()['order_id']}/submit",
        headers=command_headers(principal_id, workspace_id),
        json={"expected_order_row_version": 2, "expected_account_row_version": 1},
    )
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
