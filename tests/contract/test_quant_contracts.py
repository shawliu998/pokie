from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.contracts.quant import (
    UNKNOWN_EVENT_SAFE_SUMMARY,
    QuantDatasetImportRequest,
    QuantRunEvent,
    QuantRunEventPayload,
    QuantStreamResetEvent,
    UnknownQuantRunEvent,
    assert_quant_enum_compatibility,
    decode_quant_event,
    encode_quant_sse,
    safe_event_copy,
)


def test_quant_dataset_import_requires_an_iana_time_zone() -> None:
    payload = {
        "name": "SPY daily",
        "symbol": "SPY",
        "csv_text": "date,open,high,low,close\n2024-01-02,1,1,1,1\n",
        "market_calendar": "XNYS",
        "time_zone": "America/New_York",
    }
    assert QuantDatasetImportRequest.model_validate(payload).time_zone == "America/New_York"
    with pytest.raises(ValidationError, match="valid IANA"):
        QuantDatasetImportRequest.model_validate({**payload, "time_zone": "Mars/Olympus"})


def test_quant_run_event_payload_is_closed_and_safe() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        QuantRunEventPayload.model_validate({"access_token": "nope"})
    payload = QuantRunEventPayload.model_validate(
        {"state": "running_experiments", "plan_revision": 1, "safe_summary": "Plan approved."}
    )
    assert payload.model_dump(mode="json", exclude_none=True) == {
        "state": "running_experiments",
        "plan_revision": 1,
        "safe_summary": "Plan approved.",
    }
    assert_quant_enum_compatibility()


def test_quant_run_event_wire_and_sse_encoding() -> None:
    event = QuantRunEvent.model_validate(
        {
            "run_id": UUID("55555555-5555-5555-8555-555555555555"),
            "sequence": 7,
            "event_id": UUID("66666666-6666-5666-8666-666666666666"),
            "event_type": "run.completed",
            "payload": {"state": "completed", "safe_summary": "Run completed."},
            "trace_id": "trace-1",
            "timestamp": datetime(2026, 7, 17, 9, 0, tzinfo=UTC),
        }
    )
    wire = event.to_wire_dict()
    assert wire["event_type"] == "run.completed"
    assert wire["run_id"] == "55555555-5555-5555-8555-555555555555"
    assert encode_quant_sse(event).startswith("id: 66666666-6666-5666-8666-666666666666\n")


def test_quant_unknown_event_is_safely_parsed() -> None:
    parsed = decode_quant_event(
        {
            "run_id": UUID("55555555-5555-5555-8555-555555555555"),
            "sequence": 99,
            "event_id": UUID("77777777-7777-5777-8777-777777777777"),
            "event_type": "run.mutated_by_future_version",
            "payload": {"unexpected": "value"},
            "trace_id": "trace-future",
            "timestamp": datetime(2026, 7, 17, 9, 0, tzinfo=UTC),
        }
    )
    assert isinstance(parsed, UnknownQuantRunEvent)
    assert parsed.known is False
    assert parsed.safe_summary == UNKNOWN_EVENT_SAFE_SUMMARY
    assert safe_event_copy("run.mutated_by_future_version") == UNKNOWN_EVENT_SAFE_SUMMARY


def test_quant_stream_reset_requires_quant_snapshot_route() -> None:
    reset = QuantStreamResetEvent(
        snapshot_url="/v1/quant/runs/55555555-5555-5555-8555-555555555555",
        latest_sequence=3,
    )
    assert reset.model_dump(mode="json")["snapshot_url"].startswith("/v1/quant/runs/")
