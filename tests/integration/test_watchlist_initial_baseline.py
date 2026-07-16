from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.api.app.db.models import (
    CollectionRun,
    ContentItem,
    ContentVersion,
    ImportManifest,
    ImportSession,
    RawContentItem,
    Signal,
)
from services.api.app.db.session import get_session_factory
from services.api.app.modules.sources.service import ImportFinalizationRepository
from tests.conftest import query_headers
from tests.integration.test_cloud_sources_and_schedules import _github_source
from tests.security.helpers import create_project, create_watchlist, create_workspace


def _content_version(
    db: Session,
    *,
    workspace_id: str,
    source_id: str,
    run_id: str,
    ordinal: int,
) -> ContentVersion:
    now = datetime.now(UTC)
    raw = RawContentItem(
        workspace_id=workspace_id,
        collection_run_id=run_id,
        source_connection_id=source_id,
        source_external_id=f"baseline-{ordinal}",
        raw_snapshot_uri=f"s3://glint/raw/baseline-{ordinal}.json",
        raw_digest=f"sha256:raw-baseline-{ordinal}",
        received_at=now,
        data_authenticity="collected",
    )
    item = ContentItem(
        workspace_id=workspace_id,
        source_connection_id=source_id,
        source_item_id=f"baseline-{ordinal}",
        identity_key=f"baseline:{ordinal}",
        title=f"Baseline {ordinal}",
        data_authenticity="collected",
    )
    db.add_all([raw, item])
    db.flush()
    version = ContentVersion(
        workspace_id=workspace_id,
        content_item_id=item.id,
        source_connection_id=source_id,
        raw_content_item_id=raw.id,
        version_number=1,
        content_digest=f"sha256:baseline-{ordinal}",
        normalized_title=f"Baseline {ordinal}",
        normalized_body="Baseline content for deterministic monitoring.",
        metadata_json={},
        captured_at=now,
        raw_snapshot_uri=raw.raw_snapshot_uri,
        parser_version="github-v1",
        availability="captured",
        availability_last_checked_at=now,
        data_authenticity="collected",
    )
    db.add(version)
    db.flush()
    item.current_version_id = version.id
    return version


def test_watchlist_initial_baseline_uses_terminal_runs_and_blocks_early_signal(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Initial baseline workspace")
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
    initial = client.get("/v1/watchlists", headers=query_headers(principal_id, workspace["id"]))
    assert initial.status_code == 200, initial.text
    initial_projection = initial.json()["items"][0]["initial_baseline"]
    assert initial_projection["status"] == "collecting"
    assert initial_projection["current_count"] == 0
    assert initial_projection["required_count"] == 2
    assert initial_projection["reason"]

    now = datetime.now(UTC)
    with get_session_factory()() as db:
        run = CollectionRun(
            workspace_id=workspace["id"],
            watchlist_id=watchlist["id"],
            source_connection_id=str(source["id"]),
            stable_key=f"baseline:{uuid4()}",
            state="succeeded",
            cadence="daily",
            timezone="UTC",
            scheduled_for=now,
            input_window_json={
                "start": (now - timedelta(days=1)).isoformat(),
                "end": now.isoformat(),
            },
            counters_json={"fetched": 1, "created": 1},
            freshness_json={
                "state": "current",
                "last_success_at": now.isoformat(),
                "signal_candidate_count": 7,
                "signal_count": 0,
            },
            partial_success=False,
            started_at=now,
            finished_at=now,
            data_authenticity="collected",
        )
        db.add(run)
        db.flush()
        first_version = _content_version(
            db,
            workspace_id=workspace["id"],
            source_id=str(source["id"]),
            run_id=run.id,
            ordinal=1,
        )
        ImportFinalizationRepository._create_signals(
            db,
            ImportSession(
                workspace_id=workspace["id"],
                source_connection_id=str(source["id"]),
                created_by=principal_id,
                data_authenticity="collected",
            ),
            ImportManifest(id=str(uuid4())),
            [first_version],
        )
        assert db.scalar(select(func.count(Signal.id))) == 0
        first_run_id = run.id
        db.commit()

    insufficient = client.get(
        "/v1/watchlists", headers=query_headers(principal_id, workspace["id"])
    )
    assert insufficient.status_code == 200, insufficient.text
    projection = insufficient.json()["items"][0]["initial_baseline"]
    assert projection["status"] == "insufficient"
    assert projection["current_count"] == 1
    assert projection["required_count"] == 2
    assert projection["reason"]

    runs = client.get("/v1/collection-runs", headers=query_headers(principal_id, workspace["id"]))
    assert runs.status_code == 200, runs.text
    first_run = next(item for item in runs.json()["items"] if item["id"] == first_run_id)
    assert first_run["counters"]["signal_candidate_count"] == 7
    assert first_run["counters"]["signal_count"] == 0

    with get_session_factory()() as db:
        latest_run = db.scalar(
            select(CollectionRun)
            .where(CollectionRun.watchlist_id == watchlist["id"])
            .order_by(CollectionRun.created_at.desc())
        )
        assert latest_run is not None
        _content_version(
            db,
            workspace_id=workspace["id"],
            source_id=str(source["id"]),
            run_id=latest_run.id,
            ordinal=2,
        )
        db.commit()
    ready = client.get("/v1/watchlists", headers=query_headers(principal_id, workspace["id"]))
    assert ready.status_code == 200, ready.text
    ready_projection = ready.json()["items"][0]["initial_baseline"]
    assert ready_projection["status"] == "ready"
    assert ready_projection["current_count"] == 2
