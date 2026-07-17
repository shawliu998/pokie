"""Pure CSV-to-daily-bar normalization for local Quant datasets.

The importer deliberately produces only the immutable contract object.  It has
no storage, network, or execution dependencies, so callers can persist the
verified dataset boundary wherever their runtime requires.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any

from packages.domain.canonical import canonical_digest

from .data import (
    QUANT_DAILY_BAR_SCHEMA_VERSION,
    QuantDailyBar,
    QuantDailyBarDataset,
    QuantDailyBarInterval,
    QuantDatasetProvenance,
)

_REQUIRED_COLUMNS = ("date", "open", "high", "low", "close")
QUANT_OHLCV_CSV_PARSER_VERSION = "quant-ohlcv-csv-v1"


def parse_ohlcv_csv(csv_text: str, *, name: str, symbol: str) -> QuantDailyBarDataset:
    """Parse strict daily OHLCV CSV into a canonical imported dataset.

    Header names are case-insensitive and may contain surrounding whitespace.
    The source text itself is intentionally not part of identity: equivalent
    rows with different ordering of columns or whitespace produce the same
    immutable dataset and digest.
    """

    if not name.strip():
        raise ValueError("dataset name is required")
    normalized_symbol = symbol.strip().upper()
    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    headers = _normalized_headers(reader.fieldnames)
    missing = [column for column in _REQUIRED_COLUMNS if column not in headers.values()]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

    bars: list[QuantDailyBar] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"CSV row {row_number} does not match the header shape")
        normalized_row: dict[str, str | None] = {}
        for key, value in row.items():
            if not isinstance(key, str) or not isinstance(value, str | None):
                raise ValueError(f"CSV row {row_number} does not match the header shape")
            normalized_row[headers[key]] = value
        try:
            bar = QuantDailyBar(
                trading_date=_parse_date(normalized_row.get("date"), row_number),
                open=_parse_price(normalized_row.get("open"), "open", row_number),
                high=_parse_price(normalized_row.get("high"), "high", row_number),
                low=_parse_price(normalized_row.get("low"), "low", row_number),
                close=_parse_price(normalized_row.get("close"), "close", row_number),
                volume=_parse_volume(normalized_row.get("volume"), row_number),
            )
        except ValueError as exc:
            raise ValueError(f"CSV row {row_number}: {exc}") from exc
        bars.append(bar)

    if not bars:
        raise ValueError("CSV has no data rows")

    normalized_bars = [bar.model_dump(mode="json") for bar in bars]
    source_digest = canonical_digest({"symbol": normalized_symbol, "bars": normalized_bars})
    dataset_id = f"ohlcv-{normalized_symbol}-{source_digest.removeprefix('sha256:')[:16]}"
    content: dict[str, Any] = {
        "dataset_id": dataset_id,
        "provenance": QuantDatasetProvenance.IMPORTED_FIXTURE.value,
        "symbol": normalized_symbol,
        "interval": QuantDailyBarInterval.DAILY.value,
        "covered_start": bars[0].trading_date,
        "covered_end": bars[-1].trading_date,
        "schema_version": QUANT_DAILY_BAR_SCHEMA_VERSION,
        "bars": normalized_bars,
    }
    return QuantDailyBarDataset.model_validate(
        {**content, "digest": QuantDailyBarDataset.digest_for(content)}
    )


def _normalized_headers(fieldnames: Sequence[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise ValueError("CSV has no header row")
    normalized = [header.strip().casefold() for header in fieldnames]
    if any(not header for header in normalized):
        raise ValueError("CSV headers must be non-empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("CSV headers must be unique without regard to case")
    return dict(zip(fieldnames, normalized, strict=True))


def _parse_date(value: str | None, row_number: int) -> date:
    if value is None or not value.strip():
        raise ValueError("date is required")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("date must use ISO-8601 YYYY-MM-DD") from exc


def _parse_price(value: str | None, column: str, row_number: int) -> Decimal:
    del row_number
    if value is None or not value.strip():
        raise ValueError(f"{column} is required")
    try:
        price = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{column} must be a decimal price") from exc
    if not price.is_finite() or price <= 0:
        raise ValueError(f"{column} must be a finite positive price")
    return price


def _parse_volume(value: str | None, row_number: int) -> int:
    del row_number
    if value is None or not value.strip():
        return 0
    try:
        volume = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError("volume must be a non-negative integer") from exc
    if not volume.is_finite() or volume < 0 or volume != volume.to_integral_value():
        raise ValueError("volume must be a non-negative integer")
    return int(volume)
