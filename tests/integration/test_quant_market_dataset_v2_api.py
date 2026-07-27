from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.contracts.quant import (
    QuantBarInterval,
    QuantMarketCalendar,
    QuantRunMode,
    QuantRunState,
    parse_market_ohlcv_csv,
)
from packages.contracts.quant.schemas import QuantMarketDatasetV2PreviewResponse
from services.api.app.api import routes_quant
from services.api.app.core.errors import ApiError
from services.api.app.modules.quant.binance_market_data_v2 import (
    BinanceMarketBarsResult,
    BinanceMarketBatchEvidence,
    BinanceMarketBatchTerminationReason,
    BinanceMarketCadenceQuality,
)
from services.api.app.modules.quant.store import QuantStore


def _headers(principal_id: str, workspace_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {principal_id}",
        "Idempotency-Key": str(uuid4()),
    }
    if workspace_id is not None:
        headers["X-Workspace-ID"] = workspace_id
    return headers


def _workspace(client: TestClient, principal_id: str, name: str) -> dict[str, Any]:
    response = client.post(
        "/v1/workspaces",
        headers=_headers(principal_id),
        json={"name": name, "data_region": "local", "retention_policy_version": "retention-v1"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _market_csv(*timestamps: str) -> str:
    rows = ["timestamp,open,high,low,close,volume"]
    for index, timestamp in enumerate(timestamps):
        rows.append(
            f"{timestamp},{100 + index}.12345678,{102 + index}.12345678,"
            f"{99 + index}.12345678,{101 + index}.12345678,12.34567890"
        )
    return "\n".join(rows) + "\n"


def _generated_market_csv(interval: QuantBarInterval, count: int) -> str:
    step = {
        QuantBarInterval.HOUR: timedelta(hours=1),
        QuantBarInterval.FOUR_HOURS: timedelta(hours=4),
        QuantBarInterval.DAILY: timedelta(days=1),
    }[interval]
    timestamp = datetime(2024, 1, 1, tzinfo=UTC)
    rows = ["timestamp,open,high,low,close,volume"]
    for index in range(count):
        opening = Decimal("100") + Decimal(index % 17) / Decimal("10")
        close = opening + Decimal((index % 5) - 2) / Decimal("20")
        high = max(opening, close) + Decimal("0.25")
        low = min(opening, close) - Decimal("0.25")
        rows.append(
            f"{timestamp.isoformat().replace('+00:00', 'Z')},"
            f"{opening},{high},{low},{close},{Decimal('12.3456789') + index}"
        )
        timestamp += step
    return "\n".join(rows) + "\n"


def _generated_exchange_daily_csv(count: int) -> str:
    session = datetime(2024, 1, 2, tzinfo=UTC)
    rows = ["date,open,high,low,close,volume,amount"]
    while len(rows) <= count:
        session_date = session.date()
        if session.weekday() < 5 and session_date.isoformat() != "2024-02-12":
            index = len(rows) - 1
            opening = Decimal("100") + Decimal(index % 17) / Decimal("10")
            close = opening + Decimal((index % 5) - 2) / Decimal("20")
            high = max(opening, close) + Decimal("0.25")
            low = min(opening, close) - Decimal("0.25")
            rows.append(
                f"{session_date.isoformat()},{opening},{high},{low},{close},"
                f"{Decimal('12.3456789') + index},{Decimal('123456.78') + index}"
            )
        session += timedelta(days=1)
    return "\n".join(rows) + "\n"


CSV_CONTIGUOUS = _market_csv(
    "2024-01-02T00:00:00Z",
    "2024-01-02T01:00:00Z",
    "2024-01-02T02:00:00Z",
)
CSV_WITH_GAP = _market_csv(
    "2024-01-02T00:00:00Z",
    "2024-01-02T01:00:00Z",
    "2024-01-02T04:00:00Z",
    "2024-01-02T05:00:00Z",
)


def _import_csv(
    client: TestClient,
    principal_id: str,
    workspace_id: str,
    csv_text: str = CSV_CONTIGUOUS,
    *,
    interval: QuantBarInterval = QuantBarInterval.HOUR,
    market_calendar: QuantMarketCalendar = QuantMarketCalendar.CONTINUOUS,
    symbol: str = "btcusdt",
) -> dict[str, Any]:
    stem = f"btc-usdt-{interval.value}"
    response = client.post(
        "/v1/quant/datasets/v2/import-csv",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": f"BTC {interval.value} bars",
            "symbol": symbol,
            "interval": interval.value,
            "market_calendar": market_calendar.value,
            "csv_text": csv_text,
            "file_name": f"{stem}.csv",
            "source_name": "Research CSV",
            "source_reference": f"upload:{stem}-v2",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_v2_csv_persists_reloads_and_keeps_legacy_directory_separate(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "V2 persistence")["workspace_id"]
    imported = _import_csv(client, principal_id, workspace_id)

    assert imported["interval"] == "1h"
    assert imported["research_eligible"] is False
    assert imported["evidence"]["source_kind"] == "csv_upload"
    assert imported["evidence"]["file_name"] == "btc-usdt-1h.csv"
    assert imported["evidence"]["page_raw_sha256"] == []
    assert imported["evidence"]["retrieved_at_utc"] is None
    assert imported["evidence"]["batch_digest"] is None
    assert imported["record_digest"].startswith("sha256:")
    assert imported["quality"]["status"] == "accepted"
    legacy_datasets = client.get("/v1/quant/datasets", headers=_headers(principal_id, workspace_id))
    assert legacy_datasets.json() == []

    restored = QuantStore().get_market_dataset_v2(
        workspace_id=workspace_id, dataset_id=imported["dataset_id"]
    )
    assert restored.dataset.digest == imported["digest"]
    assert restored.evidence.model_dump(mode="json") == imported["evidence"]
    assert restored.quality.model_dump(mode="json") == imported["quality"]

    repeated = _import_csv(client, principal_id, workspace_id)
    assert repeated["dataset_id"] == imported["dataset_id"]
    assert (
        len(
            client.get("/v1/quant/datasets/v2", headers=_headers(principal_id, workspace_id)).json()
        )
        == 1
    )


def test_v2_restore_accepts_pre_d1_evidence_without_connector_fields(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "Pre-D1 v2 restore")["workspace_id"]
    imported = _import_csv(client, principal_id, workspace_id)
    store = QuantStore()
    store.get_market_dataset_v2(
        workspace_id=workspace_id,
        dataset_id=imported["dataset_id"],
    )
    legacy_state = json.loads(
        json.dumps(
            store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
        )
    )
    legacy_evidence = legacy_state["market_datasets_v2"][0]["evidence"]
    for field in (
        "connector_version",
        "source_request_digest",
        "terms_reference",
    ):
        legacy_evidence.pop(field)

    restored_store = QuantStore()
    restored_store._restore_workspace(  # pyright: ignore[reportPrivateUsage]
        workspace_id,
        legacy_state,
    )
    restored = restored_store.get_market_dataset_v2(
        workspace_id=workspace_id,
        dataset_id=imported["dataset_id"],
    )
    assert restored.record_digest == imported["record_digest"]
    assert restored.evidence.connector_version is None
    assert restored.evidence.source_request_digest is None
    assert restored.evidence.terms_reference is None


@pytest.mark.parametrize(
    ("interval", "count", "eligible"),
    [
        (QuantBarInterval.HOUR, 2189, False),
        (QuantBarInterval.HOUR, 2190, True),
        (QuantBarInterval.FOUR_HOURS, 547, False),
        (QuantBarInterval.FOUR_HOURS, 548, True),
        (QuantBarInterval.DAILY, 251, False),
        (QuantBarInterval.DAILY, 252, True),
    ],
)
def test_v2_response_marks_interval_aware_market_research_eligibility(
    client: TestClient,
    principal_id: str,
    interval: QuantBarInterval,
    count: int,
    eligible: bool,
) -> None:
    workspace_id = _workspace(client, principal_id, f"V2 eligibility {interval.value} {count}")[
        "workspace_id"
    ]
    imported = _import_csv(
        client,
        principal_id,
        workspace_id,
        _generated_market_csv(interval, count),
        interval=interval,
    )

    assert imported["interval"] == interval.value
    assert imported["bar_count"] == count
    assert imported["research_eligible"] is eligible


def test_v2_exchange_daily_import_restores_previews_and_enters_runtime(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "V2 XSHG daily")["workspace_id"]
    csv_text = _generated_exchange_daily_csv(252)
    imported = _import_csv(
        client,
        principal_id,
        workspace_id,
        csv_text,
        interval=QuantBarInterval.DAILY,
        market_calendar=QuantMarketCalendar.XSHG,
        symbol="000300.SH",
    )
    store = QuantStore()
    record = store.get_market_dataset_v2(
        workspace_id=workspace_id, dataset_id=imported["dataset_id"]
    )

    assert imported["research_eligible"] is True
    assert record.dataset.market_calendar is QuantMarketCalendar.XSHG
    assert record.dataset.market_session.value == "regular"
    assert record.dataset.time_zone == "Asia/Shanghai"
    assert record.dataset.periods_per_year == 252
    assert record.quality.status == "accepted"
    assert record.quality.cadence_gap_count == 0
    assert "holiday completeness is not inferred" in record.quality.normalization_note

    preview = store.market_dataset_v2_preview(
        workspace_id=workspace_id,
        dataset_id=record.id,
        max_points=240,
    )
    assert preview["returned_bar_count"] == 240
    assert (
        datetime.fromisoformat(preview["bars"][0]["timestamp"].replace("Z", "+00:00")).weekday() < 5
    )
    descriptor = store.validate_market_dataset_for_run(
        workspace_id=workspace_id,
        dataset_id=record.id,
        research_start_utc=record.dataset.covered_start,
        research_end_utc=record.dataset.covered_end,
    )
    assert len(descriptor.bars) == 252
    assert descriptor.periods_per_year == 252

    restored = QuantStore().get_market_dataset_v2(
        workspace_id=workspace_id,
        dataset_id=record.id,
    )
    assert restored.dataset.digest == record.dataset.digest
    assert restored.record_digest == record.record_digest


def test_v2_preview_returns_only_latest_contiguous_tail_and_is_workspace_scoped(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "V2 preview")["workspace_id"]
    imported = _import_csv(client, principal_id, workspace_id, CSV_WITH_GAP)
    preview = client.get(
        f"/v1/quant/datasets/v2/{imported['dataset_id']}/preview?max_points=10",
        headers=_headers(principal_id, workspace_id),
    )

    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["data_authenticity"] == "imported"
    assert body["data_authenticity"] == body["dataset"]["data_authenticity"]
    with pytest.raises(ValidationError, match="authenticity"):
        QuantMarketDatasetV2PreviewResponse.model_validate(
            {**body, "data_authenticity": "collected"}
        )
    assert body["dataset"]["quality"]["status"] == "blocked"
    assert body["total_bar_count"] == 4
    assert body["returned_bar_count"] == 2
    assert [bar["timestamp"] for bar in body["bars"]] == [
        "2024-01-02T04:00:00Z",
        "2024-01-02T05:00:00Z",
    ]

    other_workspace_id = _workspace(client, principal_id, "V2 other workspace")["workspace_id"]
    missing = client.get(
        f"/v1/quant/datasets/v2/{imported['dataset_id']}",
        headers=_headers(principal_id, other_workspace_id),
    )
    assert missing.status_code == 404
    assert (
        client.get(
            f"/v1/quant/datasets/v2/{imported['dataset_id']}/preview?max_points=0",
            headers=_headers(principal_id, workspace_id),
        ).status_code
        == 422
    )


def test_v2_persisted_schema_and_digest_tampering_fail_closed(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "V2 fail closed")["workspace_id"]
    imported = _import_csv(client, principal_id, workspace_id)
    reloaded_store = QuantStore()
    reloaded_store.get_market_dataset_v2(
        workspace_id=workspace_id, dataset_id=imported["dataset_id"]
    )
    state = reloaded_store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    tampered = json.loads(json.dumps(state))
    tampered["market_datasets_v2"][0]["dataset"]["digest"] = "sha256:tampered-digest"
    failed_restore = QuantStore()
    with pytest.raises(ValueError, match="digest"):
        failed_restore._restore_workspace(workspace_id, tampered)  # pyright: ignore[reportPrivateUsage]
    assert failed_restore._market_datasets_v2 == {}  # pyright: ignore[reportPrivateUsage]
    assert workspace_id not in failed_restore._loaded_workspaces  # pyright: ignore[reportPrivateUsage]

    unknown = json.loads(json.dumps(state))
    unknown["market_datasets_v2"][0]["dataset"]["schema_version"] = "unknown-v9"
    with pytest.raises(ValueError, match="Unsupported persisted"):
        QuantStore()._restore_workspace(workspace_id, unknown)  # pyright: ignore[reportPrivateUsage]
    evidence_tamper = json.loads(json.dumps(state))
    evidence_tamper["market_datasets_v2"][0]["evidence"]["normalizer_version"] = "other-v9"
    with pytest.raises(ValueError, match="record digest"):
        QuantStore()._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, evidence_tamper
        )
    filename_tamper = json.loads(json.dumps(state))
    filename_tamper["market_datasets_v2"][0]["evidence"]["file_name"] = "other.csv"
    with pytest.raises(ValueError, match="record digest"):
        QuantStore()._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, filename_tamper
        )
    authenticity_tamper = json.loads(json.dumps(state))
    authenticity_tamper["market_datasets_v2"][0]["data_authenticity"] = "collected"
    with pytest.raises(ValueError, match="authenticity"):
        QuantStore()._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, authenticity_tamper
        )
    assert imported["schema_version"] == "quant-market-bars-v2"


def test_v2_restore_is_atomic_and_rejects_duplicate_or_mismatched_market_records(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "V2 restore atom")["workspace_id"]
    imported = _import_csv(client, principal_id, workspace_id)
    store = QuantStore()
    store.get_market_dataset_v2(workspace_id=workspace_id, dataset_id=imported["dataset_id"])
    project = store.create_project(
        workspace_id=workspace_id,
        name="Atomic restore project",
        objective="Preserve every cached record on a failed restore.",
    )
    baseline_state = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    baseline_version = store._storage_versions[workspace_id]  # pyright: ignore[reportPrivateUsage]
    baseline_loaded = set(store._loaded_workspaces)  # pyright: ignore[reportPrivateUsage]

    malformed_legacy = json.loads(json.dumps(baseline_state))
    malformed_project = dict(malformed_legacy["projects"][0])
    malformed_project["id"] = f"{project.id}-bad"
    malformed_project["status"] = "not-a-status"
    malformed_legacy["projects"].append(malformed_project)
    with pytest.raises(ValueError):
        store._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, malformed_legacy
        )
    assert store._workspace_state(workspace_id) == baseline_state  # pyright: ignore[reportPrivateUsage]
    assert store._storage_versions[workspace_id] == baseline_version  # pyright: ignore[reportPrivateUsage]
    assert store._loaded_workspaces == baseline_loaded  # pyright: ignore[reportPrivateUsage]

    duplicate = json.loads(json.dumps(baseline_state))
    duplicate["market_datasets_v2"].append(dict(duplicate["market_datasets_v2"][0]))
    with pytest.raises(ValueError, match="duplicate identity"):
        store._restore_workspace(workspace_id, duplicate)  # pyright: ignore[reportPrivateUsage]
    assert store._workspace_state(workspace_id) == baseline_state  # pyright: ignore[reportPrivateUsage]

    mismatched_workspace = json.loads(json.dumps(baseline_state))
    mismatched_workspace["market_datasets_v2"][0]["workspace_id"] = "another-workspace"
    with pytest.raises(ValueError, match="does not belong"):
        store._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, mismatched_workspace
        )
    assert store._workspace_state(workspace_id) == baseline_state  # pyright: ignore[reportPrivateUsage]

    unknown_schema = json.loads(json.dumps(baseline_state))
    unknown_schema["market_datasets_v2"][0]["dataset"]["schema_version"] = "unknown-v9"
    with pytest.raises(ValueError, match="Unsupported persisted"):
        store._restore_workspace(workspace_id, unknown_schema)  # pyright: ignore[reportPrivateUsage]
    assert store._workspace_state(workspace_id) == baseline_state  # pyright: ignore[reportPrivateUsage]


def test_v2_dataset_is_rejected_by_the_daily_research_entrypoint(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "V2 run gate")["workspace_id"]
    imported = _import_csv(client, principal_id, workspace_id)
    project_response = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, workspace_id),
        json={"name": "No intraday run", "objective": "Keep C2B data preview-only."},
    )
    assert project_response.status_code == 201, project_response.text
    project = project_response.json()
    rejected = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, workspace_id),
        json={
            "project_id": project["id"],
            "question": "This must not start a v2 research run.",
            "mode": "plan",
            "expected_project_row_version": project["row_version"],
            "dataset_id": imported["dataset_id"],
            "research_start": "2024-01-02",
            "research_end": "2024-01-02",
        },
    )
    assert rejected.status_code == 409
    assert "/v1/quant/market-runs" in rejected.json()["error"]["message"]


def test_v2_research_gates_and_defensive_legacy_corrupt_retry_are_non_mutating(
    client: TestClient, principal_id: str
) -> None:
    workspace_id = _workspace(client, principal_id, "V2 all research gates")["workspace_id"]
    imported = _import_csv(client, principal_id, workspace_id)
    store = QuantStore()
    store.get_market_dataset_v2(workspace_id=workspace_id, dataset_id=imported["dataset_id"])

    before_command = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    command = client.post(
        "/v1/quant/workspace-snapshot/commands",
        headers=_headers(principal_id, workspace_id),
        json={
            "command": "start_auto_research",
            "expected_row_version": 1,
            "payload": {
                "goal": "This preview-only dataset must not create a run.",
                "dataset_id": imported["dataset_id"],
            },
        },
    )
    assert command.status_code == 409
    assert store._workspace_state(workspace_id) == before_command  # pyright: ignore[reportPrivateUsage]

    project = store.create_project(
        workspace_id=workspace_id,
        name="C2B gate project",
        objective="Keep stored v2 bars outside the research runtime.",
    )
    before_create = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ApiError, match="/v1/quant/market-runs"):
        store.create_run(
            workspace_id=workspace_id,
            project_id=project.id,
            question="Do not start a v2 run.",
            mode=QuantRunMode.PLAN,
            expected_project_row_version=project.row_version,
            dataset_id=imported["dataset_id"],
        )
    assert store._workspace_state(workspace_id) == before_create  # pyright: ignore[reportPrivateUsage]

    parent = store.create_run(
        workspace_id=workspace_id,
        project_id=project.id,
        question="A regular daily source run remains separate.",
        mode=QuantRunMode.PLAN,
        expected_project_row_version=project.row_version,
    )
    before_refine = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(ApiError, match="/v1/quant/market-runs"):
        store.create_run(
            workspace_id=workspace_id,
            project_id=project.id,
            question="A continuation cannot switch to an unenabled v2 dataset.",
            mode=QuantRunMode.PLAN,
            expected_project_row_version=store.get_project(
                workspace_id=workspace_id, project_id=project.id
            ).row_version,
            dataset_id=imported["dataset_id"],
            parent_run_id=parent.id,
            seed_candidate_id="not-used-after-c2b-gate",
            refinement_reason="Verify the dataset boundary before source validation.",
        )
    assert store._workspace_state(workspace_id) == before_refine  # pyright: ignore[reportPrivateUsage]

    # Defensive-only white-box case: public paths still cannot create a v2 run,
    # while C3B1 restore accepts only an internally pinned complete runtime record.
    # An incomplete legacy/corrupt row must not use retry idempotency as an escape.
    parent.state = QuantRunState.QUEUED
    parent.dataset_id = imported["dataset_id"]
    parent.retry_child_run_id = "missing-legacy-retry-child"
    before_retry = store._workspace_state(workspace_id)  # pyright: ignore[reportPrivateUsage]
    failed_restore = QuantStore()
    with pytest.raises(ValueError, match="complete runtime pin set"):
        failed_restore._restore_workspace(  # pyright: ignore[reportPrivateUsage]
            workspace_id, before_retry
        )
    with pytest.raises(ApiError, match="/v1/quant/market-runs"):
        store.retry_run(
            workspace_id=workspace_id,
            run_id=parent.id,
            expected_row_version=parent.row_version + 1,
            reason="A retry must retain the C2B dataset boundary.",
        )
    assert store._workspace_state(workspace_id) == before_retry  # pyright: ignore[reportPrivateUsage]

    other_workspace_id = _workspace(client, principal_id, "V2 guessed identifier")["workspace_id"]
    other_project = client.post(
        "/v1/quant/projects",
        headers=_headers(principal_id, other_workspace_id),
        json={"name": "Other project", "objective": "No cross-workspace lookup."},
    ).json()
    guessed = client.post(
        "/v1/quant/runs",
        headers=_headers(principal_id, other_workspace_id),
        json={
            "project_id": other_project["id"],
            "question": "A guessed v2 identifier must not disclose its owner.",
            "mode": "plan",
            "expected_project_row_version": other_project["row_version"],
            "dataset_id": imported["dataset_id"],
        },
    )
    assert guessed.status_code == 404
    assert "stored and previewable" not in guessed.text
    assert (
        client.get(
            f"/v1/quant/datasets/v2/{imported['dataset_id']}",
            headers=_headers(principal_id, other_workspace_id),
        ).status_code
        == 404
    )


def test_v2_binance_route_persists_fake_normalized_result_without_network(
    client: TestClient, principal_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = _workspace(client, principal_id, "V2 Binance fake")["workspace_id"]
    dataset = parse_market_ohlcv_csv(
        CSV_CONTIGUOUS, symbol="BTCUSDT", interval=QuantBarInterval.HOUR
    )
    provider_content = dataset.digest_payload() | {"provenance": "provider_fetch"}
    provider_dataset = dataset.__class__.model_validate(
        {
            **provider_content,
            "digest": dataset.__class__.digest_for(provider_content),
        }
    )
    fetched = BinanceMarketBarsResult(
        dataset=provider_dataset,
        evidence=BinanceMarketBatchEvidence(
            retrieved_at_utc=datetime(2025, 1, 1, tzinfo=UTC),
            source_reference="binance-vision:/api/v3/klines?symbol=BTCUSDT",
            requested_bar_count=3,
            returned_bar_count=3,
            retained_bar_count=3,
            closed_dropped_count=0,
            deduplicated_count=0,
            termination_reason=BinanceMarketBatchTerminationReason.REQUESTED_LIMIT,
            target_satisfied=True,
            page_raw_sha256=("sha256:abcdef1234567890",),
            batch_digest="sha256:abcdef1234567891",
        ),
        quality=BinanceMarketCadenceQuality(
            status="accepted", cadence_gap_count=0, normalization_note="No cadence gaps detected."
        ),
    )

    class _FakeBinanceV2Client:
        def fetch_market_bars(
            self, *, symbol: str, interval: QuantBarInterval, limit: int
        ) -> BinanceMarketBarsResult:
            assert (symbol, interval, limit) == ("BTCUSDT", QuantBarInterval.HOUR, 3)
            return fetched

    monkeypatch.setattr(routes_quant, "_binance_market_data_v2_client", _FakeBinanceV2Client)
    response = client.post(
        "/v1/quant/datasets/v2/fetch-binance",
        headers=_headers(principal_id, workspace_id),
        json={"symbol": "BTCUSDT", "interval": "1h", "limit": 3},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["data_authenticity"] == "collected"
    assert body["evidence"]["source_kind"] == "provider_fetch"
    assert body["evidence"]["file_name"] is None
    assert body["evidence"]["page_raw_sha256"] == ["sha256:abcdef1234567890"]
    assert "raw_payload" not in json.dumps(body).lower()


def test_v2_csv_request_size_and_interval_are_strictly_bounded() -> None:
    from pydantic import ValidationError

    from packages.contracts.quant import QuantMarketDatasetV2ImportRequest

    with pytest.raises(ValidationError):
        QuantMarketDatasetV2ImportRequest.model_validate(
            {
                "name": "too large",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "csv_text": "x" * 10_000_001,
            }
        )
    with pytest.raises(ValidationError):
        QuantMarketDatasetV2ImportRequest.model_validate(
            {
                "name": "bad interval",
                "symbol": "BTCUSDT",
                "interval": "15m",
                "csv_text": CSV_CONTIGUOUS,
            }
        )
    with pytest.raises(ValidationError):
        QuantMarketDatasetV2ImportRequest.model_validate(
            {
                "name": "bad file name",
                "symbol": "BTCUSDT",
                "interval": "1h",
                "csv_text": CSV_CONTIGUOUS,
                "file_name": "../btc.csv",
            }
        )
    with pytest.raises(ValidationError, match="supported explicit calendar"):
        QuantMarketDatasetV2ImportRequest.model_validate(
            {
                "name": "unknown calendar",
                "symbol": "BTCUSDT",
                "interval": "1D",
                "market_calendar": "unknown",
                "csv_text": CSV_CONTIGUOUS,
            }
        )
    with pytest.raises(ValidationError, match="supports only 1D"):
        QuantMarketDatasetV2ImportRequest.model_validate(
            {
                "name": "intraday exchange",
                "symbol": "000300.SH",
                "interval": "1h",
                "market_calendar": "XSHG",
                "csv_text": CSV_CONTIGUOUS,
            }
        )


def test_v2_persist_failure_does_not_leave_a_phantom_memory_record(
    client: TestClient, principal_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace_id = _workspace(client, principal_id, "V2 persistence rollback")["workspace_id"]
    store = QuantStore()

    def _persist_failure(_workspace_id: str) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "_persist_workspace", _persist_failure)

    with pytest.raises(RuntimeError, match="db down"):
        store.import_market_dataset_v2_csv(
            workspace_id=workspace_id,
            name="rollback bars",
            symbol="BTCUSDT",
            interval=QuantBarInterval.HOUR,
            csv_text=CSV_CONTIGUOUS,
            source_name="Rollback CSV",
            source_reference=None,
        )

    assert store._market_datasets_v2 == {}  # pyright: ignore[reportPrivateUsage]


def test_v2_static_routes_precede_dynamic_dataset_lookup() -> None:
    paths = [getattr(route, "path", "") for route in routes_quant.router.routes]
    base = "/v1/quant/datasets/v2"
    assert paths.index(base) < paths.index(f"{base}/{{dataset_id}}")
    assert paths.index(f"{base}/{{dataset_id}}/preview") < paths.index(f"{base}/{{dataset_id}}")
