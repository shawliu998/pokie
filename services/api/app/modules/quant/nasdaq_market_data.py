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
NASDAQ_USER_AGENT = "Qurio/0.1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_HISTORY_LIMIT = 5_000
DEFAULT_HISTORY_DAYS = 730
_SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,15}$")
_SPLIT_RATIO_PATTERN = re.compile(
    r"^(?P<numerator>[0-9]+(?:\.[0-9]+)?)\s*:\s*(?P<denominator>[0-9]+(?:\.[0-9]+)?)$"
)


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
    splits_response_digest: str
    retrieved_at: datetime
    source_reference: str
    bar_count: int
    dividend_row_count: int
    dividend_coverage_start: str | None
    dividend_coverage_end: str | None
    price_adjustment: str
    split_verification_note: str
    split_snapshot_as_of: date
    split_coverage_start: date
    split_coverage_end: date
    split_event_count: int
    split_events: tuple[NasdaqSplitEvent, ...]
    exchange: str
    company_name: str


@dataclass(frozen=True, slots=True)
class NasdaqSplitEvent:
    symbol: str
    ratio: str
    execution_date: date


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
        splits_raw = self._request(
            f"{NASDAQ_API_BASE_URL}/api/calendar/splits",
            params={},
        )
        historical_rows = self._historical_rows(historical_raw)
        dividend_rows = self._dividend_rows(dividend_raw)
        split_snapshot_as_of, all_split_dates, split_events = self._split_events(
            splits_raw, normalized_symbol
        )
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
            splits_response_digest="sha256:" + hashlib.sha256(splits_raw).hexdigest(),
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
            split_verification_note=(
                "Split events are a point-in-time Nasdaq calendar snapshot; "
                "historical completeness is not asserted."
            ),
            split_snapshot_as_of=split_snapshot_as_of,
            split_coverage_start=min((split_snapshot_as_of, *all_split_dates)),
            split_coverage_end=max((split_snapshot_as_of, *all_split_dates)),
            split_event_count=len(split_events),
            split_events=split_events,
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

    def _split_events(
        self, raw: bytes, symbol: str
    ) -> tuple[date, list[date], tuple[NasdaqSplitEvent, ...]]:
        value = self._json_object(raw)
        data = value.get("data")
        as_of_raw = data.get("asOf") if isinstance(data, dict) else None
        rows = data.get("rows") if isinstance(data, dict) else None
        if not isinstance(as_of_raw, str):
            raise NasdaqMarketDataError("Nasdaq split calendar snapshot is invalid.")
        try:
            as_of = datetime.strptime(as_of_raw, "%a, %b %d, %Y").date()
        except ValueError:
            raise NasdaqMarketDataError("Nasdaq split calendar snapshot is invalid.") from None
        parsed: list[NasdaqSplitEvent] = []
        all_dates: list[date] = []
        for row in self._rows(rows, "split"):
            raw_symbol = row.get("symbol")
            raw_ratio = row.get("ratio")
            raw_date = row.get("executionDate")
            if (
                not isinstance(raw_symbol, str)
                or not isinstance(raw_ratio, str)
                or not isinstance(raw_date, str)
            ):
                raise NasdaqMarketDataError("Nasdaq split calendar row is invalid.")
            ratio = _normalized_split_ratio(raw_ratio)
            if ratio is None:
                raise NasdaqMarketDataError("Nasdaq split calendar row is invalid.")
            try:
                execution_date = datetime.strptime(raw_date.strip(), "%m/%d/%Y").date()
            except ValueError:
                raise NasdaqMarketDataError("Nasdaq split calendar row is invalid.") from None
            all_dates.append(execution_date)
            if raw_symbol.strip().upper() == symbol:
                parsed.append(
                    NasdaqSplitEvent(
                        symbol=symbol, ratio=ratio, execution_date=execution_date
                    )
                )
        parsed.sort(key=lambda item: (item.execution_date, item.ratio))
        if len({(item.symbol, item.execution_date) for item in parsed}) != len(parsed):
            raise NasdaqMarketDataError("Nasdaq split calendar contained duplicate symbol dates.")
        return as_of, all_dates, tuple(parsed)

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


def _normalized_split_ratio(value: str) -> str | None:
    match = _SPLIT_RATIO_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    try:
        numerator = Decimal(match.group("numerator"))
        denominator = Decimal(match.group("denominator"))
    except InvalidOperation:
        return None
    if (
        not numerator.is_finite()
        or not denominator.is_finite()
        or numerator <= 0
        or denominator <= 0
    ):
        return None
    return f"{format(numerator.normalize(), 'f')}:{format(denominator.normalize(), 'f')}"
