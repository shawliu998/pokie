from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from packages.contracts.schemas import ImportNormalizationProposal
from services.api.app.db.models import (
    ContentItem,
    ContentVersion,
    ImportManifest,
    ImportManifestContentVersion,
    ImportSession,
    RawContentItem,
)
from services.api.app.db.session import get_session_factory
from services.api.app.modules.sources.service import ImportFinalizationRepository
from tests.conftest import command_headers, query_headers
from tests.integration.import_proposals import NormalizedFixtureItem, normalization_proposal
from tests.security.helpers import (
    bootstrap_import_scope,
    complete_upload,
    queue_finalization,
    sha256,
    upload_object,
)


def _finalize_version(
    client: TestClient,
    *,
    principal_id: str,
    scope: dict[str, Any],
    body: bytes,
    normalized_body: str,
) -> tuple[ImportManifest, ImportNormalizationProposal]:
    workspace_id = scope["workspace"]["id"]
    source = client.get(
        f"/v1/sources/{scope['source']['id']}",
        headers=query_headers(principal_id, workspace_id),
    ).json()
    created = client.post(
        "/v1/imports",
        headers=command_headers(principal_id, workspace_id),
        json={
            "source_connection_id": source["id"],
            "expected_source_row_version": source["row_version"],
            "expected_current_import_manifest_id": (
                source["current_import_manifest"]["id"]
                if source["current_import_manifest"] is not None
                else None
            ),
            "local_manifest_digest": sha256(body),
            "file_digest": sha256(body),
            "expected_upload_digest": sha256(body),
            "client_file_name": "stable.csv",
            "file_size_bytes": len(body),
            "media_type": "text/csv",
            "parser_version": "csv-v1",
            "schema_version": "stable-v1",
            "selected_scope_json": {"columns": ["title", "body"]},
            "selected_scope_digest": sha256(b"title,body"),
        },
    )
    assert created.status_code == 201, created.text
    session = created.json()
    preview_response = client.get(
        f"/v1/imports/{session['id']}/upload-consent/preview",
        headers=query_headers(principal_id, workspace_id),
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
    consent = consent_response.json()
    session = consent["import_session"]
    upload_object(
        client,
        principal_id,
        workspace_id,
        session["id"],
        consent_response.headers["X-Upload-Grant"],
        body,
    )
    session = complete_upload(client, principal_id, workspace_id, session, consent)
    command = queue_finalization(client, principal_id, workspace_id, session)
    with get_session_factory()() as db:
        ImportFinalizationRepository.claim(
            db,
            workspace_id=workspace_id,
            command_id=command["id"],
            worker_id="version-worker",
        )
        items: list[NormalizedFixtureItem] = [
            {
                "external_id": "stable-identity",
                "title": "Stable title",
                "body": normalized_body,
                "canonical_url": "https://example.com/stable",
                "author": "Ada",
                "published_at": "2026-07-15T08:00:00Z",
            }
        ]
        proposal = normalization_proposal(db, command_id=command["id"], items=items)
        manifest = ImportFinalizationRepository.complete(
            db,
            workspace_id=workspace_id,
            command_id=command["id"],
            worker_id="version-worker",
            proposal=proposal,
        )
        db.expunge(manifest)
    return manifest, proposal


def test_repeated_identity_reuses_frozen_version_and_changed_digest_appends(
    client: TestClient, principal_id: str
) -> None:
    scope = bootstrap_import_scope(client, principal_id)
    first_body = b"id,title,body\nstable-identity,Stable title,Alpha\n"
    changed_body = b"id,title,body\nstable-identity,Stable title,Beta\n"
    first, first_proposal = _finalize_version(
        client,
        principal_id=principal_id,
        scope=scope,
        body=first_body,
        normalized_body="title: Stable title\nbody: Alpha",
    )
    identical, identical_proposal = _finalize_version(
        client,
        principal_id=principal_id,
        scope=scope,
        body=first_body,
        normalized_body="title: Stable title\nbody: Alpha",
    )
    changed, changed_proposal = _finalize_version(
        client,
        principal_id=principal_id,
        scope=scope,
        body=changed_body,
        normalized_body="title: Stable title\nbody: Beta",
    )

    assert first.id != identical.id != changed.id
    assert first.content_count == identical.content_count == changed.content_count == 1
    assert first_proposal.content_items[0].id == identical_proposal.content_items[0].id
    assert first_proposal.content_versions[0].id == identical_proposal.content_versions[0].id
    assert changed_proposal.content_versions[0].id != first_proposal.content_versions[0].id
    with get_session_factory()() as db:
        assert db.scalar(select(func.count(ContentItem.id))) == 1
        versions = db.scalars(select(ContentVersion).order_by(ContentVersion.version_number)).all()
        assert [row.version_number for row in versions] == [1, 2]
        assert [row.id for row in versions] == [
            str(first_proposal.content_versions[0].id),
            str(changed_proposal.content_versions[0].id),
        ]
        links = db.scalars(
            select(ImportManifestContentVersion).order_by(
                ImportManifestContentVersion.import_manifest_id
            )
        ).all()
        links_by_manifest = {row.import_manifest_id: row.content_version_id for row in links}
        assert links_by_manifest[first.id] == str(first_proposal.content_versions[0].id)
        assert links_by_manifest[identical.id] == str(first_proposal.content_versions[0].id)
        assert links_by_manifest[changed.id] == str(changed_proposal.content_versions[0].id)
        assert db.scalar(select(func.count(RawContentItem.id))) == 3
        sessions = db.scalars(select(ImportSession)).all()
        assert len(sessions) == 3
        assert all(row.state == "finalized" and row.terminal_manifest_id for row in sessions)
