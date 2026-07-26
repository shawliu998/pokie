from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from packages.contracts.quant import QUANT_AGENT_TOOL_REGISTRY, QuantBarInterval
from services.api.app.api import routes_quant
from services.api.app.modules.quant.kraken_market_data_v2 import (
    KrakenMarketBarsResult,
    KrakenMarketDataV2Client,
    KrakenMarketDataV2Error,
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
        json={
            "name": name,
            "data_region": "local",
            "retention_policy_version": "retention-v1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class _Transport:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        del url, kwargs
        return httpx.Response(200, content=self.raw)


def _kraken_result(
    *, retrieved_at: datetime = datetime(2025, 1, 1, 12, 30, tzinfo=UTC)
) -> KrakenMarketBarsResult:
    current_start = datetime(2025, 1, 1, 12, tzinfo=UTC)
    step = timedelta(hours=4)
    rows = []
    for index in range(548, -1, -1):
        timestamp = current_start - step * index
        rows.append(
            [
                int(timestamp.timestamp()),
                "100",
                "102",
                "99",
                "101",
                "100.5",
                "12.5",
                42,
            ]
        )
    raw = json.dumps(
        {
            "error": [],
            "result": {
                "BTC/USDT": rows,
                "last": int(current_start.timestamp()),
            },
        }
    ).encode()
    return KrakenMarketDataV2Client(
        _Transport(raw),
        clock=lambda: retrieved_at,
    ).fetch_market_bars(
        symbol="BTCUSDT",
        interval=QuantBarInterval.FOUR_HOURS,
        limit=548,
    )


def test_connector_directory_and_fetch_enter_canonical_market_v2_path(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _workspace(client, principal_id, "Kraken connector")["workspace_id"]
    directory_response = client.get(
        "/v1/quant/connectors",
        headers=_headers(principal_id, workspace_id),
    )
    assert directory_response.status_code == 200
    assert directory_response.json() == [
        {
            "data_authenticity": "generated",
            "connector_id": "kraken-spot-ohlc-v1",
            "provider": "kraken_spot",
            "display_name": "Kraken Spot public OHLC",
            "source_kind": "market_bars",
            "supported_symbols": ["BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"],
            "supported_intervals": ["4h", "1D"],
            "minimum_recent_bars": {"4h": 548, "1D": 252},
            "maximum_recent_bars": 719,
            "fetch_endpoint": "/v1/quant/connectors/kraken-spot-ohlc-v1/fetch",
            "connector_version": "kraken-spot-ohlc-v1",
            "source_terms_url": "https://www.kraken.com/legal",
            "source_documentation_url": (
                "https://docs.kraken.com/api-reference/market-data/get-ohlc-data"
            ),
        }
    ]

    fetched = _kraken_result()
    refetched = _kraken_result(retrieved_at=datetime(2025, 1, 1, 12, 45, tzinfo=UTC))
    drifted_request = replace(
        refetched,
        evidence=replace(
            refetched.evidence,
            source_request_digest="sha256:" + "f" * 64,
        ),
    )
    assert refetched.dataset == fetched.dataset
    assert refetched.evidence != fetched.evidence
    results = iter((fetched, refetched, drifted_request))

    class _FakeKrakenClient:
        def fetch_market_bars(
            self, *, symbol: str, interval: QuantBarInterval, limit: int
        ) -> KrakenMarketBarsResult:
            assert (symbol, interval, limit) == (
                "BTCUSDT",
                QuantBarInterval.FOUR_HOURS,
                548,
            )
            return next(results)

    monkeypatch.setattr(routes_quant, "_kraken_market_data_v2_client", _FakeKrakenClient)
    response = client.post(
        "/v1/quant/connectors/kraken-spot-ohlc-v1/fetch",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": "BTCUSDT Kraken 4h",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "limit": 548,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["dataset_id"].startswith("kraken-BTCUSDT-4h-")
    assert body["interval"] == "4h"
    assert body["bar_count"] == 548
    assert body["research_eligible"] is True
    assert body["data_authenticity"] == "collected"
    assert body["evidence"]["source_kind"] == "provider_fetch"
    assert body["evidence"]["source_name"] == "Kraken Spot public OHLC"
    assert body["evidence"]["connector_version"] == "kraken-spot-ohlc-v1"
    assert body["evidence"]["source_request_digest"].startswith("sha256:")
    assert body["evidence"]["terms_reference"] == "https://www.kraken.com/legal"
    assert body["evidence"]["page_raw_sha256"][0].startswith("sha256:")
    assert "raw_payload" not in json.dumps(body).lower()
    assert "vwap" not in json.dumps(body).lower()
    assert "trade_count" not in json.dumps(body).lower()

    repeated = client.post(
        "/v1/quant/connectors/kraken-spot-ohlc-v1/fetch",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": "BTCUSDT Kraken 4h refetch",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "limit": 548,
        },
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["dataset_id"] == body["dataset_id"]
    assert repeated.json()["record_digest"] == body["record_digest"]
    assert repeated.json()["evidence"] == body["evidence"]

    conflicting_request = client.post(
        "/v1/quant/connectors/kraken-spot-ohlc-v1/fetch",
        headers=_headers(principal_id, workspace_id),
        json={
            "name": "BTCUSDT Kraken 4h conflicting request",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "limit": 548,
        },
    )
    assert conflicting_request.status_code == 409

    listed = client.get(
        "/v1/quant/datasets/v2",
        headers=_headers(principal_id, workspace_id),
    )
    assert listed.status_code == 200
    assert listed.json()[0]["dataset_id"] == body["dataset_id"]
    restored = QuantStore().get_market_dataset_v2(
        workspace_id=workspace_id,
        dataset_id=body["dataset_id"],
    )
    assert restored.dataset.digest == body["digest"]
    assert restored.evidence.source_request_digest == body["evidence"]["source_request_digest"]

    assert len(QUANT_AGENT_TOOL_REGISTRY) == 7
    assert all("kraken" not in tool.value for tool in QUANT_AGENT_TOOL_REGISTRY)


def test_connector_rejects_arbitrary_scope_and_provider_failure_without_persistence(
    client: TestClient,
    principal_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = _workspace(client, principal_id, "Kraken fail closed")["workspace_id"]

    for payload in (
        {"symbol": "SOLUSD", "interval": "4h", "limit": 548},
        {"symbol": "BTCUSDT", "interval": "1h", "limit": 2190},
        {"symbol": "BTCUSDT", "interval": "4h", "limit": 547},
        {
            "symbol": "BTCUSDT",
            "interval": "4h",
            "limit": 548,
            "endpoint": "https://example.test/private",
        },
    ):
        response = client.post(
            "/v1/quant/connectors/kraken-spot-ohlc-v1/fetch",
            headers=_headers(principal_id, workspace_id),
            json=payload,
        )
        assert response.status_code == 422

    class _FailingKrakenClient:
        def fetch_market_bars(
            self, *, symbol: str, interval: QuantBarInterval, limit: int
        ) -> KrakenMarketBarsResult:
            del symbol, interval, limit
            raise KrakenMarketDataV2Error("Kraken Spot market-data request failed safely.")

    monkeypatch.setattr(
        routes_quant,
        "_kraken_market_data_v2_client",
        _FailingKrakenClient,
    )
    failed = client.post(
        "/v1/quant/connectors/kraken-spot-ohlc-v1/fetch",
        headers=_headers(principal_id, workspace_id),
        json={"symbol": "BTCUSDT", "interval": "4h", "limit": 548},
    )
    assert failed.status_code == 409
    assert (
        client.get(
            "/v1/quant/datasets/v2",
            headers=_headers(principal_id, workspace_id),
        ).json()
        == []
    )
