from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from services.api.app.db.models import AuditLog, Project
from services.api.app.db.session import get_session_factory
from tests.conftest import command_headers, query_headers
from tests.security.helpers import create_project, create_source, create_workspace


def test_idempotency_replays_identical_command_and_rejects_fingerprint_conflict(
    client: TestClient,
) -> None:
    principal_id = str(uuid4())
    workspace = create_workspace(client, principal_id)
    key = str(uuid4())
    headers = command_headers(principal_id, workspace["id"])
    headers["Idempotency-Key"] = key

    first = client.post("/v1/projects", headers=headers, json={"name": "Original"})
    replay = client.post("/v1/projects", headers=headers, json={"name": "Original"})
    conflict = client.post("/v1/projects", headers=headers, json={"name": "Changed"})

    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    with get_session_factory()() as db:
        assert (
            db.scalar(select(func.count(Project.id)).where(Project.workspace_id == workspace["id"]))
            == 1
        )


def test_idempotency_claim_prevents_concurrent_duplicate_side_effects(
    client: TestClient,
) -> None:
    principal_id = str(uuid4())
    workspace = create_workspace(client, principal_id, "Concurrent idempotency")
    headers = command_headers(principal_id, workspace["id"])
    headers["Idempotency-Key"] = str(uuid4())
    barrier = Barrier(2)

    def submit() -> tuple[int, str, str | None]:
        barrier.wait()
        response = client.post("/v1/projects", headers=headers, json={"name": "Exactly once"})
        return (
            response.status_code,
            response.json()["id"],
            response.headers.get("Idempotency-Replayed"),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: submit(), range(2)))

    assert {status for status, _, _ in results} == {201}
    assert len({project_id for _, project_id, _ in results}) == 1
    assert sorted(replayed for _, _, replayed in results if replayed is not None) == ["true"]
    with get_session_factory()() as db:
        assert (
            db.scalar(
                select(func.count(Project.id)).where(
                    Project.workspace_id == workspace["id"], Project.name == "Exactly once"
                )
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.workspace_id == workspace["id"],
                    AuditLog.action == "project.created",
                )
            )
            == 1
        )


def test_expected_row_version_prevents_lost_update(client: TestClient) -> None:
    principal_id = str(uuid4())
    workspace = create_workspace(client, principal_id)
    project = create_project(client, principal_id, workspace["id"], "Version one")

    updated = client.patch(
        f"/v1/projects/{project['id']}",
        headers=command_headers(principal_id, workspace["id"]),
        json={"name": "Version two", "expected_row_version": project["row_version"]},
    )
    stale = client.patch(
        f"/v1/projects/{project['id']}",
        headers=command_headers(principal_id, workspace["id"]),
        json={"name": "Stale overwrite", "expected_row_version": project["row_version"]},
    )

    assert updated.status_code == 200
    assert updated.json()["row_version"] == project["row_version"] + 1
    assert stale.status_code == 412
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    assert stale.json()["error"]["details"]["current_row_version"] == updated.json()["row_version"]
    listed = client.get(
        "/v1/projects", headers=query_headers(principal_id, workspace["id"])
    ).json()["items"]
    assert [(item["name"], item["row_version"]) for item in listed] == [
        ("Version two", updated.json()["row_version"])
    ]


def test_audit_storage_redacts_secrets_and_local_paths(client: TestClient) -> None:
    principal_id = str(uuid4())
    workspace = create_workspace(client, principal_id)
    source = create_source(client, principal_id, workspace["id"])
    secret = "Bearer ghp_abcdefghijklmnopqrstuvwxyz123456"
    local_path = "/Users/alice/private/glint-token.txt"
    reason = f"Approved after diagnostic {secret} was read from {local_path}"

    response = client.post(
        f"/v1/sources/{source['id']}/activate",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": source["row_version"], "reason": reason},
    )

    assert response.status_code == 200
    with get_session_factory()() as db:
        stored = db.scalar(
            select(AuditLog.reason)
            .where(
                AuditLog.workspace_id == workspace["id"],
                AuditLog.action == "source.activated",
            )
            .order_by(AuditLog.occurred_at.desc())
        )
    assert stored is not None
    assert secret not in stored
    assert local_path not in stored
    assert "REDACTED" in stored


def test_validation_error_does_not_echo_traversal_path(client: TestClient) -> None:
    principal_id = str(uuid4())
    workspace = create_workspace(client, principal_id)
    source = create_source(client, principal_id, workspace["id"])
    traversal = "../../private/secret.csv"
    body = b"title,body\nsecurity,safe\n"

    response = client.post(
        "/v1/imports",
        headers=command_headers(principal_id, workspace["id"]),
        json={
            "source_connection_id": source["id"],
            "expected_source_row_version": source["row_version"],
            "expected_current_import_manifest_id": None,
            "local_manifest_digest": "sha256:" + "1" * 64,
            "file_digest": "sha256:" + "2" * 64,
            "expected_upload_digest": "sha256:" + "3" * 64,
            "client_file_name": traversal,
            "file_size_bytes": len(body),
            "media_type": "text/csv",
            "parser_version": "csv-v1",
            "schema_version": "security-import-v1",
            "selected_scope_json": {"columns": ["title", "body"]},
            "selected_scope_digest": "sha256:" + "4" * 64,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert traversal not in response.text
