"""Credential-free Nasdaq historical-price and dividend client."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

NASDAQ_API_BASE_URL = "https://api.nasdaq.com"
NASDAQ_USER_AGENT = "PokieQuant/0.1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_HISTORY_LIMIT = 5_000
DEFAULT_HISTORY_DAYS = 730
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")


class NasdaqMarketDataError(ValueError):
    """Safe public error that excludes upstream bodies and request details."""


class NasdaqTransport(Protocol):
    def get(self, url: str, **kwargs: object) -> httpx.Response: ...


@dataclass(frozen=True, slots=True)
class NasdaqDailyBarsResult:
    csv_text: str
    info_response_digest: str
    historical_response_digest: str
    dividends_response_digest: str
    retrieved_at: datetime
    source_reference: str
    bar_count: int
    dividend_row_count: int
    dividend_coverage_start: str | None
    dividend_coverage_end: str | None
    price_adjustment: str
    split_verification_note: str
    exchange: str
    company_name: str


class NasdaqMarketDataClient:
    def __init__(
        self,
        transport: NasdaqTransport | None = None,
        *,
        timeout_seconds: float = 15.0,
        today: date | None = None,
    ) -> None:
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._today = today

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = MAX_HISTORY_LIMIT,
    ) -> NasdaqDailyBarsResult:
        normalized_symbol = symbol.strip().upper()
        if not _SYMBOL_PATTERN.fullmatch(normalized_symbol):
            raise NasdaqMarketDataError("Nasdaq symbol is invalid.")
        if not 1 <= limit <= MAX_HISTORY_LIMIT:
            raise NasdaqMarketDataError("Nasdaq history limit must be from 1 to 5000.")
        resolved_to = to_date or (self._today or datetime.now(tz=UTC).date()) - timedelta(days=1)
        resolved_from = from_date or resolved_to - timedelta(days=DEFAULT_HISTORY_DAYS)
        if resolved_from > resolved_to:
            raise NasdaqMarketDataError("Nasdaq history date range is invalid.")
        info_raw = self._request(
            f"{NASDAQ_API_BASE_URL}/api/quote/{normalized_symbol}/info",
            params={"assetclass": "stocks"},
        )
        company_name, exchange = self._validate_info(info_raw, normalized_symbol)
        historical_raw = self._request(
            f"{NASDAQ_API_BASE_URL}/api/quote/{normalized_symbol}/historical",
            params={
                "assetclass": "stocks",
                "fromdate": resolved_from.isoformat(),
                "todate": resolved_to.isoformat(),
                "limit": limit,
            },
        )
        dividend_raw = self._request(
            f"{NASDAQ_API_BASE_URL}/api/quote/{normalized_symbol}/dividends",
            params={"assetclass": "stocks"},
        )
        historical_rows = self._historical_rows(historical_raw)
        dividend_rows = self._dividend_rows(dividend_raw)
        bars = [self._parse_bar(row) for row in historical_rows]
        if len(bars) > limit:
            raise NasdaqMarketDataError(
                "Nasdaq historical response exceeded the requested limit."
            )
        bars.sort(key=lambda item: item[0])
        if len({item[0] for item in bars}) != len(bars):
            raise NasdaqMarketDataError("Nasdaq historical response contained duplicate dates.")
        if not bars:
            raise NasdaqMarketDataError("Nasdaq historical response contained no bars.")
        csv_rows = ["date,open,high,low,close,volume"]
        csv_rows.extend(
            f"{day},{open_},{high},{low},{close},{volume}"
            for day, open_, high, low, close, volume in bars
        )
        coverage = sorted(self._dividend_date(row) for row in dividend_rows)
        return NasdaqDailyBarsResult(
            csv_text="\n".join(csv_rows) + "\n",
            info_response_digest="sha256:" + hashlib.sha256(info_raw).hexdigest(),
            historical_response_digest="sha256:" + hashlib.sha256(historical_raw).hexdigest(),
            dividends_response_digest="sha256:" + hashlib.sha256(dividend_raw).hexdigest(),
            retrieved_at=datetime.now(tz=UTC),
            source_reference=(
                f"nasdaq:{normalized_symbol}:historical?assetclass=stocks&fromdate="
                f"{resolved_from.isoformat()}&todate={resolved_to.isoformat()}&limit={limit}"
            ),
            bar_count=len(bars),
            dividend_row_count=len(dividend_rows),
            dividend_coverage_start=coverage[0].isoformat() if coverage else None,
            dividend_coverage_end=coverage[-1].isoformat() if coverage else None,
            price_adjustment="unadjusted",
            split_verification_note="Split verification is unavailable from this bounded client.",
            exchange=exchange,
            company_name=company_name,
        )

    def _request(self, url: str, *, params: dict[str, str | int]) -> bytes:
        try:
            kwargs: dict[str, object] = {
                "params": params,
                "headers": {"User-Agent": NASDAQ_USER_AGENT, "Accept": "application/json"},
                "timeout": httpx.Timeout(self._timeout_seconds),
                "follow_redirects": False,
            }
            if self._transport is not None:
                response = self._transport.get(url, **kwargs)
            else:
                with httpx.Client(
                    timeout=httpx.Timeout(self._timeout_seconds), follow_redirects=False
                ) as client:
                    response = client.get(url, params=params, headers=kwargs["headers"])
            if response.status_code != 200:
                raise NasdaqMarketDataError("Nasdaq market-data request failed safely.")
            raw = response.content
        except httpx.HTTPError:
            raise NasdaqMarketDataError("Nasdaq market-data request failed safely.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise NasdaqMarketDataError("Nasdaq market-data response exceeded the byte limit.")
        return raw

    @staticmethod
    def _json_object(raw: bytes) -> dict[str, object]:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise NasdaqMarketDataError("Nasdaq market-data response was not valid JSON.") from None
        if not isinstance(value, dict):
            raise NasdaqMarketDataError("Nasdaq market-data response must be an object.")
        status = value.get("status")
        if not isinstance(status, dict) or status.get("rCode") != 200:
            raise NasdaqMarketDataError("Nasdaq market-data response status was invalid.")
        return value

    def _historical_rows(self, raw: bytes) -> list[dict[str, object]]:
        value = self._json_object(raw)
        data = value.get("data")
        table = data.get("tradesTable") if isinstance(data, dict) else None
        rows = table.get("rows") if isinstance(table, dict) else None
        return self._rows(rows, "historical")

    def _validate_info(self, raw: bytes, symbol: str) -> tuple[str, str]:
        value = self._json_object(raw)
        data = value.get("data")
        if not isinstance(data, dict):
            raise NasdaqMarketDataError("Nasdaq instrument information is invalid.")
        response_symbol = data.get("symbol")
        asset_class = data.get("assetClass")
        listed = data.get("isNasdaqListed")
        exchange = data.get("exchange")
        company_name = data.get("companyName")
        if (
            not isinstance(response_symbol, str)
            or response_symbol.upper() != symbol
            or asset_class != "STOCKS"
            or listed is not True
            or not isinstance(exchange, str)
            or not exchange.strip()
            or not exchange.upper().startswith("NASDAQ")
            or not isinstance(company_name, str)
            or not company_name.strip()
        ):
            raise NasdaqMarketDataError("Nasdaq instrument information is invalid.")
        return company_name.strip(), exchange.strip()

    def _dividend_rows(self, raw: bytes) -> list[dict[str, object]]:
        value = self._json_object(raw)
        data = value.get("data")
        dividends = data.get("dividends") if isinstance(data, dict) else None
        rows = dividends.get("rows") if isinstance(dividends, dict) else None
        return self._rows(rows, "dividend")

    @staticmethod
    def _rows(value: object, kind: str) -> list[dict[str, object]]:
        if not isinstance(value, list):
            raise NasdaqMarketDataError(f"Nasdaq {kind} response rows are invalid.")
        if not all(isinstance(row, dict) for row in value):
            raise NasdaqMarketDataError(f"Nasdaq {kind} response rows are invalid.")
        return list(value)

    @staticmethod
    def _parse_bar(row: dict[str, object]) -> tuple[date, str, str, str, str, int]:
        try:
            day = datetime.strptime(str(row["date"]), "%m/%d/%Y").date()
            open_ = _decimal_text(row["open"])
            high = _decimal_text(row["high"])
            low = _decimal_text(row["low"])
            close = _decimal_text(row["close"])
            volume = _integer(row["volume"])
        except (KeyError, ValueError):
            raise NasdaqMarketDataError("Nasdaq historical row is invalid.") from None
        return day, open_, high, low, close, volume

    @staticmethod
    def _dividend_date(row: dict[str, object]) -> date:
        raw = row.get("exOrEffDate", row.get("exDate", row.get("date")))
        if raw is None:
            raise NasdaqMarketDataError("Nasdaq dividend row is invalid.")
        try:
            return datetime.strptime(str(raw), "%m/%d/%Y").date()
        except ValueError:
            raise NasdaqMarketDataError("Nasdaq dividend row is invalid.") from None


def _decimal_text(value: object) -> str:
    text = str(value).strip().replace("$", "").replace(",", "")
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        raise ValueError("not decimal") from None
    if not parsed.is_finite():
        raise ValueError("not finite")
    return format(parsed, "f")


def _integer(value: object) -> int:
    text = str(value).strip().replace(",", "")
    try:
        parsed = Decimal(text)
    except InvalidOperation:
        raise ValueError("not integer") from None
    if not parsed.is_finite() or parsed != parsed.to_integral_value() or parsed < 0:
        raise ValueError("not integer")
    return int(parsed)
