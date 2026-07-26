"""Deterministic, local daily-bar fixture data for the Quant dataset boundary.

The rows are generated from fixed decimal rules over weekdays. They are not
market observations and do not attempt to reproduce an exchange calendar.
There is no fetching, storage, backtest behavior, or Pydantic dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

SPY_DAILY_FIXTURE_DATASET_ID = "spy-daily-weekday-synthetic-v2"


@dataclass(frozen=True, slots=True)
class QuantFixtureDailyBar:
    """A local immutable OHLCV row suitable for pure-domain consumers."""

    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


_PRICE_QUANTUM = Decimal("0.000001")


def _synthetic_weekday_bars() -> tuple[QuantFixtureDailyBar, ...]:
    current_date = date(2018, 1, 2)
    end_date = date(2023, 12, 29)
    prior_close = Decimal("100")
    rows: list[QuantFixtureDailyBar] = []
    index = 0
    while current_date <= end_date:
        if current_date.weekday() < 5:
            phase = index % 180
            regime = (
                Decimal("0.0018")
                if phase < 80
                else Decimal("-0.0025")
                if phase < 120
                else Decimal("0.0012")
            )
            shock = (
                Decimal("-0.0035")
                if 520 <= index < 610
                else Decimal("0.0030")
                if 610 <= index < 760
                else Decimal("-0.0045")
                if 1050 <= index < 1120
                else Decimal("0.0028")
                if 1120 <= index < 1300
                else Decimal("0")
            )
            noise = Decimal((index * 37) % 17 - 8) * Decimal("0.00018")
            overnight = Decimal((index * 13) % 9 - 4) * Decimal("0.00025")
            opening = (prior_close * (Decimal("1") + overnight)).quantize(_PRICE_QUANTUM)
            close = (prior_close * (Decimal("1") + regime + shock + noise)).quantize(_PRICE_QUANTUM)
            spread = Decimal("0.0025") + Decimal((index * 11) % 7) * Decimal("0.00025")
            high = (max(opening, close) * (Decimal("1") + spread)).quantize(_PRICE_QUANTUM)
            low = (min(opening, close) * (Decimal("1") - spread)).quantize(_PRICE_QUANTUM)
            rows.append(
                QuantFixtureDailyBar(
                    trading_date=current_date,
                    open=opening,
                    high=high,
                    low=low,
                    close=close,
                    volume=1_000_000 + (index % 23) * 17_000,
                )
            )
            prior_close = close
            index += 1
        current_date += timedelta(days=1)
    return tuple(rows)


SPY_DAILY_FIXTURE_BARS = _synthetic_weekday_bars()
