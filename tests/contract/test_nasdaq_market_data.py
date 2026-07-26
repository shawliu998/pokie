from __future__ import annotations

import json
from datetime import UTC, date

import httpx
import pytest

from services.api.app.modules.quant.nasdaq_market_data import (
    NASDAQ_USER_AGENT,
    NasdaqMarketDataClient,
    NasdaqMarketDataError,
)


class _Transport:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _historical(rows: list[dict[str, object]]) -> bytes:
    return json.dumps({"data": {"tradesTable": {"rows": rows}}, "status": {"rCode": 200}}).encode()


def _dividends(rows: list[dict[str, object]]) -> bytes:
    return json.dumps({"data": {"dividends": {"rows": rows}}, "status": {"rCode": 200}}).encode()


def _info() -> bytes:
    return json.dumps(
        {
            "data": {
                "symbol": "MSFT",
                "assetClass": "STOCKS",
                "isNasdaqListed": True,
                "exchange": "NASDAQ",
                "companyName": "Microsoft",
            },
            "status": {"rCode": 200},
        },
    ).encode()


def _splits(rows: list[dict[str, object]] | None = None) -> bytes:
    return json.dumps(
        {"data": {"asOf": "Fri, Jul 17, 2026", "rows": rows or []}, "status": {"rCode": 200}}
    ).encode()


def _row(day: str = "01/03/2024") -> dict[str, object]:
    return {
        "date": day,
        "open": "$100.00",
        "high": "$102",
        "low": "$99",
        "close": "$101",
        "volume": "1,234",
    }


def test_fetches_parses_and_sends_transparent_user_agent() -> None:
    transport = _Transport(
        [
            httpx.Response(200, content=_info()),
            httpx.Response(200, content=_historical([_row("01/03/2024"), _row("01/02/2024")])),
            httpx.Response(200, content=_dividends([{"exOrEffDate": "01/01/2024"}])),
            httpx.Response(
                200,
                content=_splits(
                    [
                        {"symbol": "MSFT", "ratio": "1.5 : 1", "executionDate": "07/20/2026"},
                        {"symbol": "OTHER", "ratio": "0.5:1", "executionDate": "07/19/2026"},
                    ]
                ),
            ),
        ]
    )
    result = NasdaqMarketDataClient(transport, today=date(2024, 12, 31)).fetch_daily_bars(
        symbol="msft", limit=5000
    )

    assert result.csv_text.splitlines()[1] == "2024-01-02,100.00,102,99,101,1234"
    assert result.dividend_row_count == 1
    assert result.dividend_coverage_start == "2024-01-01"
    assert result.price_adjustment == "unadjusted"
    assert result.exchange == "NASDAQ"
    assert result.company_name == "Microsoft"
    assert result.info_response_digest.startswith("sha256:")
    assert result.split_events[0].ratio == "1.5:1"
    assert result.split_event_count == 1
    assert result.split_coverage_start.isoformat() == "2026-07-17"
    assert result.split_coverage_end.isoformat() == "2026-07-20"
    assert result.retrieved_at.tzinfo is UTC
    assert transport.calls[0][1]["headers"] == {
        "User-Agent": NASDAQ_USER_AGENT,
        "Accept": "application/json",
    }
    assert transport.calls[1][1]["params"] == {
        "assetclass": "stocks",
        "fromdate": "2022-12-31",
        "todate": "2024-12-30",
        "limit": 5000,
    }
    assert transport.calls[3][0].endswith("/api/calendar/splits")
    assert transport.calls[3][1]["params"] == {}


@pytest.mark.parametrize(
    "historical",
    [
        {"data": {"tradesTable": {"rows": "wrong"}}},
        {"data": {"tradesTable": {"rows": [_row(), _row()]}}},
        {"data": {"tradesTable": {"rows": [{**_row(), "open": "N/A"}]}}},
    ],
)
def test_rejects_invalid_rows_and_duplicate_dates(historical: object) -> None:
    transport = _Transport(
        [
            httpx.Response(200, content=_info()),
            httpx.Response(
                200,
                content=json.dumps({**historical, "status": {"rCode": 200}}).encode(),
            ),
            httpx.Response(200, content=_dividends([])),
            httpx.Response(200, content=_splits()),
        ]
    )
    with pytest.raises(NasdaqMarketDataError):
        NasdaqMarketDataClient(transport, today=date(2024, 1, 3)).fetch_daily_bars(
            symbol="MSFT", from_date=date(2024, 1, 1), to_date=date(2024, 1, 3)
        )


def test_rejects_error_or_oversized_provider_response() -> None:
    error_transport = _Transport([httpx.Response(503)])
    with pytest.raises(NasdaqMarketDataError):
        NasdaqMarketDataClient(error_transport).fetch_daily_bars(
            symbol="MSFT", from_date=date(2024, 1, 1), to_date=date(2024, 1, 2)
        )
    oversized = b"x" * (2 * 1024 * 1024 + 1)
    large_transport = _Transport([httpx.Response(200, content=oversized)])
    with pytest.raises(NasdaqMarketDataError):
        NasdaqMarketDataClient(large_transport).fetch_daily_bars(
            symbol="MSFT", from_date=date(2024, 1, 1), to_date=date(2024, 1, 2)
        )


@pytest.mark.parametrize(
    "rows",
    [
        [{"symbol": "MSFT", "ratio": "0:1", "executionDate": "07/20/2026"}],
        [{"symbol": "MSFT", "ratio": "2:1", "executionDate": "2026-07-20"}],
        [
            {"symbol": "MSFT", "ratio": "2:1", "executionDate": "07/20/2026"},
            {"symbol": "MSFT", "ratio": "3:1", "executionDate": "07/20/2026"},
        ],
    ],
)
def test_rejects_invalid_or_duplicate_split_rows(rows: list[dict[str, object]]) -> None:
    transport = _Transport(
        [
            httpx.Response(200, content=_info()),
            httpx.Response(200, content=_historical([_row()])),
            httpx.Response(200, content=_dividends([])),
            httpx.Response(200, content=_splits(rows)),
        ]
    )
    with pytest.raises(NasdaqMarketDataError):
        NasdaqMarketDataClient(transport, today=date(2024, 1, 3)).fetch_daily_bars(
            symbol="MSFT", from_date=date(2024, 1, 1), to_date=date(2024, 1, 3)
        )


def test_allows_an_empty_split_snapshot() -> None:
    transport = _Transport(
        [
            httpx.Response(200, content=_info()),
            httpx.Response(200, content=_historical([_row()])),
            httpx.Response(200, content=_dividends([])),
            httpx.Response(200, content=_splits()),
        ]
    )
    result = NasdaqMarketDataClient(transport, today=date(2024, 1, 3)).fetch_daily_bars(
        symbol="MSFT", from_date=date(2024, 1, 1), to_date=date(2024, 1, 3)
    )
    assert result.split_events == ()
    assert result.split_coverage_start == result.split_snapshot_as_of
    assert result.split_coverage_end == result.split_snapshot_as_of
