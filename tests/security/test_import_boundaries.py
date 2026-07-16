from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from services.api.app.core.errors import ApiError
from services.api.app.core.object_store import FilesystemObjectStore, get_object_store
from services.api.app.db.models import (
    ImportFinalizationJobRecord,
    ImportManifest,
    ImportSession,
    SourceConnection,
    TransferConsentRecord,
)
from services.api.app.db.session import get_session_factory
from services.api.app.modules.sources.service import ImportFinalizationRepository
from tests.conftest import command_headers
from tests.integration.import_proposals import normalization_proposal
from tests.security.helpers import (
    bootstrap_import_scope,
    complete_upload,
    create_consented_import,
    queue_finalization,
    upload_object,
)


def _uploaded_import(
    client: TestClient,
    principal_id: str,
    body: bytes,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    scope = bootstrap_import_scope(client, principal_id)
    session, consent, upload_grant = create_consented_import(client, principal_id, scope, body)
    workspace_id = str(scope["workspace"]["id"])
    upload_object(client, principal_id, workspace_id, session["id"], upload_grant, body)
    return scope, session, consent


def test_expired_consent_blocks_upload_completion(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal_id = str(uuid4())
    body = b"title,body\nsecurity,expiry gate\n"
    scope, session, consent = _uploaded_import(client, principal_id, body)
    workspace_id = str(scope["workspace"]["id"])

    after_expiry = datetime.fromisoformat(consent["consent_record"]["expires_at"]) + timedelta(
        seconds=1
    )
    monkeypatch.setattr("services.api.app.modules.sources.service.utcnow", lambda: after_expiry)

    response = client.post(
        f"/v1/imports/{session['id']}/upload-complete",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_row_version": session["row_version"],
            "object_key": consent["upload"]["object_key"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONSENT_EXPIRED_OR_REVOKED"
    with get_session_factory()() as db:
        persisted = db.get(ImportSession, session["id"])
        assert persisted is not None
        assert persisted.state == "consented"
        assert persisted.uploaded_object_key is None


def test_append_only_revocation_blocks_upload_completion(client: TestClient) -> None:
    principal_id = str(uuid4())
    body = b"title,body\nsecurity,revocation gate\n"
    scope, session, consent = _uploaded_import(client, principal_id, body)
    workspace_id = str(scope["workspace"]["id"])

    with get_session_factory()() as db:
        granted = db.get(TransferConsentRecord, consent["consent_record"]["id"])
        assert granted is not None
        db.add(
            TransferConsentRecord(
                workspace_id=granted.workspace_id,
                import_session_id=granted.import_session_id,
                decision="revoke",
                local_manifest_digest=granted.local_manifest_digest,
                file_digest=granted.file_digest,
                expected_upload_digest=granted.expected_upload_digest,
                selected_scope_json=granted.selected_scope_json,
                selected_scope_digest=granted.selected_scope_digest,
                destination_workspace_id=granted.destination_workspace_id,
                upload_object_scope=granted.upload_object_scope,
                model_egress_authorization=granted.model_egress_authorization,
                policy_version=granted.policy_version,
                actor_id=principal_id,
                expires_at=granted.expires_at,
                supersedes_id=granted.id,
                data_authenticity=granted.data_authenticity,
            )
        )
        db.commit()

    response = client.post(
        f"/v1/imports/{session['id']}/upload-complete",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_row_version": session["row_version"],
            "object_key": consent["upload"]["object_key"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONSENT_EXPIRED_OR_REVOKED"
    with get_session_factory()() as db:
        assert (
            db.scalar(
                select(func.count(ImportManifest.id)).where(
                    ImportManifest.import_session_id == session["id"]
                )
            )
            == 0
        )


def test_upload_completion_rejects_client_supplied_object_key(client: TestClient) -> None:
    principal_id = str(uuid4())
    body = b"title,body\nsecurity,object scope gate\n"
    scope, session, _consent = _uploaded_import(client, principal_id, body)
    workspace_id = str(scope["workspace"]["id"])

    response = client.post(
        f"/v1/imports/{session['id']}/upload-complete",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_row_version": session["row_version"],
            "object_key": "../another-workspace/object.csv",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OBJECT_SCOPE_MISMATCH"
    with get_session_factory()() as db:
        persisted = db.get(ImportSession, session["id"])
        assert persisted is not None
        assert persisted.state == "consented"
        assert persisted.uploaded_object_key is None


def test_upload_rejects_oversize_content_length_before_reading_body(client: TestClient) -> None:
    principal_id = str(uuid4())
    body = b"title,body\nsecurity,content length gate\n"
    scope = bootstrap_import_scope(client, principal_id)
    session, consent, upload_grant = create_consented_import(client, principal_id, scope, body)
    workspace_id = str(scope["workspace"]["id"])
    response = client.put(
        f"/v1/imports/{session['id']}/object",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace_id,
            "X-Upload-Grant": upload_grant,
            "Content-Type": "text/csv",
            "Content-Length": str(len(body) + 1),
        },
        content=b"x",
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "POLICY_BLOCKED"
    with pytest.raises((FileNotFoundError, KeyError)):
        get_object_store().get(consent["upload"]["object_key"])


def test_upload_stream_cap_rejects_chunked_body_without_content_length(
    client: TestClient,
) -> None:
    principal_id = str(uuid4())
    body = b"title,body\nsecurity,chunked stream gate\n"
    scope = bootstrap_import_scope(client, principal_id)
    session, consent, upload_grant = create_consented_import(client, principal_id, scope, body)
    workspace_id = str(scope["workspace"]["id"])

    def chunks() -> Any:
        yield body
        yield b"x"

    response = client.put(
        f"/v1/imports/{session['id']}/object",
        headers={
            "Authorization": f"Bearer {principal_id}",
            "X-Workspace-ID": workspace_id,
            "X-Upload-Grant": upload_grant,
            "Content-Type": "text/csv",
        },
        content=chunks(),
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "POLICY_BLOCKED"
    with pytest.raises((FileNotFoundError, KeyError)):
        get_object_store().get(consent["upload"]["object_key"])


@pytest.mark.parametrize("tamper", ["digest", "size", "media_type"])
def test_finalizer_rechecks_object_before_commit(client: TestClient, tamper: str) -> None:
    principal_id = str(uuid4())
    body = b"title,body\nsecurity,safe marker\n"
    scope, session, consent = _uploaded_import(client, principal_id, body)
    workspace_id = str(scope["workspace"]["id"])
    session = complete_upload(client, principal_id, workspace_id, session, consent)
    job = queue_finalization(client, principal_id, workspace_id, session)
    with get_session_factory()() as db:
        ImportFinalizationRepository.claim(
            db,
            workspace_id=workspace_id,
            command_id=job["id"],
            worker_id="security-worker",
        )
        proposal = normalization_proposal(
            db,
            command_id=job["id"],
            items=[
                {
                    "external_id": f"{session['id']}:row:1",
                    "title": "security",
                    "body": "safe marker",
                }
            ],
        )

    object_key = consent["upload"]["object_key"]
    if tamper == "digest":
        replacement = body.replace(b"safe", b"evil")
        assert len(replacement) == len(body)
        get_object_store().put(object_key, replacement, "text/csv")
    elif tamper == "size":
        get_object_store().put(object_key, body + b"x", "text/csv")
    else:
        get_object_store().put(object_key, body, "application/csv")

    with get_session_factory()() as db, pytest.raises(ApiError) as caught:
        ImportFinalizationRepository.complete(
            db,
            workspace_id=workspace_id,
            command_id=job["id"],
            worker_id="security-worker",
            proposal=proposal,
        )
    assert caught.value.code == "OBJECT_SCOPE_MISMATCH"

    with get_session_factory()() as db:
        persisted_session = db.get(ImportSession, session["id"])
        persisted_job = db.get(ImportFinalizationJobRecord, job["id"])
        source = db.get(SourceConnection, scope["source"]["id"])
        assert persisted_session is not None and persisted_session.state == "validating"
        assert persisted_job is not None and persisted_job.state == "claimed"
        assert source is not None and source.current_import_manifest_id is None
        assert (
            db.scalar(
                select(func.count(ImportManifest.id)).where(
                    ImportManifest.import_session_id == session["id"]
                )
            )
            == 0
        )


@pytest.mark.parametrize(
    "key",
    [
        "../escaped.txt",
        "nested/../../escaped.txt",
        "/tmp/glint-absolute-escape.txt",
    ],
)
def test_filesystem_object_store_rejects_key_traversal(tmp_path: Path, key: str) -> None:
    root = tmp_path / "objects"
    store = FilesystemObjectStore(root)

    with pytest.raises(ValueError, match="escaped"):
        store.put(key, b"must stay inside root", "text/plain")

    assert not (tmp_path / "escaped.txt").exists()
    assert not Path("/tmp/glint-absolute-escape.txt").exists()


def test_filesystem_object_store_does_not_trust_tampered_metadata(tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path / "objects")
    original = store.put("imports/security.csv", b"trusted", "text/csv")
    object_path = store.root / original.key
    metadata_path = object_path.with_suffix(object_path.suffix + ".meta.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["digest"] = original.digest
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    object_path.write_bytes(b"altered")

    observed = store.get(original.key)

    assert observed.body == b"altered"
    assert observed.digest != original.digest
