from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from packages.contracts.quant import parse_ohlcv_csv


def test_ohlcv_csv_builds_canonical_imported_daily_dataset() -> None:
    dataset = parse_ohlcv_csv(
        " Date , CLOSE , volume , low, open, high\n"
        "2024-01-02,101.5,1200,99,100,102\n"
        "2024-01-03,102.5,1300,100,101,103\n",
        name="SPY imported daily bars",
        symbol="spy",
    )

    assert dataset.dataset_id.startswith("ohlcv-SPY-")
    assert dataset.provenance == "imported_fixture"
    assert dataset.symbol == "SPY"
    assert dataset.covered_start == date(2024, 1, 2)
    assert dataset.covered_end == date(2024, 1, 3)
    assert dataset.bars[0].close == Decimal("101.5")
    assert dataset.bars[1].volume == 1300
    assert dataset.digest.startswith("sha256:")


def test_ohlcv_csv_is_stable_across_header_order_and_whitespace() -> None:
    first = parse_ohlcv_csv(
        "date,open,high,low,close,volume\n2024-01-02,100,102,99,101.5,1200\n",
        name="SPY imported daily bars",
        symbol="SPY",
    )
    second = parse_ohlcv_csv(
        " CLOSE , DATE , LOW , HIGH , OPEN , VOLUME\n101.5,2024-01-02,99,102,100,1200\n",
        name="SPY imported daily bars",
        symbol="SPY",
    )

    assert second == first


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("date,open,high,low\n2024-01-02,100,102,99\n", "missing required columns"),
        (
            "date,Date,open,high,low,close\n2024-01-02,2024-01-02,100,102,99,101\n",
            "headers must be unique",
        ),
        ("date,open,high,low,close\n2024-01-02,100,99,101,100\n", "high must be"),
        ("date,open,high,low,close\n2024-01-02,NaN,102,99,101\n", "finite positive"),
        (
            "date,open,high,low,close\n"
            "2024-01-02,100,102,99,101\n"
            "2024-01-02,101,103,100,102\n",
            "strictly ordered",
        ),
    ],
)
def test_ohlcv_csv_rejects_invalid_input(text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_ohlcv_csv(text, name="SPY imported daily bars", symbol="SPY")


def test_ohlcv_csv_defaults_blank_volume_to_zero() -> None:
    dataset = parse_ohlcv_csv(
        "date,open,high,low,close,volume\n2024-01-02,100,102,99,101,\n",
        name="SPY imported daily bars",
        symbol="SPY",
    )

    assert dataset.bars[0].volume == 0
