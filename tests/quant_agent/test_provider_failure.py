from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from packages.contracts.quant import QuantAgentDecision, QuantAgentPlan
from packages.contracts.quant.enums import QuantRunState
from services.api.app.modules.quant.store import QuantStore
from services.worker.app.quant_agent.provider import (
    QuantAgentProviderError,
)
from services.worker.app.quant_agent.runner import QuantAgentRunner

_PROVIDER_ENV_KEYS = (
    "POKIEQUANT_AGENT_PROVIDER",
    "DEEPSEEK_API_KEY",
    "POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK",
)


@pytest.fixture(autouse=True)
def _reset_provider_env() -> None:
    for key in _PROVIDER_ENV_KEYS:
        os.environ.pop(key, None)
    yield
    for key in _PROVIDER_ENV_KEYS:
        os.environ.pop(key, None)


class _FailingProvider:
    provider_name = "failing"
    model_name = "failing-model"

    def __init__(self, error: Exception = QuantAgentProviderError("boom")) -> None:
        self._error = error

    def plan(self, research_goal: str) -> QuantAgentPlan:
        raise self._error

    def decide(self, context: Any) -> QuantAgentDecision:
        raise self._error


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
            "name": f"Provider failure {uuid4().hex[:8]}",
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert workspace_response.status_code == 201
    workspace_id = workspace_response.json()["workspace_id"]
    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "Failure test", "objective": goal},
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
    # Force the run onto the configured (failing) provider without requiring
    # network access during plan generation.
    store = QuantStore()
    run = store.get_run(workspace_id=workspace_id, run_id=run_response.json()["id"])
    run.provider = "deepseek"
    run.model = "failing-model"
    store._persist_workspace(workspace_id)
    return workspace_id, run_response.json()


def test_first_provider_failure_records_decision_failed_and_allows_retry(
    client: TestClient, principal_id: str
) -> None:
    workspace_id, run = _create_auto_run(client, principal_id, "Test failure recovery.")
    store = QuantStore()
    lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="test")
    assert lease is not None
    runner = QuantAgentRunner(store=store, provider=_FailingProvider())
    result = runner.run_step(claim=lease)
    assert result.did_work
    assert not result.terminal
    refreshed = store.get_run(workspace_id=workspace_id, run_id=run["id"])
    assert refreshed.state is QuantRunState.RUNNING_EXPERIMENTS
    assert refreshed.consecutive_provider_failures == 1
    events = store.events_for_run(workspace_id=workspace_id, run_id=run["id"])
    assert any(
        item["event_type"] == "agent.decision_failed" for item in events
    )


def test_second_provider_failure_switches_to_mock_when_fallback_enabled(
    client: TestClient, principal_id: str
) -> None:
    os.environ["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] = "true"
    workspace_id, run = _create_auto_run(client, principal_id, "Test mock fallback.")
    store = QuantStore()
    provider = _FailingProvider()

    for _ in range(2):
        lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="test")
        assert lease is not None
        QuantAgentRunner(store=store, provider=provider).run_step(claim=lease)

    refreshed = store.get_run(workspace_id=workspace_id, run_id=run["id"])
    assert refreshed.provider == "mock"
    events = store.events_for_run(workspace_id=workspace_id, run_id=run["id"])
    assert any(item["event_type"] == "agent.provider_fallback" for item in events)
    del os.environ["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"]


def test_second_provider_failure_fails_run_when_fallback_disabled(
    client: TestClient, principal_id: str
) -> None:
    os.environ["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"] = "false"
    workspace_id, run = _create_auto_run(client, principal_id, "Test no fallback.")
    store = QuantStore()
    provider = _FailingProvider()

    for _ in range(2):
        lease = store.claim_agent_run(workspace_id=workspace_id, worker_id="test")
        assert lease is not None
        QuantAgentRunner(store=store, provider=provider).run_step(claim=lease)

    refreshed = store.get_run(workspace_id=workspace_id, run_id=run["id"])
    assert refreshed.state is QuantRunState.FAILED
    assert refreshed.failure_reason is not None
    del os.environ["POKIEQUANT_AGENT_ALLOW_MOCK_FALLBACK"]
