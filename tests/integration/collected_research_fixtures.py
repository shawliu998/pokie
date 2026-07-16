from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.db.models import (
    CollectionRun,
    ContentItem,
    ContentVersion,
    RawContentItem,
    Signal,
    SignalEvidence,
    SourceConnection,
)
from services.api.app.db.session import get_session_factory
from tests.integration.test_cloud_sources_and_schedules import _github_source
from tests.security.helpers import create_project, create_watchlist, create_workspace


def seed_collected_signal_scope(client: TestClient, principal_id: str) -> dict[str, Any]:
    workspace = create_workspace(client, principal_id, "Collected research workspace")
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
    now = datetime.now(UTC)
    independence_group_id = str(uuid4())
    with get_session_factory()() as db:
        source_row = db.get(SourceConnection, str(source["id"]))
        assert source_row is not None
        source_row.status = "healthy"
        source_row.health_state = "healthy"
        source_row.last_success_at = now
        source_row.freshness_state = "current"
        collection_run = CollectionRun(
            workspace_id=workspace["id"],
            watchlist_id=watchlist["id"],
            source_connection_id=source_row.id,
            stable_key=f"collected-research:{uuid4()}",
            state="succeeded",
            cadence="daily",
            timezone="UTC",
            scheduled_for=now,
            input_window_json={
                "current_start": (now - timedelta(days=7)).isoformat(),
                "current_end": now.isoformat(),
            },
            counters_json={"fetched": 1, "created": 1, "updated": 0, "skipped": 0, "failed": 0},
            partial_success=False,
            freshness_json={"state": "current", "last_success_at": now.isoformat()},
            started_at=now - timedelta(seconds=2),
            finished_at=now,
            data_authenticity="collected",
        )
        db.add(collection_run)
        db.flush()
        raw = RawContentItem(
            workspace_id=workspace["id"],
            collection_run_id=collection_run.id,
            source_connection_id=source_row.id,
            source_external_id="github:issue:42",
            raw_snapshot_uri="s3://glint/raw/github-issue-42.json",
            raw_digest="sha256:collected-raw-42",
            received_at=now,
            data_authenticity="collected",
        )
        item = ContentItem(
            workspace_id=workspace["id"],
            source_connection_id=source_row.id,
            source_item_id="github:issue:42",
            canonical_url="https://github.com/openai/glint/issues/42",
            identity_key="github:openai/glint:issue:42",
            title="Permission friction",
            duplicate_cluster_id=str(uuid4()),
            independence_group_id=independence_group_id,
            data_authenticity="collected",
        )
        db.add_all([raw, item])
        db.flush()
        version = ContentVersion(
            workspace_id=workspace["id"],
            content_item_id=item.id,
            source_connection_id=source_row.id,
            raw_content_item_id=raw.id,
            version_number=1,
            content_digest="sha256:collected-content-42",
            normalized_title="Permission friction",
            normalized_body="Permission requests block enterprise onboarding.",
            metadata_json={"author": "same-origin-author"},
            captured_at=now,
            raw_snapshot_uri=raw.raw_snapshot_uri,
            parser_version="github-v1",
            data_authenticity="collected",
        )
        db.add(version)
        db.flush()
        item.current_version_id = version.id
        signal = Signal(
            workspace_id=workspace["id"],
            watchlist_id=watchlist["id"],
            title="Permission friction increased",
            detector_version="deterministic-signal-v2",
            status="new",
            window_json={
                "current_start": (now - timedelta(days=7)).isoformat(),
                "current_end": now.isoformat(),
                "baseline_start": (now - timedelta(days=35)).isoformat(),
                "baseline_end": (now - timedelta(days=7)).isoformat(),
            },
            metrics_json={"mention_count": 1, "independent_source_count": 1},
            dimensions_json={"detector_policy": {"min_independent_sources": 1}},
            explanation="Origin-independent collected evidence crossed the configured threshold.",
            data_authenticity="collected",
        )
        db.add(signal)
        db.flush()
        signal_evidence = SignalEvidence(
            workspace_id=workspace["id"],
            signal_id=signal.id,
            content_version_id=version.id,
            role="trigger",
            independence_group_id=independence_group_id,
            contribution=1.0,
            added_by="worker",
            data_authenticity="collected",
        )
        db.add(signal_evidence)
        db.commit()
        return {
            "workspace": workspace,
            "project": project,
            "source": source,
            "watchlist": watchlist,
            "signal_id": signal.id,
            "signal_evidence_id": signal_evidence.id,
            "content_version_id": version.id,
            "raw_content_item_id": raw.id,
            "collection_run_id": collection_run.id,
            "independence_group_id": independence_group_id,
            "now": now,
        }
