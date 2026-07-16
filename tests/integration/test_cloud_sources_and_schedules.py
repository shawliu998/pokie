from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from services.api.app.core.errors import ApiError
from services.api.app.db.models import (
    CollectionRun,
    CollectionSchedule,
    ContentItem,
    ContentVersion,
    RawContentItem,
    Signal,
    SignalEvidence,
    SourceConnection,
    Watchlist,
)
from services.api.app.db.session import get_session_factory
from services.api.app.modules.sources.schedules import CollectionScheduleRepository
from tests.conftest import command_headers, query_headers
from tests.security.helpers import create_project, create_watchlist, create_workspace


def _github_source(
    client: TestClient, principal_id: str, workspace_id: str, *, activate: bool
) -> dict[str, object]:
    response = client.post(
        "/v1/sources",
        headers=command_headers(principal_id, workspace_id),
        json={
            "name": "Approved GitHub repository",
            "source_kind": "cloud",
            "runtime": "cloud",
            "connector_type": "github",
            "connector_version": "github-v1",
            "data_scope": "workspace_confidential",
            "credential_ref": "vault://github/product-feedback",
            "cadence": "daily",
            "timezone": "UTC",
            "source_config": {
                "connector_type": "github",
                "repositories": [
                    {
                        "owner": "openai",
                        "repository": "glint",
                        "include_issues": True,
                        "include_discussions": False,
                        "include_releases": True,
                    }
                ],
            },
        },
    )
    assert response.status_code == 201, response.text
    source = response.json()
    assert "credential_ref" not in source
    assert source["freshness"] == {"last_success_at": None, "state": "never"}
    assert source["health"]["state"] == "unknown"
    if not activate:
        return source
    activated = client.post(
        f"/v1/sources/{source['id']}/activate",
        headers=command_headers(principal_id, workspace_id),
        json={"expected_row_version": source["row_version"], "reason": "Owner approved"},
    )
    assert activated.status_code == 200, activated.text
    return activated.json()


def _schedule_payload(
    *, workspace_id: str, source_id: str, watchlist_id: str, repo: str = "glint"
) -> dict[str, object]:
    return {
        "workspace_id": workspace_id,
        "source_connection_id": source_id,
        "watchlist_id": watchlist_id,
        "query_json": {
            "owner": "openai",
            "repo": repo,
            "query": "permission friction",
            "max_pages": 2,
        },
        "cadence_seconds": 3600,
        "timezone": "UTC",
        "misfire_policy": "run_once",
        "catch_up": False,
        "overlap_policy": "skip",
        "next_run_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        "enabled": True,
    }


def test_cloud_source_response_and_schedule_are_approved_and_scope_bound(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Cloud source workspace")
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
    payload = _schedule_payload(
        workspace_id=workspace["id"],
        source_id=str(source["id"]),
        watchlist_id=watchlist["id"],
    )
    created = client.post(
        "/v1/collection-schedules",
        headers=command_headers(principal_id, workspace["id"]),
        json=payload,
    )
    assert created.status_code == 201, created.text
    schedule = created.json()
    assert schedule["query_json"]["repo"] == "glint"
    assert schedule["query_json"]["include_discussions"] is False
    assert schedule["lease_held"] is False

    unauthorized = dict(schedule["query_json"], repo="another-repository")
    update = client.patch(
        f"/v1/collection-schedules/{schedule['id']}",
        headers=command_headers(principal_id, workspace["id"]),
        json={"query_json": unauthorized, "expected_row_version": schedule["row_version"]},
    )
    assert update.status_code == 403
    assert update.json()["error"]["code"] == "SOURCE_SCOPE_BLOCKED"

    disabled = client.post(
        f"/v1/sources/{source['id']}/disable",
        headers=command_headers(principal_id, workspace["id"]),
        json={"expected_row_version": source["row_version"], "reason": "Owner disabled source"},
    )
    assert disabled.status_code == 200, disabled.text
    schedules = client.get(
        "/v1/collection-schedules", headers=query_headers(principal_id, workspace["id"])
    ).json()["items"]
    assert len(schedules) == 1
    assert schedules[0]["enabled"] is False
    assert schedules[0]["lease_held"] is False
    rejected_reenable = client.patch(
        f"/v1/collection-schedules/{schedule['id']}",
        headers=command_headers(principal_id, workspace["id"]),
        json={"enabled": True, "expected_row_version": schedules[0]["row_version"]},
    )
    assert rejected_reenable.status_code == 403


def test_schedule_rejects_unactivated_source_and_inactive_watchlist(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Schedule policy workspace")
    project = create_project(client, principal_id, workspace["id"])
    draft_source = _github_source(client, principal_id, workspace["id"], activate=False)
    active_watchlist = create_watchlist(
        client,
        principal_id,
        workspace["id"],
        project["id"],
        str(draft_source["id"]),
        active=True,
    )
    response = client.post(
        "/v1/collection-schedules",
        headers=command_headers(principal_id, workspace["id"]),
        json=_schedule_payload(
            workspace_id=workspace["id"],
            source_id=str(draft_source["id"]),
            watchlist_id=active_watchlist["id"],
        ),
    )
    assert response.status_code == 403

    activated = client.post(
        f"/v1/sources/{draft_source['id']}/activate",
        headers=command_headers(principal_id, workspace["id"]),
        json={
            "expected_row_version": draft_source["row_version"],
            "reason": "Activate for second policy check",
        },
    ).json()
    inactive_watchlist = create_watchlist(
        client,
        principal_id,
        workspace["id"],
        project["id"],
        str(draft_source["id"]),
        active=False,
    )
    response = client.post(
        "/v1/collection-schedules",
        headers=command_headers(principal_id, workspace["id"]),
        json=_schedule_payload(
            workspace_id=workspace["id"],
            source_id=activated["id"],
            watchlist_id=inactive_watchlist["id"],
        ),
    )
    assert response.status_code == 409


def test_schedule_create_and_update_require_watchlist_source_membership(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Schedule membership workspace")
    project = create_project(client, principal_id, workspace["id"])
    approved_source = _github_source(client, principal_id, workspace["id"], activate=True)
    unapproved_source = _github_source(client, principal_id, workspace["id"], activate=True)
    watchlist = create_watchlist(
        client,
        principal_id,
        workspace["id"],
        project["id"],
        str(approved_source["id"]),
        active=True,
    )
    unauthorized = client.post(
        "/v1/collection-schedules",
        headers=command_headers(principal_id, workspace["id"]),
        json=_schedule_payload(
            workspace_id=workspace["id"],
            source_id=str(unapproved_source["id"]),
            watchlist_id=watchlist["id"],
        ),
    )
    assert unauthorized.status_code == 403
    assert unauthorized.json()["error"]["code"] == "SOURCE_SCOPE_BLOCKED"

    created = client.post(
        "/v1/collection-schedules",
        headers=command_headers(principal_id, workspace["id"]),
        json=_schedule_payload(
            workspace_id=workspace["id"],
            source_id=str(approved_source["id"]),
            watchlist_id=watchlist["id"],
        ),
    )
    assert created.status_code == 201, created.text
    schedule = created.json()
    with get_session_factory()() as db:
        watchlist_row = db.get(Watchlist, watchlist["id"])
        assert watchlist_row is not None
        rules = dict(watchlist_row.rules_json)
        rules["source_connection_ids"] = [str(unapproved_source["id"])]
        watchlist_row.rules_json = rules
        db.commit()
    rejected_update = client.patch(
        f"/v1/collection-schedules/{schedule['id']}",
        headers=command_headers(principal_id, workspace["id"]),
        json={"enabled": False, "expected_row_version": schedule["row_version"]},
    )
    assert rejected_update.status_code == 403
    assert rejected_update.json()["error"]["code"] == "SOURCE_SCOPE_BLOCKED"


def test_watchlist_source_patch_is_scope_bound_and_persists_for_scheduling(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Watchlist patch workspace")
    project = create_project(client, principal_id, workspace["id"])
    original_source = _github_source(client, principal_id, workspace["id"], activate=True)
    replacement_source = _github_source(client, principal_id, workspace["id"], activate=True)
    foreign_workspace = create_workspace(client, principal_id, "Foreign source workspace")
    foreign_source = _github_source(client, principal_id, foreign_workspace["id"], activate=True)
    watchlist = create_watchlist(
        client,
        principal_id,
        workspace["id"],
        project["id"],
        str(original_source["id"]),
        active=True,
    )

    rejected = client.patch(
        f"/v1/watchlists/{watchlist['id']}",
        headers=command_headers(principal_id, workspace["id"]),
        json={
            "source_connection_ids": [foreign_source["id"]],
            "expected_row_version": watchlist["row_version"],
        },
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "SOURCE_SCOPE_BLOCKED"

    unchanged_items = client.get(
        "/v1/watchlists", headers=query_headers(principal_id, workspace["id"])
    ).json()["items"]
    unchanged = next(item for item in unchanged_items if item["id"] == watchlist["id"])
    assert unchanged["source_connection_ids"] == [original_source["id"]]

    updated_response = client.patch(
        f"/v1/watchlists/{watchlist['id']}",
        headers=command_headers(principal_id, workspace["id"]),
        json={
            "source_connection_ids": [replacement_source["id"]],
            "expected_row_version": watchlist["row_version"],
        },
    )
    assert updated_response.status_code == 200, updated_response.text
    updated = updated_response.json()
    assert updated["source_connection_ids"] == [replacement_source["id"]]

    persisted_items = client.get(
        "/v1/watchlists", headers=query_headers(principal_id, workspace["id"])
    ).json()["items"]
    persisted = next(item for item in persisted_items if item["id"] == watchlist["id"])
    assert persisted["source_connection_ids"] == [replacement_source["id"]]

    scheduled = client.post(
        "/v1/collection-schedules",
        headers=command_headers(principal_id, workspace["id"]),
        json=_schedule_payload(
            workspace_id=workspace["id"],
            source_id=str(replacement_source["id"]),
            watchlist_id=watchlist["id"],
        ),
    )
    assert scheduled.status_code == 201, scheduled.text


def test_collected_signal_response_uses_frozen_evidence_and_collection_freshness(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Collected signal workspace")
    project = create_project(client, principal_id, workspace["id"])
    source = _github_source(client, principal_id, workspace["id"], activate=True)
    second_source = _github_source(client, principal_id, workspace["id"], activate=True)
    watchlist = create_watchlist(
        client,
        principal_id,
        workspace["id"],
        project["id"],
        str(source["id"]),
        active=True,
    )
    now = datetime.now(UTC)
    with get_session_factory()() as db:
        source_ids = [str(source["id"]), str(second_source["id"])]
        source_rows = [db.get(SourceConnection, source_id) for source_id in source_ids]
        assert all(source_row is not None for source_row in source_rows)
        first_success = now
        second_success = now - timedelta(days=2)
        for source_row, state, last_success in zip(
            source_rows,
            ("current", "stale"),
            (first_success, second_success),
            strict=True,
        ):
            assert source_row is not None
            source_row.last_success_at = last_success
            source_row.freshness_state = state
        watchlist_row = db.get(Watchlist, watchlist["id"])
        assert watchlist_row is not None
        rules = dict(watchlist_row.rules_json)
        rules["source_connection_ids"] = source_ids
        watchlist_row.rules_json = rules
        runs: list[CollectionRun] = []
        for source_id, state, last_success in zip(
            source_ids,
            ("current", "stale"),
            (first_success, second_success),
            strict=True,
        ):
            run = CollectionRun(
                workspace_id=workspace["id"],
                watchlist_id=watchlist["id"],
                source_connection_id=source_id,
                stable_key=f"collected:{uuid4()}",
                state="succeeded" if state == "current" else "partial_success",
                cadence="daily",
                timezone="UTC",
                scheduled_for=now,
                input_window_json={
                    "current_start": (now - timedelta(days=7)).isoformat(),
                    "current_end": now.isoformat(),
                    "schedule_lease_token": "must-never-reach-wire",
                    "connector_config": {"credential": "must-never-reach-wire"},
                },
                counters_json={
                    "fetched": 1,
                    "created": 1,
                    "updated": 0,
                    "skipped": 0,
                    "failed": 0,
                    "internal_retry_token": "must-never-reach-wire",
                },
                partial_success=state == "stale",
                freshness_json={
                    "state": state,
                    "last_success_at": last_success.isoformat(),
                    "lease_owner_token": "must-never-reach-wire",
                },
                started_at=now,
                finished_at=now,
                data_authenticity="collected",
            )
            db.add(run)
            db.flush()
            runs.append(run)
        versions: list[ContentVersion] = []
        for index in range(2):
            source_id = source_ids[index]
            raw = RawContentItem(
                workspace_id=workspace["id"],
                collection_run_id=runs[index].id,
                source_connection_id=source_id,
                source_external_id=f"issue-{index}",
                raw_snapshot_uri=f"s3://glint/raw/issue-{index}.json",
                raw_digest=f"sha256:raw-{index}",
                received_at=now,
                data_authenticity="collected",
            )
            item = ContentItem(
                workspace_id=workspace["id"],
                source_connection_id=source_id,
                source_item_id=f"issue-{index}",
                identity_key=f"github:openai/glint:{index}",
                title=f"Issue {index}",
                data_authenticity="collected",
            )
            db.add_all([raw, item])
            db.flush()
            version = ContentVersion(
                workspace_id=workspace["id"],
                content_item_id=item.id,
                source_connection_id=source_id,
                raw_content_item_id=raw.id,
                version_number=1,
                content_digest=f"sha256:normalized-{index}",
                normalized_title=f"Issue {index}",
                normalized_body="Permission friction increased.",
                captured_at=now,
                raw_snapshot_uri=raw.raw_snapshot_uri,
                parser_version="github-v1",
                data_authenticity="collected",
            )
            db.add(version)
            db.flush()
            item.current_version_id = version.id
            versions.append(version)
        signal = Signal(
            workspace_id=workspace["id"],
            watchlist_id=watchlist["id"],
            title="Permission friction increased",
            detector_version="signal-v1",
            window_json={
                "current_start": (now - timedelta(days=7)).isoformat(),
                "current_end": now.isoformat(),
                "baseline_start": (now - timedelta(days=35)).isoformat(),
                "baseline_end": (now - timedelta(days=7)).isoformat(),
            },
            metrics_json={
                "mention_count": 2,
                "independent_source_count": 2,
                "growth_ratio": 2.0,
                "robust_z": 1.2,
                "duplicate_concentration": 0.5,
                "captured_time_fallback_count": 1,
            },
            dimensions_json={
                "detection_confidence": {
                    "level": "medium",
                    "calibration_status": "uncalibrated",
                    "explanation": "Two independent collected items crossed the threshold.",
                },
                "business_impact": {
                    "suggested_level": "medium",
                    "suggested_explanation": "Matches active Watchlist terms.",
                    "suggestion_origin": "deterministic_rule",
                    "suggestion_version": "impact-rules-v1",
                    "confirmed_level": None,
                    "confirmed_by": None,
                    "confirmed_at": None,
                },
                "urgency": {
                    "suggested_level": "monitor",
                    "suggested_explanation": "No immediate deadline.",
                    "suggestion_origin": "deterministic_rule",
                    "suggestion_version": "urgency-rules-v1",
                    "confirmed_level": None,
                    "confirmed_by": None,
                    "confirmed_at": None,
                },
                "priority": {
                    "level": None,
                    "status": "pending_confirmation",
                    "policy_version": "priority-matrix-v1",
                    "explanation": "Requires human confirmation.",
                },
                "detector_policy": {
                    "require_current_mentions": True,
                    "min_independent_sources": 1,
                    "max_duplicate_concentration": 0.8,
                    "min_growth_ratio": 1.75,
                    "min_robust_z": 1.1,
                },
                "limitations": ["event_time_missing_used_capture_time"],
            },
            explanation="Deterministic collection threshold was crossed.",
            data_authenticity="collected",
        )
        db.add(signal)
        db.flush()
        for version in versions:
            db.add(
                SignalEvidence(
                    workspace_id=workspace["id"],
                    signal_id=signal.id,
                    content_version_id=version.id,
                    role="trigger",
                    contribution=1.0,
                    added_by="worker",
                    data_authenticity="collected",
                )
            )
        signal_id = signal.id
        db.commit()

    response = client.get(
        f"/v1/signals/{signal_id}", headers=query_headers(principal_id, workspace["id"])
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data_authenticity"] == "collected"
    assert payload["total_source_count"] == 2
    assert payload["independent_source_count"] == 2
    assert payload["metrics"] == {
        "current_count": 2,
        "baseline_count": 0,
        "mention_count": 2,
        "independent_source_count": 2,
        "platform_count": 1,
        "growth_ratio": 2.0,
        "robust_z": 1.2,
    }
    assert payload["limitations"] == ["event_time_missing_used_capture_time"]
    assert payload["trigger_rules"] == [
        "detector_version = signal-v1",
        "mention_count > 0",
        "independent_source_count >= 1",
        "duplicate_concentration < 0.8",
        "growth_ratio >= 1.75 OR robust_z >= 1.1",
    ]
    freshness = payload["per_source_freshness"]
    assert len(freshness) == 2
    freshness_by_source = {item["source_connection_id"]: item for item in freshness}
    assert freshness_by_source[source["id"]]["state"] == "current"
    assert datetime.fromisoformat(freshness_by_source[source["id"]]["last_success_at"]) == now
    assert freshness_by_source[second_source["id"]]["state"] == "stale"
    assert (
        datetime.fromisoformat(freshness_by_source[second_source["id"]]["last_success_at"])
        == second_success
    )
    collection_response = client.get(
        "/v1/collection-runs", headers=query_headers(principal_id, workspace["id"])
    )
    assert collection_response.status_code == 200, collection_response.text
    assert "must-never-reach-wire" not in collection_response.text
    for public_run in collection_response.json()["items"]:
        assert set(public_run["input_window"]) == {"start", "end"}
        assert set(public_run["counters"]) == {
            "fetched",
            "created",
            "updated",
            "skipped",
            "failed",
            "signal_candidate_count",
            "signal_count",
        }
        assert set(public_run["freshness"]) == {"state", "last_success_at"}


def test_schedule_claim_is_workspace_scoped_and_stale_workers_are_fenced(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Schedule lease workspace")
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
    payload = _schedule_payload(
        workspace_id=workspace["id"],
        source_id=str(source["id"]),
        watchlist_id=watchlist["id"],
    )
    payload["next_run_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    created = client.post(
        "/v1/collection-schedules",
        headers=command_headers(principal_id, workspace["id"]),
        json=payload,
    )
    assert created.status_code == 201, created.text
    schedule_id = created.json()["id"]

    with get_session_factory()() as first_db:
        first = CollectionScheduleRepository.claim_due(
            first_db,
            workspace_id=workspace["id"],
            owner_token="worker-one-secret",
            lease_seconds=120,
        )
        assert first is not None
        assert first.id == schedule_id
        assert first.lease_attempt == 1
        assert first.lease_fencing_version == 1
    with get_session_factory()() as competing_db:
        assert (
            CollectionScheduleRepository.claim_due(
                competing_db,
                workspace_id=workspace["id"],
                owner_token="worker-two-secret",
                lease_seconds=120,
            )
            is None
        )
        assert (
            CollectionScheduleRepository.claim_due(
                competing_db,
                workspace_id=str(uuid4()),
                owner_token="system-worker-cross-scope",
                lease_seconds=120,
            )
            is None
        )

    with get_session_factory()() as db:
        row = db.get(CollectionSchedule, schedule_id)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with get_session_factory()() as second_db:
        second = CollectionScheduleRepository.claim_due(
            second_db,
            workspace_id=workspace["id"],
            owner_token="worker-two-secret",
            lease_seconds=120,
        )
        assert second is not None
        assert second.lease_attempt == 2
        assert second.lease_fencing_version == 2
    with get_session_factory()() as stale_db, pytest.raises(ApiError) as stale:
        CollectionScheduleRepository.release(
            stale_db,
            schedule_id=schedule_id,
            owner_token="worker-one-secret",
            next_run_at=datetime.now(UTC) + timedelta(hours=1),
            expected_attempt=1,
            expected_fencing_version=1,
        )
    assert stale.value.code == "JOB_LEASE_EXPIRED"
    with get_session_factory()() as wrong_attempt_db, pytest.raises(ApiError):
        CollectionScheduleRepository.release(
            wrong_attempt_db,
            schedule_id=schedule_id,
            owner_token="worker-two-secret",
            next_run_at=datetime.now(UTC) + timedelta(hours=1),
            expected_attempt=1,
            expected_fencing_version=2,
        )
    with get_session_factory()() as release_db:
        CollectionScheduleRepository.release(
            release_db,
            schedule_id=schedule_id,
            owner_token="worker-two-secret",
            next_run_at=datetime.now(UTC) + timedelta(hours=1),
            expected_attempt=2,
            expected_fencing_version=2,
        )
