from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import httpx
import pytest

from packages.contracts.quant import QuantBarInterval
from packages.domain.canonical import canonical_digest
from services.api.app.modules.quant import binance_market_data_v2 as module
from services.api.app.modules.quant.binance_market_data_v2 import (
    BinanceMarketDataV2Client,
    BinanceMarketDataV2Error,
)


class _Transport:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, str | int]] = []

    def get(self, url: str, **kwargs: object) -> httpx.Response:
        del url
        self.calls.append(dict(kwargs["params"]))  # type: ignore[arg-type]
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _row(
    open_ms: int,
    interval_ms: int,
    *,
    open_price: str = "100",
    high: str = "102",
    low: str = "99",
    close: str = "101",
    volume: str = "12.34567890",
) -> list[object]:
    return [
        open_ms,
        open_price,
        high,
        low,
        close,
        volume,
        open_ms + interval_ms - 1,
        "0",
        1,
        "0",
        "0",
        "0",
    ]


def _client(
    transport: _Transport,
    *,
    page_size: int = 1000,
    clock: Callable[[], datetime] | None = None,
) -> BinanceMarketDataV2Client:
    return BinanceMarketDataV2Client(
        transport,
        page_size=page_size,
        clock=clock or (lambda: datetime(2025, 1, 1, tzinfo=UTC)),
    )


@pytest.mark.parametrize(
    ("interval", "interval_ms", "expected_ppy"),
    [
        (QuantBarInterval.HOUR, 3_600_000, 8760),
        (QuantBarInterval.FOUR_HOURS, 14_400_000, 2190),
        (QuantBarInterval.DAILY, 86_400_000, 365),
    ],
)
def test_fetches_closed_v2_binance_bars_for_each_supported_interval(
    interval: QuantBarInterval, interval_ms: int, expected_ppy: int
) -> None:
    raw = json.dumps([_row(0, interval_ms), _row(interval_ms, interval_ms)]).encode()
    transport = _Transport([httpx.Response(200, content=raw)])

    result = _client(transport).fetch_market_bars(symbol="btcusdt", interval=interval, limit=2)

    assert result.dataset.interval is interval
    assert result.dataset.provenance == "provider_fetch"
    assert result.dataset.periods_per_year == expected_ppy
    assert result.dataset.bars[0].volume.as_tuple().exponent == -8
    assert result.quality.status == "accepted"
    assert result.evidence.retrieved_at_utc == datetime(2025, 1, 1, tzinfo=UTC)
    assert result.evidence.returned_bar_count == 2
    assert result.evidence.retained_bar_count == 2
    assert result.evidence.termination_reason == "requested_limit"
    assert result.evidence.target_satisfied is True
    assert len(result.evidence.page_raw_sha256) == 1
    assert result.evidence.batch_digest.startswith("sha256:")
    assert transport.calls[0]["interval"] in {"1h", "4h", "1d"}


def test_accepts_eight_decimal_binance_prices() -> None:
    interval_ms = 3_600_000
    raw = json.dumps(
        [
            _row(
                0,
                interval_ms,
                open_price="100.12345678",
                high="102.12345678",
                low="99.12345678",
                close="101.12345678",
            )
        ]
    ).encode()

    result = _client(_Transport([httpx.Response(200, content=raw)])).fetch_market_bars(
        symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
    )

    assert str(result.dataset.bars[0].close) == "101.12345678"


def test_pages_backward_with_end_time_and_deduplicates_identical_overlap() -> None:
    interval_ms = 3_600_000
    first = [_row(2 * interval_ms, interval_ms), _row(3 * interval_ms, interval_ms)]
    second = [_row(interval_ms, interval_ms), _row(2 * interval_ms, interval_ms)]
    transport = _Transport(
        [
            httpx.Response(200, content=json.dumps(first).encode()),
            httpx.Response(200, content=json.dumps(second).encode()),
            httpx.Response(200, content=b"[]"),
        ]
    )

    result = _client(transport, page_size=2).fetch_market_bars(
        symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=4
    )

    assert [bar.timestamp.hour for bar in result.dataset.bars] == [1, 2, 3]
    assert result.evidence.deduplicated_count == 1
    assert result.evidence.returned_bar_count == 4
    assert result.evidence.retained_bar_count == 3
    assert result.evidence.termination_reason == "history_exhausted"
    assert result.evidence.target_satisfied is False
    assert transport.calls[1]["endTime"] == 2 * interval_ms - 1


def test_deduplicates_economically_identical_rows_with_different_decimal_formatting() -> None:
    interval_ms = 3_600_000
    first = [_row(2 * interval_ms, interval_ms), _row(3 * interval_ms, interval_ms)]
    formatted_overlap = _row(
        2 * interval_ms,
        interval_ms,
        open_price="100.0",
        high="102.00",
        low="99.000",
        close="101.0",
        volume="12.345678900",
    )
    second = [_row(interval_ms, interval_ms), formatted_overlap]
    transport = _Transport(
        [
            httpx.Response(200, content=json.dumps(first).encode()),
            httpx.Response(200, content=json.dumps(second).encode()),
            httpx.Response(200, content=b"[]"),
        ]
    )

    result = _client(transport, page_size=2).fetch_market_bars(
        symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=4
    )

    assert result.evidence.deduplicated_count == 1
    assert result.evidence.retained_bar_count == 3


def test_rejects_conflicting_cross_page_overlap() -> None:
    interval_ms = 3_600_000
    first = [_row(2 * interval_ms, interval_ms), _row(3 * interval_ms, interval_ms)]
    conflict = _row(2 * interval_ms, interval_ms, volume="99")
    second = [_row(interval_ms, interval_ms), conflict]
    transport = _Transport(
        [
            httpx.Response(200, content=json.dumps(first).encode()),
            httpx.Response(200, content=json.dumps(second).encode()),
        ]
    )

    with pytest.raises(BinanceMarketDataV2Error, match="conflicting duplicate"):
        _client(transport, page_size=2).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=4
        )


def test_rejects_a_backward_pagination_page_that_does_not_advance() -> None:
    interval_ms = 3_600_000
    repeated_page = [_row(2 * interval_ms, interval_ms), _row(3 * interval_ms, interval_ms)]
    transport = _Transport(
        [
            httpx.Response(200, content=json.dumps(repeated_page).encode()),
            httpx.Response(200, content=json.dumps(repeated_page).encode()),
        ]
    )

    with pytest.raises(BinanceMarketDataV2Error, match="did not advance backward"):
        _client(transport, page_size=2).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=4
        )


def test_stops_at_the_five_page_cap_without_unbounded_pagination() -> None:
    interval_ms = 3_600_000
    pages: list[httpx.Response | Exception] = [
        httpx.Response(200, content=json.dumps([_row(open_ms, interval_ms)]).encode())
        for open_ms in range(5 * interval_ms, 0, -interval_ms)
    ]
    transport = _Transport(pages)

    result = _client(transport, page_size=1).fetch_market_bars(
        symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=6
    )

    assert len(transport.calls) == 5
    assert len(result.dataset.bars) == 5
    assert result.evidence.returned_bar_count == 5
    assert result.evidence.retained_bar_count == 5
    assert result.evidence.termination_reason == "page_cap"
    assert result.evidence.target_satisfied is False


def test_normalizes_reverse_ordered_pages_and_stops_on_a_short_history_page() -> None:
    interval_ms = 3_600_000
    newest_page = [_row(3 * interval_ms, interval_ms), _row(2 * interval_ms, interval_ms)]
    oldest_short_page = [_row(interval_ms, interval_ms)]
    transport = _Transport(
        [
            httpx.Response(200, content=json.dumps(newest_page).encode()),
            httpx.Response(200, content=json.dumps(oldest_short_page).encode()),
        ]
    )

    result = _client(transport, page_size=2).fetch_market_bars(
        symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=4
    )

    assert [bar.timestamp.hour for bar in result.dataset.bars] == [1, 2, 3]
    assert result.evidence.termination_reason == "history_exhausted"
    assert result.evidence.target_satisfied is False


def test_drops_current_unclosed_bar_and_blocks_cadence_gaps() -> None:
    interval_ms = 3_600_000
    captured_ms = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000)
    payload = [
        _row(0, interval_ms),
        _row(2 * interval_ms, interval_ms),
        _row(captured_ms // interval_ms * interval_ms, interval_ms),
    ]
    transport = _Transport([httpx.Response(200, content=json.dumps(payload).encode())])

    result = _client(transport).fetch_market_bars(
        symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=3
    )

    assert result.evidence.closed_dropped_count == 1
    assert result.quality.status == "blocked"
    assert result.quality.cadence_gap_count == 1


def test_drops_a_bar_whose_close_time_equals_the_captured_time() -> None:
    interval_ms = 3_600_000
    captured_at = datetime(2025, 1, 1, 2, 59, 59, 999_000, tzinfo=UTC)
    day_start_ms = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp()) * 1_000
    payload = [
        _row(day_start_ms, interval_ms),
        _row(day_start_ms + interval_ms, interval_ms),
        _row(day_start_ms + 2 * interval_ms, interval_ms),
    ]
    result = _client(
        _Transport(
            [
                httpx.Response(200, content=json.dumps(payload).encode()),
                httpx.Response(200, content=b"[]"),
            ]
        ),
        clock=lambda: captured_at,
    ).fetch_market_bars(symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=3)

    assert result.evidence.closed_dropped_count == 1
    assert result.evidence.retained_bar_count == 2


@pytest.mark.parametrize(
    "clock",
    [
        lambda: datetime(2025, 1, 1),
        lambda: datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=8))),
        lambda: datetime(2025, 1, 1, tzinfo=timezone(timedelta(0), name="UTC+00")),
    ],
)
def test_rejects_naive_or_noncanonical_utc_clocks(clock: Callable[[], datetime]) -> None:
    with pytest.raises(BinanceMarketDataV2Error, match="clock must return a UTC"):
        _client(_Transport([]), clock=clock).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"not": "a list"},
        [[0]],
        [_row(1, 3_600_000)],
        [[0, "100", "102", "99", "101", "1", 3_599_998, "0", 1, "0", "0", "0"]],
    ],
)
def test_rejects_malformed_or_unaligned_binance_v2_rows(payload: object) -> None:
    transport = _Transport([httpx.Response(200, content=json.dumps(payload).encode())])
    with pytest.raises(BinanceMarketDataV2Error):
        _client(transport).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
        )


@pytest.mark.parametrize(
    "row",
    [
        _row(0, 3_600_000, open_price="NaN"),
        _row(0, 3_600_000, high="Infinity"),
        _row(0, 3_600_000, volume="-1"),
        _row(0, 3_600_000, high="100"),
        _row(0, 3_600_000, low="101"),
    ],
)
def test_rejects_nonfinite_negative_or_invalid_binance_v2_ohlcv_bounds(row: list[object]) -> None:
    transport = _Transport([httpx.Response(200, content=json.dumps([row]).encode())])
    with pytest.raises(BinanceMarketDataV2Error, match="OHLCV values are invalid"):
        _client(transport).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
        )


def test_rejects_network_and_page_or_total_byte_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(BinanceMarketDataV2Error, match="failed safely"):
        _client(_Transport([httpx.ConnectError("offline")])).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
        )

    oversized = b"[" + b" " * 20 + b"]"
    monkeypatch.setattr(module, "MAX_BINANCE_V2_PAGE_BYTES", 4)
    with pytest.raises(BinanceMarketDataV2Error, match="page byte limit"):
        _client(_Transport([httpx.Response(200, content=oversized)])).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
        )

    monkeypatch.setattr(module, "MAX_BINANCE_V2_PAGE_BYTES", 100)
    monkeypatch.setattr(module, "MAX_BINANCE_V2_TOTAL_BYTES", 1)
    with pytest.raises(BinanceMarketDataV2Error, match="total byte limit"):
        _client(_Transport([httpx.Response(200, content=b"[]")])).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
        )


def test_rejects_cumulative_multi_page_total_byte_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    interval_ms = 3_600_000
    raw = json.dumps([_row(2 * interval_ms, interval_ms)]).encode()
    second_raw = json.dumps([_row(interval_ms, interval_ms)]).encode()
    monkeypatch.setattr(module, "MAX_BINANCE_V2_PAGE_BYTES", len(raw) + 1)
    monkeypatch.setattr(module, "MAX_BINANCE_V2_TOTAL_BYTES", len(raw) + len(second_raw) - 1)
    transport = _Transport(
        [
            httpx.Response(200, content=raw),
            httpx.Response(200, content=second_raw),
        ]
    )

    with pytest.raises(BinanceMarketDataV2Error, match="total byte limit"):
        _client(transport, page_size=1).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=2
        )


def test_rejects_invalid_json_without_disclosing_payload() -> None:
    with pytest.raises(BinanceMarketDataV2Error, match="valid JSON"):
        _client(_Transport([httpx.Response(200, content=b"not-json")])).fetch_market_bars(
            symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
        )


def test_batch_digest_changes_with_evidence_counts() -> None:
    interval_ms = 3_600_000
    closed = json.dumps([_row(0, interval_ms)]).encode()
    current = json.dumps(
        [_row(int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1000), interval_ms)]
    ).encode()
    first = _client(_Transport([httpx.Response(200, content=closed)])).fetch_market_bars(
        symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
    )
    second_transport = _Transport(
        [httpx.Response(200, content=closed), httpx.Response(200, content=current)]
    )
    second = _client(second_transport).fetch_market_bars(
        symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=2
    )

    assert first.evidence.batch_digest != second.evidence.batch_digest


def test_batch_digest_covers_retention_and_completion_semantics() -> None:
    interval_ms = 3_600_000
    raw = json.dumps([_row(0, interval_ms)]).encode()
    result = _client(_Transport([httpx.Response(200, content=raw)])).fetch_market_bars(
        symbol="BTCUSDT", interval=QuantBarInterval.HOUR, limit=1
    )
    evidence = result.evidence
    content: dict[str, object] = {
        "source_reference": evidence.source_reference,
        "retrieved_at_utc": evidence.retrieved_at_utc,
        "requested_bar_count": evidence.requested_bar_count,
        "returned_bar_count": evidence.returned_bar_count,
        "retained_bar_count": evidence.retained_bar_count,
        "closed_dropped_count": evidence.closed_dropped_count,
        "deduplicated_count": evidence.deduplicated_count,
        "termination_reason": evidence.termination_reason.value,
        "target_satisfied": evidence.target_satisfied,
        "page_raw_sha256": list(evidence.page_raw_sha256),
        "normalizer_version": evidence.normalizer_version,
    }

    assert evidence.batch_digest == canonical_digest(content)
    content["termination_reason"] = "history_exhausted"
    assert evidence.batch_digest != canonical_digest(content)
    content["termination_reason"] = evidence.termination_reason.value
    content["target_satisfied"] = False
    assert evidence.batch_digest != canonical_digest(content)
    content["target_satisfied"] = evidence.target_satisfied
    content["retained_bar_count"] = 0
    assert evidence.batch_digest != canonical_digest(content)
