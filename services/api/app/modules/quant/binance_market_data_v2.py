"""Bounded, in-memory Binance v2 market-bar normalization.

This module intentionally has no store, route, or UI dependency.  It is the
C2A acquisition boundary for a later persistence package, while the existing
daily CSV adapter remains untouched.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol

import httpx
from pydantic import ValidationError

from packages.contracts.quant import (
    QUANT_MARKET_BAR_SCHEMA_VERSION,
    QuantBarInterval,
    QuantMarketBar,
    QuantMarketBarDataset,
    QuantMarketCalendar,
    QuantMarketDataProvenance,
    QuantMarketSession,
    periods_per_year_for,
)
from packages.domain.canonical import canonical_digest

BINANCE_V2_DATA_API_BASE_URL = "https://data-api.binance.vision"
BINANCE_V2_KLINES_PATH = "/api/v3/klines"
BINANCE_V2_NORMALIZER_VERSION = "binance-market-bars-v2"
MAX_BINANCE_V2_PAGE_BARS = 1_000
MAX_BINANCE_V2_PAGES = 5
MAX_BINANCE_V2_TOTAL_BARS = MAX_BINANCE_V2_PAGE_BARS * MAX_BINANCE_V2_PAGES
MAX_BINANCE_V2_PAGE_BYTES = 2 * 1024 * 1024
MAX_BINANCE_V2_TOTAL_BYTES = 8 * 1024 * 1024
_UNIX_EPOCH_UTC = datetime(1970, 1, 1, tzinfo=UTC)
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{4,15}$")
_INTERVALS: dict[QuantBarInterval, tuple[str, int]] = {
    QuantBarInterval.HOUR: ("1h", 3_600_000),
    QuantBarInterval.FOUR_HOURS: ("4h", 14_400_000),
    QuantBarInterval.DAILY: ("1d", 86_400_000),
}


class BinanceMarketDataV2Error(ValueError):
    """Safe v2 provider or normalization error without raw-payload disclosure."""


class BinanceV2Transport(Protocol):
    def get(self, url: str, **kwargs: object) -> httpx.Response: ...


class BinanceMarketBatchTerminationReason(StrEnum):
    """Bounded collection outcome for a single v2 provider batch."""

    REQUESTED_LIMIT = "requested_limit"
    HISTORY_EXHAUSTED = "history_exhausted"
    PAGE_CAP = "page_cap"


@dataclass(frozen=True, slots=True)
class BinanceMarketBatchEvidence:
    """Provider-row evidence distinct from retained, unique closed bars."""

    retrieved_at_utc: datetime
    source_reference: str
    requested_bar_count: int
    # Raw rows returned by Binance across pages, before closure and duplicate filtering.
    returned_bar_count: int
    # Unique closed bars retained in the normalized dataset.
    retained_bar_count: int
    closed_dropped_count: int
    deduplicated_count: int
    termination_reason: BinanceMarketBatchTerminationReason
    target_satisfied: bool
    page_raw_sha256: tuple[str, ...]
    batch_digest: str
    normalizer_version: str = BINANCE_V2_NORMALIZER_VERSION


@dataclass(frozen=True, slots=True)
class BinanceMarketCadenceQuality:
    status: str
    cadence_gap_count: int
    normalization_note: str


@dataclass(frozen=True, slots=True)
class BinanceMarketBarsResult:
    dataset: QuantMarketBarDataset
    evidence: BinanceMarketBatchEvidence
    quality: BinanceMarketCadenceQuality


class BinanceMarketDataV2Client:
    """Fetch at most five backward Binance kline pages into the v2 contract."""

    def __init__(
        self,
        transport: BinanceV2Transport | None = None,
        *,
        timeout_seconds: float = 15.0,
        clock: Callable[[], datetime] | None = None,
        page_size: int = MAX_BINANCE_V2_PAGE_BARS,
    ) -> None:
        if not 1 <= page_size <= MAX_BINANCE_V2_PAGE_BARS:
            raise ValueError("Binance v2 page size must be from 1 to 1000.")
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._page_size = page_size

    def fetch_market_bars(
        self, *, symbol: str, interval: QuantBarInterval, limit: int
    ) -> BinanceMarketBarsResult:
        normalized_symbol = symbol.strip().upper()
        if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
            raise BinanceMarketDataV2Error("Binance symbol is invalid.")
        if not 1 <= limit <= MAX_BINANCE_V2_TOTAL_BARS:
            raise BinanceMarketDataV2Error("Binance v2 limit must be from 1 to 5000.")
        if interval not in _INTERVALS:
            raise BinanceMarketDataV2Error("Binance v2 interval is unsupported.")

        provider_interval, interval_ms = _INTERVALS[interval]
        retrieved_at = self._retrieved_at()
        captured_ms = _epoch_milliseconds(retrieved_at)
        source_reference = (
            f"binance-vision:{BINANCE_V2_KLINES_PATH}?symbol={normalized_symbol}"
            f"&interval={provider_interval}&limit={limit}&pagination=backward"
        )
        page_digests: list[str] = []
        total_bytes = 0
        returned_count = 0
        closed_dropped_count = 0
        deduplicated_count = 0
        rows_by_open: dict[int, QuantMarketBar] = {}
        cursor: int | None = None
        previous_oldest: int | None = None
        termination_reason = BinanceMarketBatchTerminationReason.PAGE_CAP

        for _page_index in range(MAX_BINANCE_V2_PAGES):
            if len(rows_by_open) >= limit:
                termination_reason = BinanceMarketBatchTerminationReason.REQUESTED_LIMIT
                break
            page_limit = min(self._page_size, limit - len(rows_by_open))
            params: dict[str, str | int] = {
                "symbol": normalized_symbol,
                "interval": provider_interval,
                "limit": page_limit,
            }
            if cursor is not None:
                params["endTime"] = cursor
            raw = self._request(params)
            total_bytes += len(raw)
            if total_bytes > MAX_BINANCE_V2_TOTAL_BYTES:
                raise BinanceMarketDataV2Error(
                    "Binance v2 responses exceeded the total byte limit."
                )
            page_digests.append("sha256:" + hashlib.sha256(raw).hexdigest())
            payload = self._decode_page(raw, page_limit)
            returned_count += len(payload)
            if not payload:
                termination_reason = BinanceMarketBatchTerminationReason.HISTORY_EXHAUSTED
                break

            parsed_rows = [
                self._parse_row(row, interval=interval, interval_ms=interval_ms) for row in payload
            ]
            oldest_open = min(open_ms for open_ms, _, _ in parsed_rows)
            if previous_oldest is not None and oldest_open >= previous_oldest:
                raise BinanceMarketDataV2Error("Binance v2 pagination did not advance backward.")
            previous_oldest = oldest_open

            for open_ms, bar, close_ms in parsed_rows:
                if close_ms >= captured_ms:
                    closed_dropped_count += 1
                    continue
                existing = rows_by_open.get(open_ms)
                if existing is None:
                    rows_by_open[open_ms] = bar
                elif _same_economic_bar(existing, bar):
                    deduplicated_count += 1
                else:
                    raise BinanceMarketDataV2Error(
                        "Binance v2 pages contained conflicting duplicate bars."
                    )

            if len(rows_by_open) >= limit:
                termination_reason = BinanceMarketBatchTerminationReason.REQUESTED_LIMIT
                break
            if len(payload) < page_limit or oldest_open == 0:
                termination_reason = BinanceMarketBatchTerminationReason.HISTORY_EXHAUSTED
                break
            next_cursor = oldest_open - 1
            if cursor is not None and next_cursor >= cursor:
                raise BinanceMarketDataV2Error("Binance v2 pagination cursor did not advance.")
            cursor = next_cursor
        else:
            termination_reason = BinanceMarketBatchTerminationReason.PAGE_CAP

        if not rows_by_open:
            raise BinanceMarketDataV2Error("Binance v2 response contained no closed bars.")
        ordered_bars = tuple(bar for _, bar in sorted(rows_by_open.items()))
        dataset = self._dataset_for(symbol=normalized_symbol, interval=interval, bars=ordered_bars)
        quality = _cadence_quality(ordered_bars, interval_ms=interval_ms)
        target_satisfied = len(rows_by_open) >= limit
        evidence_content = {
            "source_reference": source_reference,
            "retrieved_at_utc": retrieved_at,
            "requested_bar_count": limit,
            "returned_bar_count": returned_count,
            "retained_bar_count": len(rows_by_open),
            "closed_dropped_count": closed_dropped_count,
            "deduplicated_count": deduplicated_count,
            "termination_reason": termination_reason.value,
            "target_satisfied": target_satisfied,
            "page_raw_sha256": page_digests,
            "normalizer_version": BINANCE_V2_NORMALIZER_VERSION,
        }
        evidence = BinanceMarketBatchEvidence(
            retrieved_at_utc=retrieved_at,
            source_reference=source_reference,
            requested_bar_count=limit,
            returned_bar_count=returned_count,
            retained_bar_count=len(rows_by_open),
            closed_dropped_count=closed_dropped_count,
            deduplicated_count=deduplicated_count,
            termination_reason=termination_reason,
            target_satisfied=target_satisfied,
            page_raw_sha256=tuple(page_digests),
            batch_digest=canonical_digest(evidence_content),
        )
        return BinanceMarketBarsResult(dataset=dataset, evidence=evidence, quality=quality)

    def _retrieved_at(self) -> datetime:
        value = self._clock()
        offset = value.utcoffset()
        if value.tzinfo is not UTC or offset is None or offset.total_seconds() != 0:
            raise BinanceMarketDataV2Error("Binance v2 clock must return a UTC timestamp.")
        return value

    def _request(self, params: dict[str, str | int]) -> bytes:
        try:
            if self._transport is not None:
                response = self._transport.get(
                    BINANCE_V2_DATA_API_BASE_URL + BINANCE_V2_KLINES_PATH,
                    params=params,
                    timeout=httpx.Timeout(self._timeout_seconds),
                    follow_redirects=False,
                )
            else:
                with httpx.Client(
                    timeout=httpx.Timeout(self._timeout_seconds), follow_redirects=False
                ) as client:
                    response = client.get(
                        BINANCE_V2_DATA_API_BASE_URL + BINANCE_V2_KLINES_PATH,
                        params=params,
                    )
        except httpx.HTTPError:
            raise BinanceMarketDataV2Error(
                "Binance v2 market-data request failed safely."
            ) from None
        if response.status_code != 200:
            raise BinanceMarketDataV2Error("Binance v2 market-data request failed safely.")
        raw = response.content
        if len(raw) > MAX_BINANCE_V2_PAGE_BYTES:
            raise BinanceMarketDataV2Error("Binance v2 response exceeded the page byte limit.")
        return raw

    @staticmethod
    def _decode_page(raw: bytes, page_limit: int) -> list[object]:
        try:
            payload = json.loads(raw)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise BinanceMarketDataV2Error("Binance v2 response was not valid JSON.") from None
        if not isinstance(payload, list):
            raise BinanceMarketDataV2Error("Binance v2 response must be a list.")
        if len(payload) > page_limit:
            raise BinanceMarketDataV2Error("Binance v2 response exceeded the requested page limit.")
        return payload

    @staticmethod
    def _parse_row(
        row: object, *, interval: QuantBarInterval, interval_ms: int
    ) -> tuple[int, QuantMarketBar, int]:
        if not isinstance(row, list) or len(row) != 12:
            raise BinanceMarketDataV2Error("Binance v2 kline rows must contain exactly 12 values.")
        open_ms, close_ms = row[0], row[6]
        if (
            not isinstance(open_ms, int)
            or isinstance(open_ms, bool)
            or open_ms < 0
            or not isinstance(close_ms, int)
            or isinstance(close_ms, bool)
            or close_ms < 0
        ):
            raise BinanceMarketDataV2Error("Binance v2 kline timestamps are invalid.")
        if open_ms % interval_ms:
            raise BinanceMarketDataV2Error("Binance v2 kline open time is not interval aligned.")
        if close_ms != open_ms + interval_ms - 1:
            raise BinanceMarketDataV2Error("Binance v2 kline close time is invalid.")
        if any(not isinstance(row[index], str) or not row[index] for index in (1, 2, 3, 4, 5)):
            raise BinanceMarketDataV2Error("Binance v2 kline OHLCV values are invalid.")
        try:
            bar = QuantMarketBar(
                timestamp=datetime.fromtimestamp(open_ms / 1000, tz=UTC),
                open=Decimal(row[1]),
                high=Decimal(row[2]),
                low=Decimal(row[3]),
                close=Decimal(row[4]),
                volume=Decimal(row[5]),
            )
        except (InvalidOperation, ValidationError, OverflowError, OSError, ValueError):
            raise BinanceMarketDataV2Error("Binance v2 kline OHLCV values are invalid.") from None
        if not _timestamp_matches_interval(bar.timestamp, interval):
            raise BinanceMarketDataV2Error("Binance v2 timestamp is not interval aligned.")
        return open_ms, bar, close_ms

    @staticmethod
    def _dataset_for(
        *, symbol: str, interval: QuantBarInterval, bars: tuple[QuantMarketBar, ...]
    ) -> QuantMarketBarDataset:
        identity = canonical_digest(
            {
                "symbol": symbol,
                "interval": interval.value,
                "bars": [bar.model_dump(mode="json") for bar in bars],
            }
        ).removeprefix("sha256:")[:16]
        content = {
            "dataset_id": f"binance-{symbol}-{interval.value}-{identity}",
            "provenance": QuantMarketDataProvenance.PROVIDER_FETCH.value,
            "symbol": symbol,
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
        return QuantMarketBarDataset.model_validate(
            {**content, "digest": QuantMarketBarDataset.digest_for(content)}
        )


def _same_economic_bar(left: QuantMarketBar, right: QuantMarketBar) -> bool:
    """Compare parsed timestamp and OHLCV values, not provider string formatting."""

    return (
        left.timestamp == right.timestamp
        and left.open == right.open
        and left.high == right.high
        and left.low == right.low
        and left.close == right.close
        and left.volume == right.volume
    )


def _epoch_milliseconds(timestamp: datetime) -> int:
    """Convert a canonical UTC timestamp without float rounding at close boundaries."""

    delta = timestamp - _UNIX_EPOCH_UTC
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


def _timestamp_matches_interval(timestamp: datetime, interval: QuantBarInterval) -> bool:
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


def _cadence_quality(
    bars: tuple[QuantMarketBar, ...], *, interval_ms: int
) -> BinanceMarketCadenceQuality:
    gap_count = sum(
        1
        for left, right in zip(bars, bars[1:], strict=False)
        if int((right.timestamp - left.timestamp).total_seconds() * 1000) != interval_ms
    )
    return BinanceMarketCadenceQuality(
        status="blocked" if gap_count else "accepted",
        cadence_gap_count=gap_count,
        normalization_note=(
            "No cadence gaps detected."
            if not gap_count
            else (
                "Cadence gaps were retained without filling; C2B persistence and "
                "future research must remain blocked."
            )
        ),
    )
