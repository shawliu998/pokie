from __future__ import annotations

import pytest

from packages.contracts.quant import QuantBarInterval, parse_market_ohlcv_csv


def _csv(*rows: str) -> str:
    return "timestamp,open,high,low,close,volume\n" + "\n".join(rows) + "\n"


@pytest.mark.parametrize(
    ("interval", "rows", "expected_ppy"),
    [
        (
            QuantBarInterval.HOUR,
            [
                "2024-01-02T00:00:00Z,100,102,99,101,12.34567890",
                "2024-01-02T01:00:00Z,101,103,100,102,13",
            ],
            8760,
        ),
        (
            QuantBarInterval.FOUR_HOURS,
            [
                "2024-01-02T00:00:00Z,100,102,99,101,12.34567890",
                "2024-01-02T04:00:00Z,101,103,100,102,13",
            ],
            2190,
        ),
        (
            QuantBarInterval.DAILY,
            [
                "2024-01-02T00:00:00Z,100,102,99,101,12.34567890",
                "2024-01-03T00:00:00Z,101,103,100,102,13",
            ],
            365,
        ),
    ],
)
def test_v2_csv_parses_utc_24x7_market_bars(
    interval: QuantBarInterval, rows: list[str], expected_ppy: int
) -> None:
    dataset = parse_market_ohlcv_csv(_csv(*rows), symbol="btcusdt", interval=interval)

    assert dataset.symbol == "BTCUSDT"
    assert dataset.interval is interval
    assert dataset.provenance == "csv_upload"
    assert dataset.periods_per_year == expected_ppy
    assert str(dataset.bars[0].volume) == "12.34567890"


def test_v2_csv_accepts_eight_decimal_prices_and_normalizes_bom_headers() -> None:
    text = (
        "\ufeff Timestamp , OPEN , high , LOW , Close , Volume \n"
        "2024-01-02T00:00:00Z,100.12345678,102.12345678,99.12345678,101.12345678,12.3\n"
    )

    dataset = parse_market_ohlcv_csv(text, symbol="btcusdt", interval=QuantBarInterval.HOUR)

    assert str(dataset.bars[0].open) == "100.12345678"


@pytest.mark.parametrize(
    ("interval", "text", "message"),
    [
        (
            QuantBarInterval.HOUR,
            "date,open,high,low,close,volume\n2024-01-02,1,2,1,1,1\n",
            "timestamp",
        ),
        (QuantBarInterval.HOUR, _csv("2024-01-02,1,2,1,1,1"), "RFC3339"),
        (QuantBarInterval.HOUR, _csv("2024-01-02T00:00:00,1,2,1,1,1"), "RFC3339"),
        (QuantBarInterval.HOUR, _csv("2024-01-02T08:00:00+08:00,1,2,1,1,1"), "RFC3339"),
        (QuantBarInterval.HOUR, _csv("2024-01-02T00:30:00Z,1,2,1,1,1"), "aligned"),
        (QuantBarInterval.FOUR_HOURS, _csv("2024-01-02T02:00:00Z,1,2,1,1,1"), "aligned"),
    ],
)
def test_v2_csv_rejects_missing_or_invalid_intraday_timestamp_boundary(
    interval: QuantBarInterval, text: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parse_market_ohlcv_csv(text, symbol="BTCUSDT", interval=interval)


@pytest.mark.parametrize(
    "rows",
    [
        [
            "2024-01-02T00:00:00Z,1,2,1,1,1",
            "2024-01-02T00:00:00Z,1,2,1,1,1",
        ],
        [
            "2024-01-02T01:00:00Z,1,2,1,1,1",
            "2024-01-02T00:00:00Z,1,2,1,1,1",
        ],
    ],
)
def test_v2_csv_rejects_duplicate_or_unordered_timestamps(rows: list[str]) -> None:
    with pytest.raises(ValueError, match="strictly ordered"):
        parse_market_ohlcv_csv(_csv(*rows), symbol="BTCUSDT", interval=QuantBarInterval.HOUR)


@pytest.mark.parametrize(
    "row",
    [
        "2024-01-02T00:00:00Z,NaN,2,1,1,1",
        "2024-01-02T00:00:00Z,1,Infinity,1,1,1",
        "2024-01-02T00:00:00Z,1,2,1,1,-Infinity",
        "2024-01-02T00:00:00Z,1,2,1,1,-1",
    ],
)
def test_v2_csv_rejects_nonfinite_or_negative_ohlcv_values(row: str) -> None:
    with pytest.raises(ValueError):
        parse_market_ohlcv_csv(_csv(row), symbol="BTCUSDT", interval=QuantBarInterval.HOUR)
