from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.db.models import (
    CollectionRun,
    ContentItem,
    ContentVersion,
    RawContentItem,
)
from services.api.app.db.session import get_session_factory
from tests.conftest import command_headers, query_headers
from tests.integration.test_cloud_sources_and_schedules import _github_source
from tests.security.helpers import create_project, create_watchlist, create_workspace


def test_content_version_exact_get_projects_persisted_source_availability(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Content provenance workspace")
    project = create_project(client, principal_id, workspace["id"])
    source = _github_source(client, principal_id, workspace["id"], activate=True)
    watchlist = create_watchlist(
        client,
        principal_id,
        workspace["id"],
        project["id"],
        str(source["id"]),
        active=True,
    )
    captured_at = datetime.now(UTC) - timedelta(hours=2)
    checked_at = captured_at + timedelta(minutes=5)
    published_at = captured_at - timedelta(hours=1)
    duplicate_cluster_id = str(uuid4())
    independence_group_id = str(uuid4())
    with get_session_factory()() as db:
        run = CollectionRun(
            workspace_id=workspace["id"],
            watchlist_id=watchlist["id"],
            source_connection_id=str(source["id"]),
            stable_key=f"content-provenance:{uuid4()}",
            state="succeeded",
            cadence="daily",
            timezone="UTC",
            scheduled_for=captured_at,
            input_window_json={
                "start": (captured_at - timedelta(days=1)).isoformat(),
                "end": captured_at.isoformat(),
            },
            counters_json={"fetched": 1, "created": 1},
            freshness_json={
                "state": "current",
                "last_success_at": captured_at.isoformat(),
                "signal_candidate_count": 1,
                "signal_count": 0,
            },
            partial_success=False,
            started_at=captured_at,
            finished_at=captured_at,
            data_authenticity="collected",
        )
        db.add(run)
        db.flush()
        raw = RawContentItem(
            workspace_id=workspace["id"],
            collection_run_id=run.id,
            source_connection_id=str(source["id"]),
            source_external_id="issue-availability",
            raw_snapshot_uri="s3://private-bucket/raw/issue-availability.json",
            raw_digest="sha256:raw-availability",
            received_at=captured_at,
            data_authenticity="collected",
        )
        item = ContentItem(
            workspace_id=workspace["id"],
            source_connection_id=str(source["id"]),
            source_item_id="issue-availability",
            canonical_url="https://example.test/issues/availability",
            identity_key="github:glint:issue-availability",
            title="Availability marker",
            duplicate_cluster_id=duplicate_cluster_id,
            independence_group_id=independence_group_id,
            data_authenticity="collected",
        )
        db.add_all([raw, item])
        db.flush()
        version = ContentVersion(
            workspace_id=workspace["id"],
            content_item_id=item.id,
            source_connection_id=str(source["id"]),
            raw_content_item_id=raw.id,
            version_number=1,
            content_digest="sha256:normalized-availability",
            normalized_title="Availability marker",
            normalized_body="The normalized body remains readable after source deletion.",
            metadata_json={
                "published_at": published_at.isoformat(),
                "author": "Ada",
                "credential": "must-never-reach-wire",
                "raw_metadata": {"access_token": "must-never-reach-wire"},
            },
            captured_at=captured_at,
            raw_snapshot_uri=raw.raw_snapshot_uri,
            parser_version="github-v1",
            availability="captured",
            availability_last_checked_at=checked_at,
            data_authenticity="collected",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        version_id = version.id
        db.commit()

    captured = client.get(
        f"/v1/content-versions/{version_id}",
        headers=query_headers(principal_id, workspace["id"]),
    )
    assert captured.status_code == 200, captured.text
    payload = captured.json()
    assert payload["availability"] == "captured"
    assert payload["availability_last_checked_at"] == checked_at.isoformat().replace("+00:00", "Z")
    assert payload["published_at"] == published_at.isoformat().replace("+00:00", "Z")
    assert payload["source_connection_id"] == source["id"]
    assert payload["source_name"] == source["name"]
    assert payload["source_kind"] == "cloud"
    assert payload["identity_key"] == "github:glint:issue-availability"
    assert payload["duplicate_cluster_id"] == duplicate_cluster_id
    assert payload["independence_group_id"] == independence_group_id
    assert "credential" not in payload["metadata_json"]
    assert "raw_metadata" not in payload["metadata_json"]
    assert "raw_snapshot_uri" not in payload

    deleted_at = datetime.now(UTC)
    with get_session_factory()() as db:
        stored = db.get(ContentVersion, version_id)
        assert stored is not None
        stored.availability = "deleted"
        stored.availability_last_checked_at = deleted_at
        stored.availability_reason = "origin_returned_404"
        db.commit()
    deleted = client.get(
        f"/v1/content-versions/{version_id}",
        headers=query_headers(principal_id, workspace["id"]),
    )
    assert deleted.status_code == 200, deleted.text
    deleted_payload = deleted.json()
    assert deleted_payload["id"] == version_id
    assert deleted_payload["availability"] == "deleted"
    assert deleted_payload["availability_reason"] == "origin_returned_404"
    assert deleted_payload["normalized_body"] == payload["normalized_body"]


def test_content_version_exact_get_is_workspace_scoped(
    client: TestClient, principal_id: str
) -> None:
    first = create_workspace(client, principal_id, "First provenance workspace")
    second = create_workspace(client, principal_id, "Second provenance workspace")
    response = client.get(
        f"/v1/content-versions/{uuid4()}",
        headers=command_headers(principal_id, second["id"]),
    )
    assert response.status_code == 404
    assert first["id"] != second["id"]
