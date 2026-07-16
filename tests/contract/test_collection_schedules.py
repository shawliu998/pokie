from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.contracts import enums
from packages.contracts.schemas import (
    CollectionScheduleCreateRequest,
    CollectionScheduleResponse,
    CollectionScheduleUpdateRequest,
)

WORKSPACE_ID = UUID("11111111-1111-5111-8111-111111111111")
SOURCE_ID = UUID("22222222-2222-5222-8222-222222222222")
WATCHLIST_ID = UUID("33333333-3333-5333-8333-333333333333")
SCHEDULE_ID = UUID("44444444-4444-5444-8444-444444444444")


def create_payload() -> dict[str, object]:
    return {
        "workspace_id": str(WORKSPACE_ID),
        "source_connection_id": str(SOURCE_ID),
        "watchlist_id": str(WATCHLIST_ID),
        "query_json": {"query": "permissions"},
        "cadence_seconds": 3600,
        "timezone": "UTC",
        "misfire_policy": "run_once",
        "catch_up": False,
        "overlap_policy": "skip",
        "next_run_at": "2026-07-15T06:00:00Z",
        "enabled": True,
    }


def test_schedule_policy_enums_are_closed() -> None:
    assert {member.value for member in enums.MisfirePolicy} == {"skip", "run_once"}
    assert {member.value for member in enums.OverlapPolicy} == {"skip", "queue_one"}


def test_schedule_create_is_strict_and_timezone_aware() -> None:
    schedule = CollectionScheduleCreateRequest.model_validate(create_payload())
    assert schedule.workspace_id == WORKSPACE_ID
    assert schedule.timezone == "UTC"

    invalid = create_payload() | {"timezone": "Not/A-Timezone"}
    with pytest.raises(ValidationError, match="IANA time zone"):
        CollectionScheduleCreateRequest.model_validate(invalid)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CollectionScheduleCreateRequest.model_validate(
            create_payload() | {"lease_owner_token": "must-not-pass"}
        )


def test_schedule_update_requires_version_and_a_real_change() -> None:
    with pytest.raises(ValidationError, match="at least one field"):
        CollectionScheduleUpdateRequest(expected_row_version=2)
    with pytest.raises(ValidationError, match="at least one field"):
        CollectionScheduleUpdateRequest(expected_row_version=2, enabled=None)

    update = CollectionScheduleUpdateRequest(expected_row_version=2, enabled=False)
    assert update.enabled is False


def test_management_response_exposes_only_safe_lease_projection() -> None:
    now = datetime(2026, 7, 15, 6, tzinfo=UTC)
    response = CollectionScheduleResponse.model_validate(
        {
            "id": SCHEDULE_ID,
            "workspace_id": WORKSPACE_ID,
            "source_connection_id": SOURCE_ID,
            "watchlist_id": WATCHLIST_ID,
            "query_json": {"query": "permissions"},
            "cadence_seconds": 3600,
            "timezone": "UTC",
            "misfire_policy": "skip",
            "catch_up": False,
            "overlap_policy": "skip",
            "next_run_at": now,
            "enabled": True,
            "row_version": 2,
            "lease_held": True,
            "lease_expires_at": now,
            "heartbeat_at": now,
            "created_at": now,
            "updated_at": now,
            "data_authenticity": "human_authored",
        }
    )
    payload = response.model_dump(mode="json")
    assert payload["lease_held"] is True
    assert "lease_owner_token" not in payload

    with pytest.raises(ValidationError, match="held lease"):
        CollectionScheduleResponse.model_validate(payload | {"lease_expires_at": None})
