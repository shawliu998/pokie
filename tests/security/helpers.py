from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import command_headers


def sha256(body: bytes) -> str:
    return f"sha256:{hashlib.sha256(body).hexdigest()}"


def create_workspace(
    client: TestClient, principal_id: str, name: str = "Security workspace"
) -> dict[str, Any]:
    response = client.post(
        "/v1/workspaces",
        headers=command_headers(principal_id),
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_project(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    name: str = "Security project",
) -> dict[str, Any]:
    response = client.post(
        "/v1/projects",
        headers=command_headers(principal_id, workspace_id),
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_source(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    name: str = "Security import",
) -> dict[str, Any]:
    response = client.post(
        "/v1/sources",
        headers=command_headers(principal_id, workspace_id),
        json={
            "name": name,
            "source_kind": "imported_dataset",
            "runtime": "static_import",
            "connector_type": "csv",
            "connector_version": "1.0.0",
            "data_scope": "workspace_confidential",
        },
    )
    assert response.status_code == 201, response.text
    source = response.json()
    activated = client.post(
        f"/v1/sources/{source['id']}/activate",
        headers=command_headers(principal_id, workspace_id),
        json={"expected_row_version": source["row_version"], "reason": "Security fixture"},
    )
    assert activated.status_code == 200, activated.text
    return activated.json()


def create_watchlist(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    project_id: str,
    source_id: str,
    *,
    active: bool = True,
) -> dict[str, Any]:
    response = client.post(
        "/v1/watchlists",
        headers=command_headers(principal_id, workspace_id),
        json={
            "project_id": project_id,
            "name": "Security watchlist",
            "objective": "Detect imported security markers without executing them",
            "source_connection_ids": [source_id],
            "rules": {
                "entities": ["Glint"],
                "query_rules": {"include_terms": ["security"]},
                "cadence": "manual",
                "current_window_days": 7,
                "baseline_window_days": 28,
            },
        },
    )
    assert response.status_code == 201, response.text
    watchlist = response.json()
    if not active:
        return watchlist
    activated = client.post(
        f"/v1/watchlists/{watchlist['id']}/activate",
        headers=command_headers(principal_id, workspace_id),
        json={"expected_row_version": watchlist["row_version"], "reason": "Security fixture"},
    )
    assert activated.status_code == 200, activated.text
    return activated.json()


def bootstrap_import_scope(
    client: TestClient,
    principal_id: str,
    *,
    with_watchlist: bool = False,
) -> dict[str, Any]:
    workspace = create_workspace(client, principal_id)
    project = create_project(client, principal_id, workspace["id"])
    source = create_source(client, principal_id, workspace["id"])
    result = {"workspace": workspace, "project": project, "source": source}
    if with_watchlist:
        result["watchlist"] = create_watchlist(
            client,
            principal_id,
            workspace["id"],
            project["id"],
            source["id"],
        )
    return result


def create_consented_import(
    client: TestClient,
    principal_id: str,
    scope: dict[str, Any],
    body: bytes,
    *,
    client_file_name: str = "security.csv",
) -> tuple[dict[str, Any], dict[str, Any], str]:
    workspace_id = scope["workspace"]["id"]
    source = scope["source"]
    response = client.post(
        "/v1/imports",
        headers=command_headers(principal_id, workspace_id),
        json={
            "source_connection_id": source["id"],
            "expected_source_row_version": source["row_version"],
            "expected_current_import_manifest_id": None,
            "local_manifest_digest": sha256(body),
            "file_digest": sha256(body),
            "expected_upload_digest": sha256(body),
            "client_file_name": client_file_name,
            "file_size_bytes": len(body),
            "media_type": "text/csv",
            "parser_version": "csv-v1",
            "schema_version": "security-import-v1",
            "selected_scope_json": {"columns": ["title", "body"]},
            "selected_scope_digest": sha256(b"title,body"),
        },
    )
    assert response.status_code == 201, response.text
    session = response.json()
    preview_response = client.get(
        f"/v1/imports/{session['id']}/upload-consent/preview",
        headers=command_headers(principal_id, workspace_id),
        params={"expected_row_version": session["row_version"]},
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    consent_response = client.post(
        f"/v1/imports/{session['id']}/upload-consent",
        headers=command_headers(principal_id, workspace_id),
        json={
            "preview_scope": preview["preview_scope"],
            "scope_digest": preview["scope_digest"],
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
            "confirmation": True,
        },
    )
    assert consent_response.status_code == 200, consent_response.text
    consent_payload = consent_response.json()
    return (
        consent_payload["import_session"],
        consent_payload,
        consent_response.headers["X-Upload-Grant"],
    )


def upload_object(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    session_id: str,
    upload_grant: str,
    body: bytes,
) -> None:
    response = client.put(
        f"/v1/imports/{session_id}/object",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace_id,
            "X-Upload-Grant": upload_grant,
            "Content-Type": "text/csv",
        },
        content=body,
    )
    assert response.status_code == 201, response.text


def complete_upload(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    session: dict[str, Any],
    consent_payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(
        f"/v1/imports/{session['id']}/upload-complete",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_row_version": session["row_version"],
            "object_key": consent_payload["upload"]["object_key"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def queue_finalization(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    session: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(
        f"/v1/imports/{session['id']}/finalize",
        headers=command_headers(principal_id, workspace_id),
        json={"expected_row_version": session["row_version"]},
    )
    assert response.status_code == 202, response.text
    return response.json()
