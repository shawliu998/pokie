from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from services.api.app.db.models import AuditLog
from services.api.app.db.session import get_session_factory
from tests.conftest import command_headers, query_headers
from tests.integration.collected_research_fixtures import seed_collected_signal_scope


def test_signal_monitor_dismiss_filter_and_same_session_undo(
    client: TestClient, principal_id: str
) -> None:
    fixture = seed_collected_signal_scope(client, principal_id)
    workspace_id = str(fixture["workspace"]["id"])
    signal_id = str(fixture["signal_id"])
    signal = client.get(
        f"/v1/signals/{signal_id}", headers=query_headers(principal_id, workspace_id)
    ).json()
    session_id = str(uuid4())
    cooldown_until = datetime.now(UTC) + timedelta(days=2)
    monitored = client.post(
        f"/v1/signals/{signal_id}/transitions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "action": "monitor",
            "expected_row_version": signal["row_version"],
            "session_id": session_id,
            "cooldown_until": cooldown_until.isoformat(),
        },
    )
    assert monitored.status_code == 200, monitored.text
    monitoring = monitored.json()
    assert monitoring["status"] == "monitoring"
    assert monitoring["disposition"]["monitoring_snapshot"]["metrics"]
    assert monitoring["disposition"]["cooldown_until"]

    invalid_reason = client.post(
        f"/v1/signals/{signal_id}/transitions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "action": "dismiss",
            "expected_row_version": monitoring["row_version"],
            "session_id": session_id,
            "dismiss_reason": "made_up_reason",
            "note": "Not a contract reason.",
        },
    )
    assert invalid_reason.status_code == 422

    dismissed = client.post(
        f"/v1/signals/{signal_id}/transitions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "action": "dismiss",
            "expected_row_version": monitoring["row_version"],
            "session_id": session_id,
            "dismiss_reason": "known_issue",
            "note": "Already tracked by the platform reliability owner.",
        },
    )
    assert dismissed.status_code == 200, dismissed.text
    dismissed_signal = dismissed.json()
    assert dismissed_signal["status"] == "dismissed"
    default_inbox = client.get(
        "/v1/signals", headers=query_headers(principal_id, workspace_id)
    ).json()["items"]
    assert all(item["id"] != signal_id for item in default_inbox)
    full_inbox = client.get(
        "/v1/signals?include_dismissed=true",
        headers=query_headers(principal_id, workspace_id),
    ).json()["items"]
    assert any(item["id"] == signal_id for item in full_inbox)

    wrong_session = client.post(
        f"/v1/signals/{signal_id}/transitions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "action": "undo",
            "expected_row_version": dismissed_signal["row_version"],
            "session_id": str(uuid4()),
        },
    )
    assert wrong_session.status_code == 409
    undone = client.post(
        f"/v1/signals/{signal_id}/transitions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "action": "undo",
            "expected_row_version": dismissed_signal["row_version"],
            "session_id": session_id,
        },
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["status"] == "monitoring"


def test_signal_cooldown_break_requires_reason_and_is_audited(
    client: TestClient, principal_id: str
) -> None:
    fixture = seed_collected_signal_scope(client, principal_id)
    workspace_id = str(fixture["workspace"]["id"])
    signal_id = str(fixture["signal_id"])
    signal = client.get(
        f"/v1/signals/{signal_id}", headers=query_headers(principal_id, workspace_id)
    ).json()
    triaged_response = client.post(
        f"/v1/signals/{signal_id}/triage",
        headers=command_headers(principal_id, workspace_id),
        json={
            "expected_signal_row_version": signal["row_version"],
            "business_impact": {
                "confirmed_level": "medium",
                "reason": "Owner confirmed product impact.",
                "expected_assessment_version": 0,
            },
            "urgency": {
                "confirmed_level": "monitor",
                "reason": "No immediate deadline.",
                "expected_assessment_version": 0,
            },
        },
    )
    assert triaged_response.status_code == 200, triaged_response.text
    triaged = triaged_response.json()
    session_id = str(uuid4())
    monitored = client.post(
        f"/v1/signals/{signal_id}/transitions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "action": "monitor",
            "expected_row_version": triaged["row_version"],
            "session_id": session_id,
            "cooldown_until": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
            "note": "Wait for independent coverage.",
        },
    ).json()
    blocked = client.post(
        f"/v1/signals/{signal_id}/transitions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "action": "investigate",
            "expected_row_version": monitored["row_version"],
            "session_id": session_id,
        },
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "COOLDOWN_BREAK_REASON_REQUIRED"
    broken = client.post(
        f"/v1/signals/{signal_id}/transitions",
        headers=command_headers(principal_id, workspace_id),
        json={
            "action": "investigate",
            "expected_row_version": monitored["row_version"],
            "session_id": session_id,
            "note": "A newly independent source crossed the threshold.",
        },
    )
    assert broken.status_code == 200, broken.text
    assert broken.json()["status"] == "investigating"
    assert broken.json()["disposition"]["cooldown_broken_at"]
    assert broken.json()["disposition"]["cooldown_break_reason"]
    with get_session_factory()() as db:
        audits = db.query(AuditLog).filter(AuditLog.target_id == signal_id).all()
        assert any(row.action == "signal.cooldown_broken" for row in audits)
