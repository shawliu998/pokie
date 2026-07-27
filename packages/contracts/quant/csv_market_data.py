"""Strict calendar-aware CSV parser for the isolated v2 market-bar boundary."""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
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
    market_bar_label_is_consistent,
    market_calendar_metadata,
)

_REQUIRED_VALUE_COLUMNS = ("open", "high", "low", "close", "volume")
_RFC3339_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
QUANT_MARKET_OHLCV_CSV_PARSER_VERSION = "quant-market-ohlcv-csv-v3"


def parse_market_ohlcv_csv(
    csv_text: str,
    *,
    symbol: str,
    interval: QuantBarInterval,
    market_calendar: QuantMarketCalendar = QuantMarketCalendar.CONTINUOUS,
) -> QuantMarketBarDataset:
    """Parse one supported v2 CSV without inferring exchange holidays.

    Continuous markets retain the RFC3339-Z ``timestamp`` contract. Exchange
    daily imports use an ISO ``date`` whose UTC-midnight timestamp is a
    canonical session-date label, not an event timestamp.
    """

    normalized_symbol = symbol.strip().upper()
    market_session, time_zone, periods_per_year = market_calendar_metadata(
        calendar=market_calendar, interval=interval
    )
    date_labeled = market_calendar is not QuantMarketCalendar.CONTINUOUS
    label_column = "date" if date_labeled else "timestamp"
    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    headers = _normalized_headers(reader.fieldnames)
    missing = [
        column
        for column in (label_column, *_REQUIRED_VALUE_COLUMNS)
        if column not in headers.values()
    ]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

    bars: list[QuantMarketBar] = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"CSV row {row_number} does not match the header shape")
        normalized_row = {headers[key]: value for key, value in row.items() if isinstance(key, str)}
        try:
            timestamp = (
                _parse_session_date(normalized_row.get("date"))
                if date_labeled
                else _parse_timestamp(normalized_row.get("timestamp"))
            )
            if not market_bar_label_is_consistent(
                timestamp=timestamp,
                calendar=market_calendar,
                interval=interval,
            ):
                raise ValueError(f"{market_calendar.value} session date must fall on a weekday")
            bar = QuantMarketBar(
                timestamp=timestamp,
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
            "market_calendar": market_calendar.value,
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
        "market_calendar": market_calendar.value,
        "market_session": market_session.value,
        "time_zone": time_zone,
        "periods_per_year": periods_per_year,
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


def _parse_timestamp(value: str | None) -> datetime:
    if value is None or not _RFC3339_Z.fullmatch(value.strip()):
        raise ValueError("timestamp must be RFC3339 UTC with a Z suffix")
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).astimezone(UTC)
    except ValueError as exc:
        raise ValueError("timestamp must be RFC3339 UTC with a Z suffix") from exc


def _parse_session_date(value: str | None) -> datetime:
    if value is None or not _ISO_DATE.fullmatch(value.strip()):
        raise ValueError("date must use ISO YYYY-MM-DD format")
    try:
        return datetime.combine(date.fromisoformat(value.strip()), time.min, tzinfo=UTC)
    except ValueError as exc:
        raise ValueError("date must use ISO YYYY-MM-DD format") from exc


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
