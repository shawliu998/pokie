from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from packages.contracts.quant import parse_ohlcv_csv
from services.api.app.modules.quant.binance_market_data import (
    BinanceMarketDataClient,
    BinanceMarketDataError,
)


class _Transport:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.calls: list[tuple[str, object]] = []

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append((url, kwargs["params"]))
        return self.response


def _row(open_time: int, *, volume: str = "12.5") -> list[object]:
    return [
        open_time,
        "100",
        "102",
        "99",
        "101",
        volume,
        open_time + 86_399_999,
        "0",
        1,
        "0",
        "0",
        "0",
    ]


def test_fetches_public_daily_rows_as_existing_ohlcv_csv() -> None:
    raw = json.dumps([_row(1_704_067_200_000), _row(1_704_153_600_000, volume="12.6")]).encode()
    transport = _Transport(httpx.Response(200, content=raw))
    result = BinanceMarketDataClient(transport).fetch_daily_klines(
        symbol="btcusdt", limit=252
    )

    assert result.bar_count == 2
    assert result.requested_limit == 252
    assert result.returned_bar_count == 2
    assert result.dropped_incomplete_count == 0
    assert result.retrieved_at.tzinfo is UTC
    assert result.csv_text.endswith("2024-01-02,100,102,99,101,13\n")
    assert result.provider_response_digest.startswith("sha256:")
    assert "secret" not in result.source_reference.lower()
    assert transport.calls[0][1] == {"symbol": "BTCUSDT", "interval": "1d", "limit": 252}
    assert len(parse_ohlcv_csv(result.csv_text, name="BTC daily", symbol="BTCUSDT").bars) == 2


@pytest.mark.parametrize(
    ("symbol", "limit"), [("BTC-USDT", 252), ("BTCUSDT", 251), ("BTCUSDT", 1001)]
)
def test_rejects_invalid_request_before_transport(symbol: str, limit: int) -> None:
    with pytest.raises(BinanceMarketDataError):
        BinanceMarketDataClient().fetch_daily_klines(symbol=symbol, limit=limit)


@pytest.mark.parametrize(
    "payload",
    [
        {"not": "a list"},
        [[1_704_067_200_000]],
        [_row(1_704_067_200_001)],
    ],
)
def test_rejects_malformed_or_non_utc_rows(payload: object) -> None:
    transport = _Transport(httpx.Response(200, content=json.dumps(payload).encode()))
    with pytest.raises(BinanceMarketDataError):
        BinanceMarketDataClient(transport).fetch_daily_klines(symbol="BTCUSDT", limit=252)


def test_drops_an_unclosed_current_daily_kline() -> None:
    current_open = int(datetime.now(tz=UTC).timestamp() * 1000) // 86_400_000 * 86_400_000
    payload = [_row(1_704_067_200_000), _row(current_open)]
    transport = _Transport(httpx.Response(200, content=json.dumps(payload).encode()))
    result = BinanceMarketDataClient(transport).fetch_daily_klines(symbol="BTCUSDT", limit=252)

    assert result.returned_bar_count == 1
    assert result.dropped_incomplete_count == 1
    assert "1970" not in result.csv_text
