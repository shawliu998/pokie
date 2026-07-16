from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from packages.domain.canonical import canonical_digest
from services.api.app.db.models import (
    ImportSession,
    SourceConnection,
    TransferConsentRecord,
    UploadGrant,
)
from services.api.app.db.session import get_session_factory
from tests.conftest import command_headers, query_headers
from tests.security.helpers import bootstrap_import_scope, sha256


def _draft_import(client: TestClient, principal_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    scope = bootstrap_import_scope(client, principal_id)
    workspace_id = scope["workspace"]["id"]
    source = scope["source"]
    body = b"title,body\nPreview,Consent must precede transfer\n"
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
            "client_file_name": "preview.csv",
            "file_size_bytes": len(body),
            "media_type": "text/csv",
            "parser_version": "csv-v1",
            "schema_version": "preview-v1",
            "selected_scope_json": {"columns": ["title", "body"]},
            "selected_scope_digest": sha256(b"title,body"),
        },
    )
    assert response.status_code == 201, response.text
    return scope, response.json()


def _preview(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    session: dict[str, Any],
) -> dict[str, Any]:
    response = client.get(
        f"/v1/imports/{session['id']}/upload-consent/preview",
        headers=query_headers(principal_id, workspace_id),
        params={"expected_row_version": session["row_version"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _consent_body(preview: dict[str, Any]) -> dict[str, Any]:
    return {
        "preview_scope": preview["preview_scope"],
        "scope_digest": preview["scope_digest"],
        "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        "confirmation": True,
    }


def test_preview_is_side_effect_free_and_exact_scope_grants_one_object(
    client: TestClient, principal_id: str
) -> None:
    scope, session = _draft_import(client, principal_id)
    workspace_id = scope["workspace"]["id"]

    preview = _preview(client, principal_id, workspace_id, session)
    exact = preview["preview_scope"]
    assert exact["destination_workspace_id"] == workspace_id
    assert exact["import_session_id"] == session["id"]
    assert exact["import_session_row_version"] == session["row_version"]
    assert exact["source_connection_id"] == scope["source"]["id"]
    assert exact["source_row_version"] == scope["source"]["row_version"]
    assert exact["current_import_manifest_id"] is None
    assert exact["upload_object_scope"] == {
        "object_key": f"workspaces/{workspace_id}/imports/{session['id']}/payload.csv",
        "max_bytes": session["file_size_bytes"],
        "media_type": session["media_type"],
    }
    assert preview["scope_digest"] == canonical_digest(exact)

    with get_session_factory()() as db:
        assert db.scalar(select(func.count(TransferConsentRecord.id))) == 0
        assert db.scalar(select(func.count(UploadGrant.id))) == 0
        persisted = db.get(ImportSession, session["id"])
        assert persisted is not None
        assert persisted.state == "draft"
        assert persisted.row_version == session["row_version"]

    response = client.post(
        f"/v1/imports/{session['id']}/upload-consent",
        headers=command_headers(principal_id, workspace_id),
        json=_consent_body(preview),
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Upload-Grant"]
    payload = response.json()
    assert payload["consent_record"]["upload_object_scope"] == exact["upload_object_scope"]
    assert payload["consent_record"]["policy_version"] == exact["policy_version"]
    assert payload["upload"]["object_key"] == exact["upload_object_scope"]["object_key"]
    with get_session_factory()() as db:
        assert db.scalar(select(func.count(TransferConsentRecord.id))) == 1
        assert db.scalar(select(func.count(UploadGrant.id))) == 1


def test_tampered_preview_scope_is_rejected_before_ledger_append(
    client: TestClient, principal_id: str
) -> None:
    scope, session = _draft_import(client, principal_id)
    workspace_id = scope["workspace"]["id"]
    preview = _preview(client, principal_id, workspace_id, session)
    tampered = deepcopy(preview)
    tampered["preview_scope"]["upload_object_scope"]["max_bytes"] += 1

    response = client.post(
        f"/v1/imports/{session['id']}/upload-consent",
        headers=command_headers(principal_id, workspace_id),
        json=_consent_body(tampered),
    )
    assert response.status_code == 412
    assert response.json()["error"]["code"] == "CONSENT_SCOPE_STALE"
    with get_session_factory()() as db:
        assert db.scalar(select(func.count(TransferConsentRecord.id))) == 0
        assert db.scalar(select(func.count(UploadGrant.id))) == 0


def test_source_version_drift_rejects_preview_without_authorizing_transfer(
    client: TestClient, principal_id: str
) -> None:
    scope, session = _draft_import(client, principal_id)
    workspace_id = scope["workspace"]["id"]
    preview = _preview(client, principal_id, workspace_id, session)
    with get_session_factory()() as db:
        source = db.get(SourceConnection, scope["source"]["id"])
        assert source is not None
        source.row_version += 1
        db.commit()

    response = client.post(
        f"/v1/imports/{session['id']}/upload-consent",
        headers=command_headers(principal_id, workspace_id),
        json=_consent_body(preview),
    )
    assert response.status_code == 412
    assert response.json()["error"]["code"] == "STALE_SOURCE_VERSION"
    with get_session_factory()() as db:
        assert db.scalar(select(func.count(TransferConsentRecord.id))) == 0
        assert db.scalar(select(func.count(UploadGrant.id))) == 0
