from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from packages.contracts.quant import (
    QuantBarInterval,
    QuantConnectorDirectoryResponse,
    QuantKrakenSpotFetchRequest,
    QuantMarketDataProvenance,
    QuantMarketDatasetEvidence,
)
from services.api.app.modules.quant import kraken_market_data_v2 as module
from services.api.app.modules.quant.kraken_market_data_v2 import (
    KRAKEN_SPOT_CONNECTOR_VERSION,
    KRAKEN_SPOT_OHLC_PATH,
    KRAKEN_SPOT_TERMS_REFERENCE,
    KrakenMarketDataV2Client,
    KrakenMarketDataV2Error,
)


class _Transport:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _row(timestamp: datetime) -> list[object]:
    return [
        int(timestamp.timestamp()),
        "100.12345678",
        "102.12345678",
        "99.12345678",
        "101.12345678",
        "100.98765432",
        "12.34567890",
        42,
    ]


def _payload(*, pair: str, current_start: datetime, step: timedelta, completed: int) -> bytes:
    rows = [
        _row(current_start - step * index)
        for index in range(completed, -1, -1)
    ]
    return json.dumps(
        {
            "error": [],
            "result": {
                pair: rows,
                "last": int(current_start.timestamp()),
            },
        }
    ).encode()


@pytest.mark.parametrize(
    ("symbol", "pair", "interval", "minimum", "step", "current_start", "clock", "ppy"),
    [
        (
            "BTCUSDT",
            "BTC/USDT",
            QuantBarInterval.FOUR_HOURS,
            548,
            timedelta(hours=4),
            datetime(2025, 1, 1, 12, tzinfo=UTC),
            datetime(2025, 1, 1, 12, 30, tzinfo=UTC),
            2190,
        ),
        (
            "ETHUSD",
            "ETH/USD",
            QuantBarInterval.DAILY,
            252,
            timedelta(days=1),
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, 12, tzinfo=UTC),
            365,
        ),
    ],
)
def test_fixed_kraken_connector_normalizes_research_eligible_closed_bars(
    symbol: str,
    pair: str,
    interval: QuantBarInterval,
    minimum: int,
    step: timedelta,
    current_start: datetime,
    clock: datetime,
    ppy: int,
) -> None:
    transport = _Transport(
        [
            httpx.Response(
                200,
                content=_payload(
                    pair=pair,
                    current_start=current_start,
                    step=step,
                    completed=minimum,
                ),
            )
        ]
    )
    result = KrakenMarketDataV2Client(
        transport,
        clock=lambda: clock,
    ).fetch_market_bars(symbol=symbol, interval=interval, limit=minimum)

    assert result.dataset.dataset_id.startswith(f"kraken-{symbol}-{interval.value}-")
    assert result.dataset.provenance is QuantMarketDataProvenance.PROVIDER_FETCH
    assert result.dataset.periods_per_year == ppy
    assert len(result.dataset.bars) == minimum
    assert result.dataset.bars[-1].timestamp == current_start - step
    assert result.evidence.returned_bar_count == minimum + 1
    assert result.evidence.closed_dropped_count == 1
    assert result.evidence.target_satisfied is True
    assert result.evidence.connector_version == KRAKEN_SPOT_CONNECTOR_VERSION
    assert result.evidence.source_request_digest.startswith("sha256:")
    assert result.evidence.terms_reference == KRAKEN_SPOT_TERMS_REFERENCE
    assert result.quality.status == "accepted"
    url, kwargs = transport.calls[0]
    assert url.endswith(KRAKEN_SPOT_OHLC_PATH)
    assert kwargs["params"] == {
        "pair": pair,
        "interval": 240 if interval is QuantBarInterval.FOUR_HOURS else 1440,
        "assetVersion": 1,
    }
    assert "limit" not in kwargs["params"]  # type: ignore[operator]


def test_connector_contract_is_server_driven_and_interval_limit_bounded() -> None:
    directory = QuantConnectorDirectoryResponse(
        data_authenticity="generated",
        connector_id="kraken-spot-ohlc-v1",
        provider="kraken_spot",
        display_name="Kraken Spot public OHLC",
        source_kind="market_bars",
        supported_symbols=("BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"),
        supported_intervals=("4h", "1D"),
        minimum_recent_bars={"4h": 548, "1D": 252},
        maximum_recent_bars=719,
        fetch_endpoint="/v1/quant/connectors/kraken-spot-ohlc-v1/fetch",
        connector_version="kraken-spot-ohlc-v1",
        source_terms_url="https://www.kraken.com/legal",
        source_documentation_url=(
            "https://docs.kraken.com/api-reference/market-data/get-ohlc-data"
        ),
    )
    assert directory.maximum_recent_bars == 719

    QuantKrakenSpotFetchRequest.model_validate(
        {"symbol": "BTCUSDT", "interval": "4h", "limit": 548}
    )
    QuantKrakenSpotFetchRequest.model_validate(
        {"symbol": "ETHUSD", "interval": "1D", "limit": 252}
    )
    for invalid in (
        {"symbol": "SOLUSD", "interval": "4h", "limit": 548},
        {"symbol": "BTCUSDT", "interval": "1h", "limit": 2190},
        {"symbol": "BTCUSDT", "interval": "4h", "limit": 547},
        {"symbol": "BTCUSDT", "interval": "1D", "limit": 720},
        {
            "symbol": "BTCUSDT",
            "interval": "4h",
            "limit": 548,
            "url": "https://example.test/arbitrary",
        },
    ):
        with pytest.raises(ValidationError):
            QuantKrakenSpotFetchRequest.model_validate(invalid)


def test_connector_evidence_extension_is_additive_but_complete_when_present() -> None:
    legacy = QuantMarketDatasetEvidence(
        source_kind="provider_fetch",
        source_name="Existing provider",
        source_reference="provider:/fixed",
        retrieved_at_utc=datetime(2025, 1, 1, tzinfo=UTC),
        requested_bar_count=1,
        returned_bar_count=1,
        retained_bar_count=1,
        closed_dropped_count=0,
        deduplicated_count=0,
        page_raw_sha256=("sha256:page",),
        batch_digest="sha256:batch",
        termination_reason="requested_limit",
        target_satisfied=True,
        normalizer_version="existing-v1",
    )
    assert legacy.connector_version is None

    with pytest.raises(ValidationError, match="requires version"):
        QuantMarketDatasetEvidence.model_validate(
            {
                **legacy.model_dump(mode="json"),
                "connector_version": KRAKEN_SPOT_CONNECTOR_VERSION,
            }
        )


def test_live_shaped_721_row_response_drops_current_and_retains_bounded_history() -> None:
    current_start = datetime(2025, 1, 1, 12, tzinfo=UTC)
    transport = _Transport(
        [
            httpx.Response(
                200,
                content=_payload(
                    pair="BTC/USD",
                    current_start=current_start,
                    step=timedelta(hours=4),
                    completed=module.MAX_KRAKEN_SPOT_COMMITTED_BARS,
                ),
            )
        ]
    )

    result = KrakenMarketDataV2Client(
        transport,
        clock=lambda: current_start + timedelta(minutes=30),
    ).fetch_market_bars(
        symbol="BTCUSD",
        interval=QuantBarInterval.FOUR_HOURS,
        limit=module.MAX_KRAKEN_SPOT_RECENT_BARS,
    )

    assert result.evidence.returned_bar_count == module.MAX_KRAKEN_SPOT_RAW_ROWS
    assert result.evidence.closed_dropped_count == 1
    assert result.evidence.retained_bar_count == module.MAX_KRAKEN_SPOT_RECENT_BARS
    assert len(result.dataset.bars) == module.MAX_KRAKEN_SPOT_RECENT_BARS
    assert result.dataset.bars[-1].timestamp == current_start - timedelta(hours=4)


def test_kraken_response_errors_and_untrusted_shape_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = datetime(2025, 1, 1, 12, tzinfo=UTC)

    def clock() -> datetime:
        return datetime(2025, 1, 1, 12, 30, tzinfo=UTC)

    for payload in (
        {"error": ["EQuery:Unknown asset pair"], "result": {}},
        {"error": [], "result": {"BTC/USDT": [[1]], "last": 1}},
        {"error": [], "result": {"OTHER": [], "last": 1}},
        {
            "error": [],
            "result": {
                "BTC/USDT": [_row(current), _row(current - timedelta(hours=4))],
                "last": int(current.timestamp()),
            },
        },
    ):
        with pytest.raises(KrakenMarketDataV2Error):
            KrakenMarketDataV2Client(
                _Transport([httpx.Response(200, content=json.dumps(payload).encode())]),
                clock=clock,
            ).fetch_market_bars(
                symbol="BTCUSDT",
                interval=QuantBarInterval.FOUR_HOURS,
                limit=548,
            )

    with pytest.raises(KrakenMarketDataV2Error, match="failed safely"):
        KrakenMarketDataV2Client(
            _Transport([httpx.ConnectError("offline")]),
            clock=clock,
        ).fetch_market_bars(
            symbol="BTCUSDT",
            interval=QuantBarInterval.FOUR_HOURS,
            limit=548,
        )

    monkeypatch.setattr(module, "MAX_KRAKEN_SPOT_RESPONSE_BYTES", 4)
    with pytest.raises(KrakenMarketDataV2Error, match="byte limit"):
        KrakenMarketDataV2Client(
            _Transport([httpx.Response(200, content=b'{"error":[]}')]),
            clock=clock,
        ).fetch_market_bars(
            symbol="BTCUSDT",
            interval=QuantBarInterval.FOUR_HOURS,
            limit=548,
        )
