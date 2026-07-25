from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from qurio.client import QurioApiError, QurioClient
from qurio.config import QurioConfigurationError, QurioConnection


def connection() -> QurioConnection:
    return QurioConnection(
        api_url="http://127.0.0.1:8135/",
        workspace_id="00000000-0000-4000-8000-000000000001",
        access_token="secret-token",
    )


def run_payload() -> dict[str, Any]:
    return {
        "id": "00000000-0000-4000-8000-000000000010",
        "workspace_id": "00000000-0000-4000-8000-000000000001",
        "row_version": 1,
        "created_at": "2026-07-25T00:00:00Z",
        "updated_at": "2026-07-25T00:00:00Z",
        "project_id": "00000000-0000-4000-8000-000000000002",
        "dataset_id": "dataset-v2",
        "dataset_digest": "sha256:dataset",
        "research_start": "2025-01-01",
        "research_end": "2025-12-31",
        "state": "draft",
        "mode": "plan",
        "question": "Compare retained strategies.",
        "plan_revision": 0,
        "attempt_number": 1,
        "retry_of_run_id": None,
        "parent_run_id": None,
        "seed_candidate_id": None,
        "refinement_reason": None,
        "latest_sequence": 0,
        "trace_id": "trace-1",
        "failure_reason": None,
        "agent_iteration": 0,
        "agent_status": "idle",
        "max_agent_iterations": 12,
        "max_experiments": 3,
        "max_repairs": 2,
        "used_experiments": 0,
        "used_repairs": 0,
        "last_action": None,
        "last_observation": None,
        "final_conclusion": None,
        "provider": "mock",
        "model": None,
        "data_authenticity": "seed",
    }


def test_connection_requires_http_workspace_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("QURIO_API_URL", "http://127.0.0.1:8135")
    monkeypatch.setenv("QURIO_WORKSPACE_ID", "workspace-1")
    monkeypatch.delenv("QURIO_ACCESS_TOKEN", raising=False)
    with pytest.raises(QurioConfigurationError, match="QURIO_ACCESS_TOKEN"):
        QurioConnection.from_env()
    with pytest.raises(QurioConfigurationError, match=r"HTTP\(S\)"):
        QurioConnection(
            api_url="file:///tmp/qurio",
            workspace_id="workspace-1",
            access_token="token",
        )


def test_typed_run_methods_send_scoped_headers_without_exposing_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1/quant/runs":
            return httpx.Response(200, json=[run_payload()])
        return httpx.Response(200, json=run_payload())

    with QurioClient(connection(), transport=httpx.MockTransport(handler)) as client:
        runs = client.list_runs(limit=10)
        run = client.get_run(runs[0].id)

    assert run.question == "Compare retained strategies."
    assert requests[0].url.params["limit"] == "10"
    assert requests[0].headers["x-workspace-id"] == connection().workspace_id
    assert requests[0].headers["authorization"] == "Bearer secret-token"
    assert "secret-token" not in repr(runs)


def test_snapshot_and_empty_dataset_directory_keep_json_contracts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/quant/datasets/v2":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"runs": [], "data_authenticity": "seed"})

    with QurioClient(connection(), transport=httpx.MockTransport(handler)) as client:
        assert client.list_datasets() == []
        assert client.get_workspace_snapshot()["runs"] == []
        assert client.get_run_snapshot("run-1")["data_authenticity"] == "seed"


def test_api_error_preserves_safe_code_and_never_includes_token() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": "QUANT_RUN_NOT_FOUND", "message": "Run not found."}},
        )

    with (
        QurioClient(connection(), transport=httpx.MockTransport(handler)) as client,
        pytest.raises(QurioApiError) as captured,
    ):
        client.get_run("missing")

    assert captured.value.status_code == 404
    assert captured.value.code == "QUANT_RUN_NOT_FOUND"
    assert str(captured.value) == "QUANT_RUN_NOT_FOUND: Run not found."
    assert "secret-token" not in str(captured.value)


def test_run_limit_is_checked_before_http() -> None:
    with (
        QurioClient(
            connection(),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(500, json={"unexpected": True})
            ),
        ) as client,
        pytest.raises(ValueError, match="between 1 and 100"),
    ):
        client.list_runs(limit=101)


def test_json_payload_remains_serializable() -> None:
    payload = run_payload()
    assert json.loads(json.dumps(payload))["dataset_id"] == "dataset-v2"
