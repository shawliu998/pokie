"""Small, credential-free Binance Vision daily-kline client."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Protocol

import httpx

BINANCE_DATA_API_BASE_URL = "https://data-api.binance.vision"
BINANCE_KLINES_PATH = "/api/v3/klines"
BINANCE_DAILY_INTERVAL = "1d"
MIN_KLINES_LIMIT = 252
MAX_KLINES_LIMIT = 1_000
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{4,15}$")
_UTC_DAY_MS = 86_400_000


class BinanceMarketDataError(ValueError):
    """Safe validation or transport error without provider response disclosure."""


class BinanceTransport(Protocol):
    def get(self, url: str, **kwargs: object) -> httpx.Response: ...


@dataclass(frozen=True, slots=True)
class BinanceDailyBarsResult:
    csv_text: str
    provider_response_digest: str
    retrieved_at: datetime
    source_reference: str
    bar_count: int
    requested_limit: int
    returned_bar_count: int
    dropped_incomplete_count: int
    normalization_note: str


class BinanceMarketDataClient:
    """Fetch bounded UTC daily klines from the public Binance Vision endpoint."""

    def __init__(
        self,
        transport: BinanceTransport | None = None,
        *,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._transport = transport
        self._timeout_seconds = timeout_seconds

    def fetch_daily_klines(self, *, symbol: str, limit: int) -> BinanceDailyBarsResult:
        normalized_symbol = symbol.strip().upper()
        if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
            raise BinanceMarketDataError("Binance symbol is invalid.")
        if not MIN_KLINES_LIMIT <= limit <= MAX_KLINES_LIMIT:
            raise BinanceMarketDataError(
                "Binance daily kline limit must be from 252 to 1000."
            )
        response = self._get(
            BINANCE_DATA_API_BASE_URL + BINANCE_KLINES_PATH,
            params={
                "symbol": normalized_symbol,
                "interval": BINANCE_DAILY_INTERVAL,
                "limit": limit,
            },
        )
        if response.status_code != 200:
            raise BinanceMarketDataError("Binance market-data request failed safely.")
        raw = response.content
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BinanceMarketDataError(
                "Binance market-data response exceeded the byte limit."
            )
        try:
            payload = json.loads(raw)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise BinanceMarketDataError(
                "Binance market-data response was not valid JSON."
            ) from None
        if not isinstance(payload, list):
            raise BinanceMarketDataError(
                "Binance market-data response must be a list."
            )
        retrieved_at = datetime.now(tz=UTC)
        fetched_at_ms = int(retrieved_at.timestamp() * 1000)
        complete_rows = [row for row in payload if not self._is_incomplete(row, fetched_at_ms)]
        rows = [self._parse_row(row) for row in complete_rows]
        if not rows:
            raise BinanceMarketDataError("Binance market-data response contained no closed bars.")
        if len(rows) > limit:
            raise BinanceMarketDataError(
                "Binance market-data response exceeded the requested limit."
            )
        rows.sort(key=lambda row: row[0])
        if len({row[0] for row in rows}) != len(rows):
            raise BinanceMarketDataError(
                "Binance market-data response contained duplicate UTC dates."
            )
        csv_rows = ["date,open,high,low,close,volume"]
        csv_rows.extend(
            f"{day},{open_},{high},{low},{close},{volume}"
            for day, open_, high, low, close, volume in rows
        )
        return BinanceDailyBarsResult(
            csv_text="\n".join(csv_rows) + "\n",
            provider_response_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
            retrieved_at=retrieved_at,
            source_reference=(
                f"binance-vision:{BINANCE_KLINES_PATH}?symbol={normalized_symbol}"
                f"&interval={BINANCE_DAILY_INTERVAL}&limit={limit}"
            ),
            bar_count=len(rows),
            requested_limit=limit,
            returned_bar_count=len(rows),
            dropped_incomplete_count=len(payload) - len(complete_rows),
            normalization_note=(
                "Volume is Binance base-asset volume rounded to the nearest integer "
                "using decimal half-up rounding for the existing integer-volume CSV contract."
            ),
        )

    def _get(self, url: str, *, params: dict[str, str | int]) -> httpx.Response:
        try:
            if self._transport is not None:
                return self._transport.get(
                    url,
                    params=params,
                    timeout=httpx.Timeout(self._timeout_seconds),
                    follow_redirects=False,
                )
            with httpx.Client(
                timeout=httpx.Timeout(self._timeout_seconds), follow_redirects=False
            ) as client:
                return client.get(url, params=params)
        except httpx.HTTPError:
            raise BinanceMarketDataError("Binance market-data request failed safely.") from None

    @staticmethod
    def _is_incomplete(row: object, fetched_at_ms: int) -> bool:
        if not isinstance(row, list) or len(row) < 12:
            raise BinanceMarketDataError("Binance kline rows must contain at least 12 values.")
        close_time = row[6]
        if not isinstance(close_time, int) or isinstance(close_time, bool) or close_time < 0:
            raise BinanceMarketDataError("Binance kline close time is invalid.")
        return close_time >= fetched_at_ms

    @staticmethod
    def _parse_row(row: object) -> tuple[str, str, str, str, str, int]:
        if not isinstance(row, list) or len(row) < 12:
            raise BinanceMarketDataError("Binance kline rows must contain at least 12 values.")
        open_time = row[0]
        if not isinstance(open_time, int) or isinstance(open_time, bool) or open_time < 0:
            raise BinanceMarketDataError("Binance kline open time is invalid.")
        if open_time % _UTC_DAY_MS:
            raise BinanceMarketDataError("Binance kline open time must be a UTC day boundary.")
        try:
            day = datetime.fromtimestamp(open_time / 1000, tz=UTC).date().isoformat()
            volume = int(Decimal(str(row[5])).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, OverflowError, ValueError):
            raise BinanceMarketDataError("Binance kline volume is invalid.") from None
        if volume < 0:
            raise BinanceMarketDataError("Binance kline volume is invalid.")
        # Price validation intentionally remains with parse_ohlcv_csv/QuantDailyBar.
        values = tuple(str(row[index]) for index in (1, 2, 3, 4))
        return (day, *values, volume)
