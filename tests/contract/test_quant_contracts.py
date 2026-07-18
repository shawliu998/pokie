from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from packages.contracts.quant import (
    UNKNOWN_EVENT_SAFE_SUMMARY,
    QuantDatasetImportRequest,
    QuantDatasetSourceMetadata,
    QuantNasdaqEquityFetchRequest,
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


def test_quant_dataset_import_accepts_a_24x7_market_calendar() -> None:
    request = QuantDatasetImportRequest.model_validate(
        {
            "name": "Crypto daily bars",
            "symbol": "BTC-USD",
            "csv_text": "date,open,high,low,close\\n2024-01-01,1,1,1,1\\n",
            "market_calendar": "24x7",
            "time_zone": "UTC",
        }
    )
    assert request.market_calendar == "24x7"


def test_provider_source_requires_complete_provider_retrieval_attestation() -> None:
    payload = {
        "kind": "provider_fetch",
        "source_name": "Binance Spot public market data",
        "provider_id": "binance_spot",
        "provider_response_digest": "sha256:provider-response",
        "retrieved_at": "2026-07-18T02:00:00Z",
        "requested_limit": 365,
        "returned_bar_count": 364,
        "dropped_incomplete_count": 1,
        "normalization_note": "Rounded base-asset volume to whole units.",
        "attestation_status": "provider_retrieved",
        "market_calendar": "24x7",
        "time_zone": "UTC",
        "price_adjustment": "unadjusted",
    }
    metadata = QuantDatasetSourceMetadata.model_validate(payload)
    assert metadata.provider_id == "binance_spot"

    with pytest.raises(ValidationError, match="provider attestation fields"):
        QuantDatasetSourceMetadata.model_validate(
            {**payload, "provider_response_digest": None}
        )
    with pytest.raises(ValidationError, match="declared attestation status"):
        QuantDatasetSourceMetadata.model_validate(
            {"kind": "csv_upload", "attestation_status": "provider_retrieved"}
        )


def test_nasdaq_request_and_partial_corporate_action_evidence_are_explicit() -> None:
    assert QuantNasdaqEquityFetchRequest().model_dump() == {
        "name": None,
        "symbol": "AAPL",
        "lookback_days": 730,
    }
    metadata = QuantDatasetSourceMetadata.model_validate(
        {
            "kind": "provider_fetch",
            "source_name": "Nasdaq historical quotes",
            "provider_id": "nasdaq_equity",
            "provider_response_digest": "sha256:history",
            "provider_response_attestations": [
                {
                    "kind": "daily_bars",
                    "digest": "sha256:history",
                    "source_reference": "nasdaq:AAPL:historical",
                },
                {
                    "kind": "instrument_info",
                    "digest": "sha256:info",
                    "source_reference": "nasdaq:AAPL:info",
                },
                {
                    "kind": "dividends",
                    "digest": "sha256:dividends",
                    "source_reference": "nasdaq:AAPL:dividends",
                },
            ],
            "corporate_actions_attestation": {
                "dividends_status": "retrieved_unverified",
                "splits_status": "unavailable",
                "coverage_start": "1988-11-21",
                "coverage_end": "2026-05-11",
                "dividend_event_count": 82,
                "split_event_count": None,
                "note": "Dividend response retrieved; split response unavailable.",
            },
            "price_adjustment_verification_status": "not_applicable",
            "retrieved_at": "2026-07-18T02:00:00Z",
            "requested_limit": 5000,
            "returned_bar_count": 502,
            "dropped_incomplete_count": 0,
            "normalization_note": "Provider prices retained as unadjusted.",
            "attestation_status": "provider_retrieved",
            "market_calendar": "XNAS",
            "time_zone": "America/New_York",
            "price_adjustment": "unadjusted",
        }
    )
    assert metadata.corporate_actions_attestation is not None
    assert metadata.corporate_actions_attestation.splits_status == "unavailable"

    with pytest.raises(ValidationError, match="verified split evidence"):
        QuantDatasetSourceMetadata.model_validate(
            {
                **metadata.model_dump(mode="json"),
                "price_adjustment": "split_adjusted",
                "price_adjustment_verification_status": "verified",
            }
        )


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
