from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.db.models import (
    AuditLog,
    ContentItem,
    ContentVersion,
    RawContentItem,
    SourceConnection,
)
from services.api.app.db.session import get_session_factory
from services.api.app.modules.common import digest
from tests.conftest import query_headers
from tests.security.helpers import create_workspace


def test_content_item_version_history_is_ordered_exact_and_workspace_scoped(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Content replay workspace")
    workspace_id = str(workspace["id"])
    now = datetime.now(UTC)
    with get_session_factory()() as db:
        source = SourceConnection(
            workspace_id=workspace_id,
            name="Replay source",
            source_kind="cloud",
            runtime="cloud",
            connector_type="github",
            connector_version="github-v1",
            status="healthy",
            data_scope="workspace_confidential",
            approved_by=principal_id,
            data_authenticity="collected",
        )
        db.add(source)
        db.flush()
        raw = RawContentItem(
            workspace_id=workspace_id,
            collection_run_id=str(uuid4()),
            source_connection_id=source.id,
            source_external_id="github:issue:replay",
            raw_snapshot_uri="s3://glint/raw/replay.json",
            raw_digest=digest(b"raw replay"),
            received_at=now,
            data_authenticity="collected",
        )
        item = ContentItem(
            workspace_id=workspace_id,
            source_connection_id=source.id,
            source_item_id="github:issue:replay",
            canonical_url="https://github.com/openai/glint/issues/1",
            identity_key="github:openai/glint:issue:replay",
            title="Replay content",
            data_authenticity="collected",
        )
        db.add_all([raw, item])
        db.flush()
        first = ContentVersion(
            workspace_id=workspace_id,
            content_item_id=item.id,
            source_connection_id=source.id,
            raw_content_item_id=raw.id,
            version_number=1,
            content_digest=digest(b"content v1"),
            normalized_title="Replay content v1",
            normalized_body="First immutable body.",
            metadata_json={},
            captured_at=now - timedelta(hours=1),
            raw_snapshot_uri=raw.raw_snapshot_uri,
            parser_version="github-v1",
            availability="deleted",
            availability_last_checked_at=now - timedelta(minutes=30),
            availability_reason="Upstream issue was deleted after capture.",
            data_authenticity="collected",
        )
        second = ContentVersion(
            workspace_id=workspace_id,
            content_item_id=item.id,
            source_connection_id=source.id,
            raw_content_item_id=raw.id,
            version_number=2,
            content_digest=digest(b"content v2"),
            normalized_title="Replay content v2",
            normalized_body="Second immutable body.",
            metadata_json={},
            captured_at=now,
            raw_snapshot_uri=raw.raw_snapshot_uri,
            parser_version="github-v1",
            availability="captured",
            availability_last_checked_at=now,
            data_authenticity="collected",
        )
        db.add_all([first, second])
        db.flush()
        item.current_version_id = second.id
        additional_items = [
            ContentItem(
                workspace_id=workspace_id,
                source_connection_id=source.id,
                source_item_id=f"github:issue:replay:{index}",
                canonical_url=f"https://github.com/openai/glint/issues/{index + 1}",
                identity_key=f"github:openai/glint:issue:replay:{index}",
                title=f"Replay content {index}",
                current_version_id=second.id,
                data_authenticity="collected",
            )
            for index in range(2, 4)
        ]
        db.add_all(additional_items)
        db.commit()
        item_id = item.id
        first_id = first.id
        second_id = second.id
        expected_item_ids = {item.id, *(row.id for row in additional_items)}

    first_history_page = client.get(
        f"/v1/content-items/{item_id}/versions",
        headers=query_headers(principal_id, workspace_id),
        params={"limit": 1},
    )
    assert first_history_page.status_code == 200, first_history_page.text
    assert first_history_page.json()["page"] == {
        "next_cursor": first_id,
        "has_more": True,
    }
    second_history_page = client.get(
        f"/v1/content-items/{item_id}/versions",
        headers=query_headers(principal_id, workspace_id),
        params={"limit": 1, "cursor": first_history_page.json()["page"]["next_cursor"]},
    )
    assert second_history_page.status_code == 200, second_history_page.text
    assert second_history_page.json()["page"] == {"next_cursor": None, "has_more": False}
    history = [
        *first_history_page.json()["items"],
        *second_history_page.json()["items"],
    ]
    assert [row["id"] for row in history] == [first_id, second_id]
    assert [row["version_number"] for row in history] == [1, 2]
    assert history[0]["availability"] == "deleted"
    assert history[0]["availability_reason"] == "Upstream issue was deleted after capture."
    assert history[1]["availability"] == "captured"

    first_item_page = client.get(
        "/v1/content-items",
        headers=query_headers(principal_id, workspace_id),
        params={"limit": 2},
    )
    assert first_item_page.status_code == 200, first_item_page.text
    assert first_item_page.json()["page"]["has_more"] is True
    second_item_page = client.get(
        "/v1/content-items",
        headers=query_headers(principal_id, workspace_id),
        params={
            "limit": 2,
            "cursor": first_item_page.json()["page"]["next_cursor"],
        },
    )
    assert second_item_page.status_code == 200, second_item_page.text
    assert second_item_page.json()["page"] == {"next_cursor": None, "has_more": False}
    paged_item_ids = [
        row["id"]
        for row in [
            *first_item_page.json()["items"],
            *second_item_page.json()["items"],
        ]
    ]
    assert len(paged_item_ids) == len(set(paged_item_ids)) == 3
    assert set(paged_item_ids) == expected_item_ids

    other_workspace = create_workspace(client, principal_id, "Other content workspace")
    other_workspace_id = str(other_workspace["id"])
    with get_session_factory()() as db:
        other_item = ContentItem(
            workspace_id=other_workspace_id,
            source_connection_id=str(uuid4()),
            source_item_id="other-workspace-item",
            identity_key="other-workspace-item",
            title="Other workspace cursor",
            current_version_id=str(uuid4()),
            data_authenticity="collected",
        )
        db.add(other_item)
        db.flush()
        other_version = ContentVersion(
            workspace_id=other_workspace_id,
            content_item_id=other_item.id,
            source_connection_id=other_item.source_connection_id,
            raw_content_item_id=str(uuid4()),
            version_number=1,
            content_digest=digest(b"other workspace content"),
            normalized_title="Other workspace cursor",
            normalized_body="Must not become a cursor in another workspace.",
            metadata_json={},
            captured_at=now,
            raw_snapshot_uri="s3://glint/raw/other-workspace.json",
            parser_version="github-v1",
            availability="captured",
            availability_last_checked_at=now,
            data_authenticity="collected",
        )
        db.add(other_version)
        db.commit()
        other_item_id = other_item.id
        other_version_id = other_version.id
    scoped = client.get(
        f"/v1/content-items/{item_id}/versions",
        headers=query_headers(principal_id, other_workspace_id),
    )
    assert scoped.status_code == 404
    cross_workspace_item_cursor = client.get(
        "/v1/content-items",
        headers=query_headers(principal_id, workspace_id),
        params={"cursor": other_item_id},
    )
    assert cross_workspace_item_cursor.status_code == 404
    cross_workspace_version_cursor = client.get(
        f"/v1/content-items/{item_id}/versions",
        headers=query_headers(principal_id, workspace_id),
        params={"cursor": other_version_id},
    )
    assert cross_workspace_version_cursor.status_code == 404


def test_audit_log_cursor_filters_and_redacted_public_projection(
    client: TestClient, principal_id: str
) -> None:
    workspace = create_workspace(client, principal_id, "Audit replay workspace")
    workspace_id = str(workspace["id"])
    target_id = str(uuid4())
    now = datetime.now(UTC)
    secret = "Bearer ghp_abcdefghijklmnopqrstuvwxyz123456"
    local_path = "/Users/private/customer/export.csv"
    with get_session_factory()() as db:
        rows = [
            AuditLog(
                workspace_id=workspace_id,
                actor_id=principal_id,
                action="decision_brief.replayed",
                target_type="DecisionBriefVersion",
                target_id=target_id,
                before_digest=None,
                after_digest=digest({"sequence": index}),
                reason=f"Diagnostic {secret} from {local_path}",
                request_id=str(uuid4()),
                details_json={"secret": secret, "local_path": local_path},
                occurred_at=now - timedelta(minutes=index),
                data_authenticity="human_authored",
            )
            for index in range(3)
        ]
        other = AuditLog(
            workspace_id=str(uuid4()),
            actor_id=principal_id,
            action="decision_brief.replayed",
            target_type="DecisionBriefVersion",
            target_id=target_id,
            request_id=str(uuid4()),
            details_json={},
            occurred_at=now + timedelta(minutes=1),
            data_authenticity="human_authored",
        )
        db.add_all([*rows, other])
        db.commit()

    headers = query_headers(principal_id, workspace_id)
    first_page = client.get(
        "/v1/audit-logs",
        headers=headers,
        params={"action": "decision_brief.replayed", "limit": 2},
    )
    assert first_page.status_code == 200, first_page.text
    first_payload = first_page.json()
    assert len(first_payload["items"]) == 2
    assert first_payload["page"]["has_more"] is True
    assert first_payload["page"]["next_cursor"] == first_payload["items"][-1]["id"]
    serialized = first_page.text
    assert secret not in serialized
    assert local_path not in serialized
    assert "details_json" not in serialized
    assert "[REDACTED_SECRET]" in serialized
    assert "[REDACTED_PATH]" in serialized

    second_page = client.get(
        "/v1/audit-logs",
        headers=headers,
        params={
            "action": "decision_brief.replayed",
            "limit": 2,
            "cursor": first_payload["page"]["next_cursor"],
        },
    )
    assert second_page.status_code == 200, second_page.text
    assert len(second_page.json()["items"]) == 1
    assert second_page.json()["page"] == {"next_cursor": None, "has_more": False}

    object_filter = client.get(
        "/v1/audit-logs",
        headers=headers,
        params={
            "target_type": "DecisionBriefVersion",
            "target_id": target_id,
            "occurred_after": (now - timedelta(seconds=30)).isoformat(),
            "occurred_before": (now + timedelta(seconds=30)).isoformat(),
        },
    )
    assert object_filter.status_code == 200, object_filter.text
    assert len(object_filter.json()["items"]) == 1
    assert object_filter.json()["items"][0]["target_id"] == target_id
