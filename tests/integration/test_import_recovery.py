from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.db.models import ImportSession
from services.api.app.db.session import get_session_factory
from services.api.app.modules.sources.service import ImportFinalizationRepository
from tests.conftest import command_headers, query_headers
from tests.security.helpers import (
    bootstrap_import_scope,
    complete_upload,
    create_consented_import,
    queue_finalization,
    sha256,
    upload_object,
)


def _create_request(source: dict[str, object], body: bytes) -> dict[str, object]:
    return {
        "source_connection_id": source["id"],
        "expected_source_row_version": source["row_version"],
        "expected_current_import_manifest_id": None,
        "local_manifest_digest": sha256(body),
        "file_digest": sha256(body),
        "expected_upload_digest": sha256(body),
        "client_file_name": "recovery.csv",
        "file_size_bytes": len(body),
        "media_type": "text/csv",
        "parser_version": "csv-v1",
        "schema_version": "recovery-v1",
        "selected_scope_json": {"columns": ["title", "body"]},
        "selected_scope_digest": sha256(b"title,body"),
    }


def test_permanent_failed_import_releases_source_for_new_session(
    client: TestClient, principal_id: str
) -> None:
    body = b"title,body\nrecovery,permanent failure\n"
    scope = bootstrap_import_scope(client, principal_id)
    first, _consent, _grant = create_consented_import(client, principal_id, scope, body)
    with get_session_factory()() as db:
        row = db.get(ImportSession, first["id"])
        assert row is not None
        row.state = "failed"
        row.failure_code = "PERMANENT_INVALID_SCHEMA"
        row.retryable = False
        row.row_version += 1
        db.commit()
    second_body = b"title,body\nrecovery,corrected input\n"
    response = client.post(
        "/v1/imports",
        headers=command_headers(principal_id, scope["workspace"]["id"]),
        json=_create_request(scope["source"], second_body),
    )
    assert response.status_code == 201, response.text
    assert response.json()["id"] != first["id"]


def test_retryable_failure_blocks_new_session_and_requeues_same_command(
    client: TestClient, principal_id: str
) -> None:
    body = b"title,body\nrecovery,retry worker\n"
    scope = bootstrap_import_scope(client, principal_id)
    workspace_id = scope["workspace"]["id"]
    session, consent, grant = create_consented_import(client, principal_id, scope, body)
    upload_object(client, principal_id, workspace_id, session["id"], grant, body)
    session = complete_upload(client, principal_id, workspace_id, session, consent)
    command = queue_finalization(client, principal_id, workspace_id, session)
    with get_session_factory()() as db:
        ImportFinalizationRepository.claim(
            db,
            workspace_id=workspace_id,
            command_id=command["id"],
            worker_id="recovery-worker",
        )
        failed = ImportFinalizationRepository.fail(
            db,
            workspace_id=workspace_id,
            command_id=command["id"],
            worker_id="recovery-worker",
            failure_code="OBJECT_UNAVAILABLE",
            retryable=True,
        )
        assert failed.state == "failed" and failed.retryable is True

    blocked = client.post(
        "/v1/imports",
        headers=command_headers(principal_id, workspace_id),
        json=_create_request(scope["source"], body),
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "ACTIVE_IMPORT_EXISTS"

    current = client.get(
        f"/v1/imports/{session['id']}", headers=query_headers(principal_id, workspace_id)
    ).json()
    retry_headers = command_headers(principal_id, workspace_id)
    retry_headers["Idempotency-Key"] = str(uuid4())
    retried = client.post(
        f"/v1/imports/{session['id']}/finalize",
        headers=retry_headers,
        json={"expected_row_version": current["row_version"]},
    )
    assert retried.status_code == 202, retried.text
    assert retried.json()["id"] == command["id"]
    assert retried.json()["state"] == "queued"
    recovery = client.get("/v1/imports", headers=query_headers(principal_id, workspace_id))
    assert recovery.status_code == 200, recovery.text
    item = next(
        value
        for value in recovery.json()["items"]
        if value["import_session"]["id"] == session["id"]
    )
    assert item["import_session"]["state"] == "validating"
    assert item["finalization_job"]["id"] == command["id"]
    assert item["finalization_job"]["state"] == "queued"
