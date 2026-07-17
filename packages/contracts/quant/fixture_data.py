"""Contract-wrapped deterministic fixtures for the bounded Quant dataset."""

from __future__ import annotations

from typing import Any

from packages.domain.quant_fixture_data import (
    SPY_DAILY_FIXTURE_BARS,
    SPY_DAILY_FIXTURE_DATASET_ID,
)

from .data import (
    QUANT_DAILY_BAR_SCHEMA_VERSION,
    QuantDailyBar,
    QuantDailyBarDataset,
    QuantDailyBarInterval,
    QuantDatasetProvenance,
)


def _spy_daily_fixture_content() -> dict[str, Any]:
    bars = tuple(
        QuantDailyBar(
            trading_date=row.trading_date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in SPY_DAILY_FIXTURE_BARS
    )
    return {
        "dataset_id": SPY_DAILY_FIXTURE_DATASET_ID,
        "provenance": QuantDatasetProvenance.SYNTHETIC_FIXTURE.value,
        "symbol": "SPY",
        "interval": QuantDailyBarInterval.DAILY.value,
        "covered_start": bars[0].trading_date,
        "covered_end": bars[-1].trading_date,
        "schema_version": QUANT_DAILY_BAR_SCHEMA_VERSION,
        "bars": [bar.model_dump(mode="json") for bar in bars],
    }


def build_spy_daily_fixture() -> QuantDailyBarDataset:
    """Build the canonical immutable SPY daily fixture with its verified digest."""

    content = _spy_daily_fixture_content()
    return QuantDailyBarDataset.model_validate(
        {**content, "digest": QuantDailyBarDataset.digest_for(content)}
    )


SPY_DAILY_FIXTURE = build_spy_daily_fixture()
