from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from services.api.app.core.errors import ApiError
from services.api.app.db.models import AuditLog, SourceConnection, SourceValidationJobRecord
from services.api.app.db.session import get_session_factory
from services.api.app.modules.sources.validation import SourceValidationJobRepository
from tests.conftest import command_headers, query_headers
from tests.security.helpers import create_project, create_workspace


def _cloud_source(client: TestClient, principal_id: str, workspace_id: str) -> dict[str, object]:
    response = client.post(
        "/v1/sources",
        headers=command_headers(principal_id, workspace_id),
        json={
            "name": "Durable GitHub validation",
            "source_kind": "cloud",
            "runtime": "cloud",
            "connector_type": "github",
            "connector_version": "github-v1",
            "data_scope": "workspace_confidential",
            "credential_ref": "vault://github/durable-validation",
            "cadence": "daily",
            "timezone": "UTC",
            "source_config": {
                "connector_type": "github",
                "repositories": [{"owner": "openai", "repository": "glint"}],
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_health_check_is_durable_pollable_and_fenced(client: TestClient, principal_id: str) -> None:
    workspace = create_workspace(client, principal_id, "Source validation workspace")
    source = _cloud_source(client, principal_id, workspace["id"])
    headers = command_headers(principal_id, workspace["id"])
    response = client.post(
        f"/v1/sources/{source['id']}/health-check",
        headers=headers,
        json={"expected_row_version": source["row_version"], "reason": "Explicit check"},
    )
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["state"] == "queued"
    assert job["command"] == "health_check"
    assert job["attempt"] == 0

    replay = client.post(
        f"/v1/sources/{source['id']}/health-check",
        headers=headers,
        json={"expected_row_version": source["row_version"], "reason": "Explicit check"},
    )
    assert replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["id"] == job["id"]

    current = client.get(
        f"/v1/sources/{source['id']}", headers=query_headers(principal_id, workspace["id"])
    ).json()
    assert current["status"] == "validating"
    source_row_version = source["row_version"]
    assert isinstance(source_row_version, int)
    assert current["row_version"] == source_row_version + 1

    with get_session_factory()() as db:
        assert (
            SourceValidationJobRepository.claim(
                db,
                workspace_id=str(uuid4()),
                job_id=job["id"],
                owner_token="worker-lease-token",
            )
            is None
        )
        claimed = SourceValidationJobRepository.claim(
            db,
            workspace_id=workspace["id"],
            job_id=job["id"],
            owner_token="worker-lease-token",
            lease_seconds=120,
        )
        assert claimed is not None
        assert claimed.attempt == 1
        assert claimed.fencing_version == 1
        assert claimed.lease_owner_token != "worker-lease-token"
        SourceValidationJobRepository.heartbeat(
            db,
            workspace_id=workspace["id"],
            job_id=job["id"],
            owner_token="worker-lease-token",
            expected_attempt=1,
            expected_fencing_version=1,
        )
        completed = SourceValidationJobRepository.complete(
            db,
            workspace_id=workspace["id"],
            job_id=job["id"],
            owner_token="worker-lease-token",
            expected_attempt=1,
            expected_fencing_version=1,
            source_status="healthy",
        )
        assert completed.state == "completed"

    polled = client.get(
        f"/v1/source-validation-jobs/{job['id']}",
        headers=query_headers(principal_id, workspace["id"]),
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["result_source_status"] == "healthy"
    assert "lease_owner_token" not in polled.text
    healthy = client.get(
        f"/v1/sources/{source['id']}", headers=query_headers(principal_id, workspace["id"])
    ).json()
    assert healthy["status"] == "healthy"
    assert healthy["health"]["state"] == "healthy"
    assert healthy["health"]["checked_at"] is not None


@pytest.mark.parametrize("job_state", ["queued", "claimed"])
@pytest.mark.parametrize("lifecycle_command", ["patch", "activate", "disable", "remove"])
def test_source_lifecycle_rejects_active_validation_without_mutation(
    client: TestClient,
    principal_id: str,
    lifecycle_command: str,
    job_state: str,
) -> None:
    workspace = create_workspace(
        client,
        principal_id,
        f"{lifecycle_command} against {job_state} validation",
    )
    source = _cloud_source(client, principal_id, workspace["id"])
    queued_response = client.post(
        f"/v1/sources/{source['id']}/health-check",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": source["row_version"], "reason": "Hold lifecycle"},
    )
    assert queued_response.status_code == 202, queued_response.text
    job = queued_response.json()
    if job_state == "claimed":
        with get_session_factory()() as db:
            claimed = SourceValidationJobRepository.claim(
                db,
                workspace_id=workspace["id"],
                job_id=job["id"],
                owner_token=f"{lifecycle_command}-worker",
            )
            assert claimed is not None

    before = client.get(
        f"/v1/sources/{source['id']}",
        headers=query_headers(principal_id, workspace["id"]),
    ).json()
    headers = command_headers(principal_id, workspace["id"])
    if lifecycle_command == "patch":
        response = client.patch(
            f"/v1/sources/{source['id']}",
            headers=headers,
            json={
                "name": "Forbidden concurrent mutation",
                # Deliberately stale: active validation rejection wins before
                # version interpretation while the source row is locked.
                "expected_row_version": source["row_version"],
            },
        )
    else:
        response = client.post(
            f"/v1/sources/{source['id']}/{lifecycle_command}",
            headers=headers,
            json={
                "expected_row_version": source["row_version"],
                "reason": "Forbidden concurrent lifecycle command",
            },
        )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "SOURCE_VALIDATION_IN_PROGRESS"

    after = client.get(
        f"/v1/sources/{source['id']}",
        headers=query_headers(principal_id, workspace["id"]),
    ).json()
    assert after == before
    with get_session_factory()() as db:
        persisted_job = db.get(SourceValidationJobRecord, job["id"])
        assert persisted_job is not None
        assert persisted_job.state == job_state


@pytest.mark.parametrize("worker_outcome", ["complete", "fail"])
def test_source_fence_drift_terminalizes_job_and_allows_reenqueue(
    client: TestClient,
    principal_id: str,
    worker_outcome: str,
) -> None:
    workspace = create_workspace(client, principal_id, f"Fence drift {worker_outcome}")
    source = _cloud_source(client, principal_id, workspace["id"])
    queued_response = client.post(
        f"/v1/sources/{source['id']}/health-check",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": source["row_version"], "reason": "Fence drift"},
    )
    assert queued_response.status_code == 202, queued_response.text
    job = queued_response.json()
    owner_token = f"fence-drift-{worker_outcome}"

    with get_session_factory()() as db:
        claimed = SourceValidationJobRepository.claim(
            db,
            workspace_id=workspace["id"],
            job_id=job["id"],
            owner_token=owner_token,
        )
        assert claimed is not None
        drifted_source = db.get(SourceConnection, source["id"])
        assert drifted_source is not None
        drifted_source.status = "disabled"
        drifted_source.health_state = "disabled"
        drifted_source.row_version += 1
        db.commit()
        drifted_version = drifted_source.row_version

        if worker_outcome == "complete":
            terminal = SourceValidationJobRepository.complete(
                db,
                workspace_id=workspace["id"],
                job_id=job["id"],
                owner_token=owner_token,
                expected_attempt=claimed.attempt,
                expected_fencing_version=claimed.fencing_version,
                source_status="healthy",
            )
        else:
            terminal = SourceValidationJobRepository.fail(
                db,
                workspace_id=workspace["id"],
                job_id=job["id"],
                owner_token=owner_token,
                expected_attempt=claimed.attempt,
                expected_fencing_version=claimed.fencing_version,
                failure_code="WORKER_FAILURE",
                reason="Worker failure after source drift",
            )
        assert terminal.state == "failed"
        assert terminal.result_source_status == "failed"
        assert terminal.failure_code == "SOURCE_VALIDATION_FENCE_DRIFT"
        assert terminal.lease_owner_token is None
        assert terminal.lease_expires_at is None
        assert terminal.heartbeat_at is None

        unchanged_source = db.get(SourceConnection, source["id"])
        assert unchanged_source is not None
        assert unchanged_source.status == "disabled"
        assert unchanged_source.health_state == "disabled"
        assert unchanged_source.row_version == drifted_version

    polled = client.get(
        f"/v1/source-validation-jobs/{job['id']}",
        headers=query_headers(principal_id, workspace["id"]),
    )
    assert polled.status_code == 200, polled.text
    assert polled.json()["state"] == "failed"
    assert polled.json()["failure_code"] == "SOURCE_VALIDATION_FENCE_DRIFT"

    requeued_response = client.post(
        f"/v1/sources/{source['id']}/health-check",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": drifted_version, "reason": "Retry after fence drift"},
    )
    assert requeued_response.status_code == 202, requeued_response.text
    requeued = requeued_response.json()
    assert requeued["id"] != job["id"]
    assert requeued["state"] == "queued"
    assert requeued["expected_source_row_version"] == drifted_version + 1


@pytest.mark.parametrize(
    ("claim_override", "override_value"),
    [
        ("owner_token", "stale-owner-token"),
        ("expected_attempt", 2),
        ("expected_fencing_version", 2),
    ],
)
def test_source_fence_drift_does_not_authorize_a_stale_claim(
    client: TestClient,
    principal_id: str,
    claim_override: str,
    override_value: str | int,
) -> None:
    workspace = create_workspace(client, principal_id, f"Stale claim {claim_override}")
    source = _cloud_source(client, principal_id, workspace["id"])
    queued_response = client.post(
        f"/v1/sources/{source['id']}/health-check",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": source["row_version"], "reason": "Stale claim"},
    )
    assert queued_response.status_code == 202, queued_response.text
    job = queued_response.json()
    owner_token = "current-owner-token"

    with get_session_factory()() as db:
        claimed = SourceValidationJobRepository.claim(
            db,
            workspace_id=workspace["id"],
            job_id=job["id"],
            owner_token=owner_token,
        )
        assert claimed is not None
        drifted_source = db.get(SourceConnection, source["id"])
        assert drifted_source is not None
        drifted_source.status = "disabled"
        drifted_source.health_state = "disabled"
        drifted_source.row_version += 1
        db.commit()
        drifted_version = drifted_source.row_version

        claim_args: dict[str, str | int] = {
            "owner_token": owner_token,
            "expected_attempt": claimed.attempt,
            "expected_fencing_version": claimed.fencing_version,
        }
        claim_args[claim_override] = override_value
        with pytest.raises(ApiError) as raised:
            SourceValidationJobRepository.complete(
                db,
                workspace_id=workspace["id"],
                job_id=job["id"],
                owner_token=str(claim_args["owner_token"]),
                expected_attempt=int(claim_args["expected_attempt"]),
                expected_fencing_version=int(claim_args["expected_fencing_version"]),
                source_status="healthy",
            )
        assert raised.value.code == "JOB_LEASE_EXPIRED"
        db.rollback()

        still_claimed = db.get(SourceValidationJobRecord, job["id"])
        unchanged_source = db.get(SourceConnection, source["id"])
        assert still_claimed is not None
        assert still_claimed.state == "claimed"
        assert still_claimed.result_source_status is None
        assert still_claimed.lease_owner_token is not None
        assert unchanged_source is not None
        assert unchanged_source.status == "disabled"
        assert unchanged_source.row_version == drifted_version

        terminal = SourceValidationJobRepository.complete(
            db,
            workspace_id=workspace["id"],
            job_id=job["id"],
            owner_token=owner_token,
            expected_attempt=claimed.attempt,
            expected_fencing_version=claimed.fencing_version,
            source_status="healthy",
        )
        assert terminal.state == "failed"
        assert terminal.failure_code == "SOURCE_VALIDATION_FENCE_DRIFT"


def test_reconnect_failure_is_workspace_scoped_and_secret_safe(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Reconnect workspace")
    other = create_workspace(client, principal_id, "Other reconnect workspace")
    source = _cloud_source(client, principal_id, workspace["id"])
    response = client.post(
        f"/v1/sources/{source['id']}/reconnect",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": source["row_version"], "reason": "Reconnect"},
    )
    assert response.status_code == 202, response.text
    job = response.json()
    secret = "Bearer ghp_abcdefghijklmnopqrstuvwxyz123456"
    local_path = "/Users/alice/private/source-token.txt"
    with get_session_factory()() as db:
        claimed = SourceValidationJobRepository.claim(
            db,
            workspace_id=workspace["id"],
            job_id=job["id"],
            owner_token="failure-worker",
            now=datetime.now(UTC) - timedelta(seconds=1),
        )
        assert claimed is not None
        with pytest.raises(ApiError, match="source validation lease"):
            SourceValidationJobRepository.fail(
                db,
                workspace_id=workspace["id"],
                job_id=job["id"],
                owner_token="failure-worker",
                expected_attempt=1,
                expected_fencing_version=0,
                failure_code="AUTH_TOKEN_REJECTED",
                reason="stale fence",
            )
        failed = SourceValidationJobRepository.fail(
            db,
            workspace_id=workspace["id"],
            job_id=job["id"],
            owner_token="failure-worker",
            expected_attempt=claimed.attempt,
            expected_fencing_version=claimed.fencing_version,
            failure_code="AUTH_TOKEN_REJECTED",
            reason=f"Connector returned {secret} from {local_path}",
        )
        assert secret not in (failed.failure_reason or "")
        assert local_path not in (failed.failure_reason or "")
        audit_reason = db.scalar(
            select(AuditLog.reason).where(
                AuditLog.workspace_id == workspace["id"],
                AuditLog.action == "source.validation_failed",
            )
        )
        assert secret not in (audit_reason or "")
        assert local_path not in (audit_reason or "")

    hidden = client.get(
        f"/v1/source-validation-jobs/{job['id']}",
        headers=query_headers(principal_id, other["id"]),
    )
    assert hidden.status_code == 404
    polled = client.get(
        f"/v1/source-validation-jobs/{job['id']}",
        headers=query_headers(principal_id, workspace["id"]),
    )
    assert polled.status_code == 200
    assert polled.json()["state"] == "failed"
    assert secret not in polled.text
    assert local_path not in polled.text


def test_schedule_freezes_watchlist_rules_and_source_patch_synchronizes_safely(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Frozen schedule workspace")
    project = create_project(client, principal_id, workspace["id"])
    source = _cloud_source(client, principal_id, workspace["id"])
    activated_response = client.post(
        f"/v1/sources/{source['id']}/activate",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": source["row_version"], "reason": "Approve target"},
    )
    assert activated_response.status_code == 200, activated_response.text
    activated = activated_response.json()
    watchlist_response = client.post(
        "/v1/watchlists",
        headers=command_headers(principal_id, workspace["id"]),
        json={
            "project_id": project["id"],
            "name": "Frozen rule Watchlist",
            "objective": "Freeze exact collection scope",
            "source_connection_ids": [source["id"]],
            "rules": {
                "entities": ["Glint"],
                "topics": ["permissions"],
                "query_rules": {
                    "include_terms": ["preview"],
                    "exclude_terms": ["spam"],
                    "languages": ["en"],
                    "regions": ["US"],
                },
                "cadence": "daily",
                "current_window_days": 7,
                "baseline_window_days": 28,
            },
        },
    )
    assert watchlist_response.status_code == 201, watchlist_response.text
    watchlist = watchlist_response.json()
    active_watchlist_response = client.post(
        f"/v1/watchlists/{watchlist['id']}/activate",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": watchlist["row_version"], "reason": "Collect"},
    )
    assert active_watchlist_response.status_code == 200, active_watchlist_response.text
    watchlist = active_watchlist_response.json()
    schedule_response = client.post(
        "/v1/collection-schedules",
        headers=command_headers(principal_id, workspace["id"]),
        json={
            "workspace_id": workspace["id"],
            "source_connection_id": source["id"],
            "watchlist_id": watchlist["id"],
            "query_json": {"owner": "openai", "repo": "glint", "query": "preview"},
            "cadence_seconds": 3600,
            "timezone": "UTC",
            "misfire_policy": "run_once",
            "catch_up": False,
            "overlap_policy": "skip",
            "next_run_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "enabled": True,
        },
    )
    assert schedule_response.status_code == 201, schedule_response.text
    schedule = schedule_response.json()
    frozen = schedule["query_json"]
    assert frozen["watchlist_rules_version"] == watchlist["rules_version"]
    assert frozen["include_terms"] == ["preview"]
    assert frozen["exclude_terms"] == ["spam"]
    assert frozen["languages"] == ["en"]
    assert frozen["regions"] == ["US"]
    assert frozen["entities"] == ["Glint"]
    assert frozen["topics"] == ["permissions"]
    assert frozen["current_window"] == {"days": 7}
    assert frozen["baseline_window"] == {"days": 28, "offset_days": 7}

    with get_session_factory()() as db:
        row = db.get(SourceConnection, source["id"])
        assert row is not None
        row.status = "auth_required"
        row.health_state = "auth_required"
        db.commit()
    patched_response = client.patch(
        f"/v1/sources/{source['id']}",
        headers=command_headers(principal_id, workspace["id"]),
        json={
            "source_config": {
                "connector_type": "github",
                "repositories": [{"owner": "openai", "repository": "glint-next"}],
            },
            "cadence": "manual",
            "timezone": "Asia/Shanghai",
            "expected_row_version": activated["row_version"],
        },
    )
    assert patched_response.status_code == 200, patched_response.text
    patched = patched_response.json()
    assert patched["status"] == "validating"
    schedules = client.get(
        "/v1/collection-schedules", headers=query_headers(principal_id, workspace["id"])
    ).json()["items"]
    assert len(schedules) == 1
    synchronized = schedules[0]
    assert synchronized["query_json"]["repo"] == "glint-next"
    assert synchronized["query_json"]["watchlist_rules_version"] == watchlist["rules_version"]
    assert synchronized["timezone"] == "Asia/Shanghai"
    assert synchronized["enabled"] is False
    assert synchronized["lease_held"] is False
    assert synchronized["row_version"] == schedule["row_version"] + 1

    removed = client.post(
        f"/v1/sources/{source['id']}/remove",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": patched["row_version"], "reason": "Remove safely"},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["status"] == "disabled"
    assert (
        client.get(
            f"/v1/sources/{source['id']}",
            headers=query_headers(principal_id, workspace["id"]),
        ).status_code
        == 200
    )
