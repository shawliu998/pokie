"""D1-lite fixed Kraken Spot OHLC connector into native market-v2 data.

Kraken responses are untrusted transport records.  This module validates and
normalizes only public OHLCV fields, then returns the existing canonical
``QuantMarketBarDataset`` boundary for persistence by the route/store layer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
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

KRAKEN_SPOT_API_BASE_URL = "https://api.kraken.com"
KRAKEN_SPOT_OHLC_PATH = "/0/public/OHLC"
KRAKEN_SPOT_CONNECTOR_VERSION = "kraken-spot-ohlc-v1"
KRAKEN_SPOT_TERMS_REFERENCE = "https://www.kraken.com/legal"
KRAKEN_SPOT_DOCUMENTATION_REFERENCE = (
    "https://docs.kraken.com/api-reference/market-data/get-ohlc-data"
)
# Kraken documents up to 720 recent entries plus an always-present current
# interval. The live endpoint therefore returns at most 721 raw rows, of which
# at most 720 are committed. Keep the public fetch contract narrower at 719
# retained rows so the current interval can never be mistaken for evidence.
MAX_KRAKEN_SPOT_RAW_ROWS = 721
MAX_KRAKEN_SPOT_COMMITTED_BARS = 720
MAX_KRAKEN_SPOT_RECENT_BARS = 719
MAX_KRAKEN_SPOT_RESPONSE_BYTES = 2 * 1024 * 1024

KRAKEN_SPOT_SYMBOL_PAIRS: dict[str, str] = {
    "BTCUSD": "BTC/USD",
    "BTCUSDT": "BTC/USDT",
    "ETHUSD": "ETH/USD",
    "ETHUSDT": "ETH/USDT",
}
KRAKEN_SPOT_INTERVALS: dict[QuantBarInterval, tuple[int, timedelta, int]] = {
    QuantBarInterval.FOUR_HOURS: (240, timedelta(hours=4), 548),
    QuantBarInterval.DAILY: (1440, timedelta(days=1), 252),
}


class KrakenMarketDataV2Error(ValueError):
    """Safe fixed-connector transport or normalization failure."""


class KrakenV2Transport(Protocol):
    def get(self, url: str, **kwargs: object) -> httpx.Response: ...


@dataclass(frozen=True, slots=True)
class KrakenMarketBatchEvidence:
    retrieved_at_utc: datetime
    source_reference: str
    requested_bar_count: int
    returned_bar_count: int
    retained_bar_count: int
    closed_dropped_count: int
    deduplicated_count: int
    termination_reason: str
    target_satisfied: bool
    page_raw_sha256: tuple[str, ...]
    batch_digest: str
    connector_version: str
    source_request_digest: str
    terms_reference: str
    normalizer_version: str = KRAKEN_SPOT_CONNECTOR_VERSION


@dataclass(frozen=True, slots=True)
class KrakenMarketCadenceQuality:
    status: str
    cadence_gap_count: int
    normalization_note: str


@dataclass(frozen=True, slots=True)
class KrakenMarketBarsResult:
    dataset: QuantMarketBarDataset
    evidence: KrakenMarketBatchEvidence
    quality: KrakenMarketCadenceQuality


class KrakenMarketDataV2Client:
    """Fetch one allowlisted public OHLC response and retain recent closed bars."""

    def __init__(
        self,
        transport: KrakenV2Transport | None = None,
        *,
        timeout_seconds: float = 15.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    def fetch_market_bars(
        self, *, symbol: str, interval: QuantBarInterval, limit: int
    ) -> KrakenMarketBarsResult:
        normalized_symbol = symbol.strip().upper()
        provider_pair = KRAKEN_SPOT_SYMBOL_PAIRS.get(normalized_symbol)
        if provider_pair is None:
            raise KrakenMarketDataV2Error("Kraken Spot symbol is not allowlisted.")
        interval_config = KRAKEN_SPOT_INTERVALS.get(interval)
        if interval_config is None:
            raise KrakenMarketDataV2Error("Kraken Spot interval is unsupported.")
        provider_interval, interval_delta, minimum_limit = interval_config
        if isinstance(limit, bool) or not minimum_limit <= limit <= MAX_KRAKEN_SPOT_RECENT_BARS:
            raise KrakenMarketDataV2Error(
                f"Kraken {interval.value} recent limit must be from "
                f"{minimum_limit} to {MAX_KRAKEN_SPOT_RECENT_BARS}."
            )

        retrieved_at = self._retrieved_at()
        params: dict[str, str | int] = {
            "pair": provider_pair,
            "interval": provider_interval,
            "assetVersion": 1,
        }
        source_request_digest = canonical_digest(
            {
                "connector_version": KRAKEN_SPOT_CONNECTOR_VERSION,
                "provider": "kraken_spot",
                "method": "GET",
                "endpoint": KRAKEN_SPOT_OHLC_PATH,
                "params": params,
                "bounded_recent_limit": limit,
            }
        )
        source_reference = (
            f"kraken-spot:{KRAKEN_SPOT_OHLC_PATH}?pair={provider_pair}"
            f"&interval={provider_interval}&assetVersion=1&recent_limit={limit}"
        )
        raw = self._request(params)
        rows = self._decode_response(raw, provider_pair=provider_pair)
        parsed = tuple(
            self._parse_row(row, interval=interval, interval_delta=interval_delta)
            for row in rows
        )
        if any(
            current.timestamp >= following.timestamp
            for current, following in zip(parsed, parsed[1:], strict=False)
        ):
            raise KrakenMarketDataV2Error(
                "Kraken Spot OHLC rows must be strictly ordered without duplicates."
            )

        current = parsed[-1]
        if not (
            current.timestamp <= retrieved_at
            and current.timestamp + interval_delta > retrieved_at
        ):
            raise KrakenMarketDataV2Error(
                "Kraken Spot response did not end with the current uncommitted interval."
            )
        completed = parsed[:-1]
        if not completed or len(completed) > MAX_KRAKEN_SPOT_COMMITTED_BARS:
            raise KrakenMarketDataV2Error(
                "Kraken Spot committed OHLC row count is invalid."
            )
        retained = completed[-limit:]
        dataset = self._dataset_for(
            symbol=normalized_symbol,
            interval=interval,
            bars=retained,
        )
        quality = _cadence_quality(retained, interval_delta=interval_delta)
        target_satisfied = len(completed) >= limit
        termination_reason = "requested_limit" if target_satisfied else "history_exhausted"
        page_digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        evidence_content = {
            "source_reference": source_reference,
            "retrieved_at_utc": retrieved_at,
            "requested_bar_count": limit,
            "returned_bar_count": len(parsed),
            "retained_bar_count": len(retained),
            "closed_dropped_count": 1,
            "deduplicated_count": 0,
            "termination_reason": termination_reason,
            "target_satisfied": target_satisfied,
            "page_raw_sha256": [page_digest],
            "normalizer_version": KRAKEN_SPOT_CONNECTOR_VERSION,
            "connector_version": KRAKEN_SPOT_CONNECTOR_VERSION,
            "source_request_digest": source_request_digest,
            "terms_reference": KRAKEN_SPOT_TERMS_REFERENCE,
        }
        evidence = KrakenMarketBatchEvidence(
            retrieved_at_utc=retrieved_at,
            source_reference=source_reference,
            requested_bar_count=limit,
            returned_bar_count=len(parsed),
            retained_bar_count=len(retained),
            closed_dropped_count=1,
            deduplicated_count=0,
            termination_reason=termination_reason,
            target_satisfied=target_satisfied,
            page_raw_sha256=(page_digest,),
            batch_digest=canonical_digest(evidence_content),
            connector_version=KRAKEN_SPOT_CONNECTOR_VERSION,
            source_request_digest=source_request_digest,
            terms_reference=KRAKEN_SPOT_TERMS_REFERENCE,
        )
        return KrakenMarketBarsResult(dataset=dataset, evidence=evidence, quality=quality)

    def _retrieved_at(self) -> datetime:
        value = self._clock()
        offset = value.utcoffset()
        if value.tzinfo is not UTC or offset is None or offset.total_seconds() != 0:
            raise KrakenMarketDataV2Error("Kraken connector clock must return a UTC timestamp.")
        return value

    def _request(self, params: dict[str, str | int]) -> bytes:
        try:
            if self._transport is not None:
                response = self._transport.get(
                    KRAKEN_SPOT_API_BASE_URL + KRAKEN_SPOT_OHLC_PATH,
                    params=params,
                    timeout=httpx.Timeout(self._timeout_seconds),
                    follow_redirects=False,
                )
            else:
                with httpx.Client(
                    timeout=httpx.Timeout(self._timeout_seconds),
                    follow_redirects=False,
                ) as client:
                    response = client.get(
                        KRAKEN_SPOT_API_BASE_URL + KRAKEN_SPOT_OHLC_PATH,
                        params=params,
                    )
        except httpx.HTTPError:
            raise KrakenMarketDataV2Error(
                "Kraken Spot market-data request failed safely."
            ) from None
        if response.status_code != 200:
            raise KrakenMarketDataV2Error(
                "Kraken Spot market-data request failed safely."
            )
        raw = response.content
        if len(raw) > MAX_KRAKEN_SPOT_RESPONSE_BYTES:
            raise KrakenMarketDataV2Error(
                "Kraken Spot response exceeded the byte limit."
            )
        return raw

    @staticmethod
    def _decode_response(raw: bytes, *, provider_pair: str) -> list[object]:
        try:
            payload = json.loads(raw)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise KrakenMarketDataV2Error(
                "Kraken Spot response was not valid JSON."
            ) from None
        if not isinstance(payload, dict) or set(payload) != {"error", "result"}:
            raise KrakenMarketDataV2Error("Kraken Spot response shape is invalid.")
        errors = payload["error"]
        result = payload["result"]
        if not isinstance(errors, list) or errors:
            raise KrakenMarketDataV2Error(
                "Kraken Spot market-data request failed safely."
            )
        if (
            not isinstance(result, dict)
            or set(result) != {provider_pair, "last"}
            or not isinstance(result["last"], int)
            or isinstance(result["last"], bool)
        ):
            raise KrakenMarketDataV2Error("Kraken Spot result shape is invalid.")
        rows = result[provider_pair]
        if (
            not isinstance(rows, list)
            or not rows
            or len(rows) > MAX_KRAKEN_SPOT_RAW_ROWS
        ):
            raise KrakenMarketDataV2Error("Kraken Spot OHLC row count is invalid.")
        return rows

    @staticmethod
    def _parse_row(
        row: object,
        *,
        interval: QuantBarInterval,
        interval_delta: timedelta,
    ) -> QuantMarketBar:
        if not isinstance(row, list) or len(row) != 8:
            raise KrakenMarketDataV2Error(
                "Kraken Spot OHLC rows must contain exactly 8 values."
            )
        timestamp = row[0]
        if (
            not isinstance(timestamp, int)
            or isinstance(timestamp, bool)
            or timestamp < 0
        ):
            raise KrakenMarketDataV2Error("Kraken Spot OHLC timestamp is invalid.")
        if any(not isinstance(row[index], str) or not row[index] for index in range(1, 7)):
            raise KrakenMarketDataV2Error("Kraken Spot OHLC values are invalid.")
        if (
            not isinstance(row[7], int)
            or isinstance(row[7], bool)
            or row[7] < 0
        ):
            raise KrakenMarketDataV2Error("Kraken Spot OHLC trade count is invalid.")
        try:
            vwap = Decimal(row[5])
            if not vwap.is_finite() or vwap <= 0:
                raise InvalidOperation
            bar = QuantMarketBar(
                timestamp=datetime.fromtimestamp(timestamp, tz=UTC),
                open=Decimal(row[1]),
                high=Decimal(row[2]),
                low=Decimal(row[3]),
                close=Decimal(row[4]),
                volume=Decimal(row[6]),
            )
        except (InvalidOperation, ValidationError, OverflowError, OSError, ValueError):
            raise KrakenMarketDataV2Error(
                "Kraken Spot OHLC values are invalid."
            ) from None
        if interval is QuantBarInterval.FOUR_HOURS:
            aligned = (
                bar.timestamp.hour % 4 == 0
                and bar.timestamp.minute == 0
                and bar.timestamp.second == 0
            )
        else:
            aligned = (
                bar.timestamp.hour == 0
                and bar.timestamp.minute == 0
                and bar.timestamp.second == 0
            )
        if not aligned or bar.timestamp.microsecond != 0:
            raise KrakenMarketDataV2Error(
                "Kraken Spot OHLC timestamp is not interval aligned."
            )
        if interval_delta.total_seconds() not in {14_400, 86_400}:
            raise KrakenMarketDataV2Error("Kraken Spot interval is unsupported.")
        return bar

    @staticmethod
    def _dataset_for(
        *,
        symbol: str,
        interval: QuantBarInterval,
        bars: tuple[QuantMarketBar, ...],
    ) -> QuantMarketBarDataset:
        identity = canonical_digest(
            {
                "provider": "kraken_spot",
                "symbol": symbol,
                "interval": interval.value,
                "bars": [bar.model_dump(mode="json") for bar in bars],
            }
        ).removeprefix("sha256:")[:16]
        content = {
            "dataset_id": f"kraken-{symbol}-{interval.value}-{identity}",
            "provenance": QuantMarketDataProvenance.PROVIDER_FETCH.value,
            "symbol": symbol,
            "interval": interval.value,
            "covered_start": bars[0].timestamp,
            "covered_end": bars[-1].timestamp,
            "market_calendar": QuantMarketCalendar.CONTINUOUS.value,
            "market_session": QuantMarketSession.CONTINUOUS.value,
            "time_zone": "UTC",
            "periods_per_year": periods_per_year_for(
                calendar=QuantMarketCalendar.CONTINUOUS,
                interval=interval,
            ),
            "schema_version": QUANT_MARKET_BAR_SCHEMA_VERSION,
            "bars": [bar.model_dump(mode="json") for bar in bars],
        }
        return QuantMarketBarDataset.model_validate(
            {**content, "digest": QuantMarketBarDataset.digest_for(content)}
        )


def _cadence_quality(
    bars: tuple[QuantMarketBar, ...], *, interval_delta: timedelta
) -> KrakenMarketCadenceQuality:
    gap_count = sum(
        1
        for left, right in zip(bars, bars[1:], strict=False)
        if right.timestamp - left.timestamp != interval_delta
    )
    return KrakenMarketCadenceQuality(
        status="blocked" if gap_count else "accepted",
        cadence_gap_count=gap_count,
        normalization_note=(
            "No cadence gaps detected."
            if not gap_count
            else "Cadence gaps were retained without filling; research remains unavailable."
        ),
    )
