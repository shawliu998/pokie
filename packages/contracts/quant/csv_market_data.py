"""Strict RFC3339-Z CSV parser for the isolated v2 market-bar boundary."""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any

from pydantic import ValidationError

from packages.domain.canonical import canonical_digest

from .market_data import (
    QUANT_MARKET_BAR_SCHEMA_VERSION,
    QuantBarInterval,
    QuantMarketBar,
    QuantMarketBarDataset,
    QuantMarketCalendar,
    QuantMarketDataProvenance,
    QuantMarketSession,
    periods_per_year_for,
)

_REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
_RFC3339_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
QUANT_MARKET_OHLCV_CSV_PARSER_VERSION = "quant-market-ohlcv-csv-v2"


def parse_market_ohlcv_csv(
    csv_text: str, *, symbol: str, interval: QuantBarInterval
) -> QuantMarketBarDataset:
    """Parse v2 24x7 CSV without changing the legacy date-based parser."""

    normalized_symbol = symbol.strip().upper()
    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    headers = _normalized_headers(reader.fieldnames)
    missing = [column for column in _REQUIRED_COLUMNS if column not in headers.values()]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

    bars: list[QuantMarketBar] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"CSV row {row_number} does not match the header shape")
        normalized_row = {headers[key]: value for key, value in row.items() if isinstance(key, str)}
        try:
            bar = QuantMarketBar(
                timestamp=_parse_timestamp(normalized_row.get("timestamp"), row_number),
                open=_decimal(normalized_row.get("open"), "open"),
                high=_decimal(normalized_row.get("high"), "high"),
                low=_decimal(normalized_row.get("low"), "low"),
                close=_decimal(normalized_row.get("close"), "close"),
                volume=_decimal(normalized_row.get("volume"), "volume"),
            )
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"CSV row {row_number}: {exc}") from None
        if not _aligned(bar.timestamp, interval):
            raise ValueError(f"CSV row {row_number}: timestamp is not interval aligned")
        bars.append(bar)
    if not bars:
        raise ValueError("CSV has no data rows")

    identity = canonical_digest(
        {
            "symbol": normalized_symbol,
            "interval": interval.value,
            "bars": [bar.model_dump(mode="json") for bar in bars],
        }
    ).removeprefix("sha256:")[:16]
    content: dict[str, Any] = {
        "dataset_id": f"market-csv-{normalized_symbol}-{interval.value}-{identity}",
        "provenance": QuantMarketDataProvenance.CSV_UPLOAD.value,
        "symbol": normalized_symbol,
        "interval": interval.value,
        "covered_start": bars[0].timestamp,
        "covered_end": bars[-1].timestamp,
        "market_calendar": QuantMarketCalendar.CONTINUOUS.value,
        "market_session": QuantMarketSession.CONTINUOUS.value,
        "time_zone": "UTC",
        "periods_per_year": periods_per_year_for(
            calendar=QuantMarketCalendar.CONTINUOUS, interval=interval
        ),
        "schema_version": QUANT_MARKET_BAR_SCHEMA_VERSION,
        "bars": [bar.model_dump(mode="json") for bar in bars],
    }
    try:
        return QuantMarketBarDataset.model_validate(
            {**content, "digest": QuantMarketBarDataset.digest_for(content)}
        )
    except ValidationError as exc:
        raise ValueError(str(exc)) from None


def _normalized_headers(fieldnames: Sequence[str] | None) -> dict[str, str]:
    if not fieldnames:
        raise ValueError("CSV has no header row")
    normalized = [header.strip().casefold() for header in fieldnames]
    if any(not header for header in normalized):
        raise ValueError("CSV headers must be non-empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("CSV headers must be unique without regard to case")
    return dict(zip(fieldnames, normalized, strict=True))


def _parse_timestamp(value: str | None, row_number: int) -> datetime:
    del row_number
    if value is None or not _RFC3339_Z.fullmatch(value.strip()):
        raise ValueError("timestamp must be RFC3339 UTC with a Z suffix")
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise ValueError("timestamp must be RFC3339 UTC with a Z suffix") from exc


def _decimal(value: str | None, field: str) -> Decimal:
    if value is None or not value.strip():
        raise ValueError(f"{field} is required")
    try:
        decimal_value = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"{field} must be finite")
    return decimal_value


def _aligned(timestamp: datetime, interval: QuantBarInterval) -> bool:
    if interval is QuantBarInterval.HOUR:
        return timestamp.minute == 0 and timestamp.second == 0 and timestamp.microsecond == 0
    if interval is QuantBarInterval.FOUR_HOURS:
        return (
            timestamp.hour % 4 == 0
            and timestamp.minute == 0
            and timestamp.second == 0
            and timestamp.microsecond == 0
        )
    return timestamp.hour == timestamp.minute == timestamp.second == timestamp.microsecond == 0
