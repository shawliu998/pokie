from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.contracts.events import (
    RUN_EVENT_PERSISTENCE_TO_WIRE,
    RunEvent,
    RunEventPayload,
    StreamResetEvent,
    encode_heartbeat,
    encode_sse,
)

RUN_ID = UUID("55555555-5555-5555-8555-555555555555")
INVESTIGATION_ID = UUID("dddddddd-dddd-5ddd-8ddd-dddddddddddd")
EVENT_ID = UUID("6eb2e2b4-0000-5000-8000-000000000001")
CLAIM_ID = UUID("77777777-7777-5777-8777-777777777777")
CLAIM_VERSION_ID = UUID("88888888-8888-5888-8888-888888888888")


def claim_event() -> RunEvent:
    return RunEvent.model_validate(
        {
            "investigation_id": INVESTIGATION_ID,
            "research_run_id": RUN_ID,
            "sequence": 14,
            "event_id": EVENT_ID,
            "type": "claim.version_proposed",
            "payload_json": {
                "claim_id": CLAIM_ID,
                "claim_version_id": CLAIM_VERSION_ID,
            },
            "trace_id": "trace-safe-1",
            "occurred_at": datetime(2026, 7, 15, 5, 10, tzinfo=UTC),
        }
    )


def test_persistence_to_wire_mapping_is_the_only_alias_mapping() -> None:
    assert dict(RUN_EVENT_PERSISTENCE_TO_WIRE) == {
        "research_run_id": "run_id",
        "type": "event_type",
        "payload_json": "payload",
        "occurred_at": "timestamp",
        "event_id": "event_id",
        "sequence": "sequence",
        "trace_id": "trace_id",
    }
    assert claim_event().to_wire_dict() == {
        "event_id": str(EVENT_ID),
        "run_id": str(RUN_ID),
        "sequence": 14,
        "timestamp": "2026-07-15T05:10:00Z",
        "event_type": "claim.version_proposed",
        "trace_id": "trace-safe-1",
        "data_authenticity": "generated",
        "payload": {
            "claim_id": str(CLAIM_ID),
            "claim_version_id": str(CLAIM_VERSION_ID),
        },
    }


def test_serialization_schema_uses_wire_names_only() -> None:
    properties = RunEvent.model_json_schema(mode="serialization", by_alias=True)["properties"]
    assert {"run_id", "event_type", "payload", "timestamp"}.issubset(properties)
    assert {
        "research_run_id",
        "type",
        "payload_json",
        "occurred_at",
        "investigation_id",
    }.isdisjoint(properties)


def test_sse_encoder_uses_event_id_type_and_exact_wire_data() -> None:
    frame = encode_sse(claim_event())
    lines = frame.rstrip("\n").splitlines()
    assert lines[0] == f"id: {EVENT_ID}"
    assert lines[1] == "event: claim.version_proposed"
    assert lines[2].startswith("data: ")
    assert json.loads(lines[2].removeprefix("data: ")) == claim_event().to_wire_dict()
    assert frame.endswith("\n\n")


def test_event_payload_is_closed_and_secret_free() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RunEventPayload.model_validate({"access_token": "must-not-pass"})
    with pytest.raises(ValidationError):
        RunEventPayload.model_validate({"status": "needs_review"})


@pytest.mark.parametrize(
    "state",
    ["queued", "running", "waiting_for_input", "completed", "failed", "cancelled"],
)
def test_event_payload_state_is_exactly_research_run_state(state: str) -> None:
    payload = RunEventPayload.model_validate({"state": state})
    assert payload.model_dump(mode="json", exclude_none=True) == {"state": state}


def test_stream_reset_has_no_business_id_or_sequence() -> None:
    reset = StreamResetEvent(
        snapshot_url=f"/v1/research-runs/{RUN_ID}",
        latest_sequence=14,
    )
    assert reset.model_dump(mode="json") == {
        "event_type": "stream.reset",
        "snapshot_url": f"/v1/research-runs/{RUN_ID}",
        "latest_sequence": 14,
        "data_authenticity": "generated",
    }
    frame = encode_sse(reset)
    assert frame.startswith("event: stream.reset\n")
    assert "id:" not in frame
    assert '"sequence"' not in frame


def test_heartbeat_is_a_comment_not_an_event() -> None:
    assert encode_heartbeat() == ": heartbeat\n\n"
