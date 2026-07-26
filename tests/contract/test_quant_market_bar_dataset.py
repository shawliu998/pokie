from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.contracts.quant import (
    QUANT_MARKET_BAR_SCHEMA_VERSION,
    QuantBarInterval,
    QuantMarketBar,
    QuantMarketBarDataset,
    QuantMarketCalendar,
    QuantMarketSession,
    daily_bar_dataset_to_market_dataset,
    periods_per_year_for,
)
from packages.contracts.quant.fixture_data import SPY_DAILY_FIXTURE


def _bar(hour: int = 0) -> QuantMarketBar:
    return QuantMarketBar(
        timestamp=datetime(2024, 1, 2, hour, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("1200"),
    )


def _payload(
    *,
    interval: QuantBarInterval = QuantBarInterval.DAILY,
    bars: list[QuantMarketBar] | None = None,
    calendar: QuantMarketCalendar = QuantMarketCalendar.XNYS,
    session: QuantMarketSession = QuantMarketSession.REGULAR,
    periods_per_year: int | None = 252,
    time_zone: str | None = None,
) -> dict[str, object]:
    retained_bars = bars or [
        _bar(),
        _bar().model_copy(update={"timestamp": datetime(2024, 1, 3, tzinfo=UTC)}),
    ]
    resolved_time_zone = time_zone or {
        QuantMarketCalendar.CONTINUOUS: "UTC",
        QuantMarketCalendar.XNYS: "America/New_York",
        QuantMarketCalendar.XNAS: "America/New_York",
        QuantMarketCalendar.XSHG: "Asia/Shanghai",
        QuantMarketCalendar.XSHE: "Asia/Shanghai",
    }.get(calendar, "UTC")
    content: dict[str, object] = {
        "dataset_id": "market-SPY-v2-test",
        "provenance": "imported_fixture",
        "symbol": "SPY",
        "interval": interval.value,
        "covered_start": retained_bars[0].timestamp,
        "covered_end": retained_bars[-1].timestamp,
        "market_calendar": calendar.value,
        "market_session": session.value,
        "time_zone": resolved_time_zone,
        "periods_per_year": periods_per_year,
        "schema_version": QUANT_MARKET_BAR_SCHEMA_VERSION,
        "bars": [bar.model_dump(mode="json") for bar in retained_bars],
    }
    return {**content, "digest": QuantMarketBarDataset.digest_for(content)}


@pytest.mark.parametrize(
    ("interval", "calendar", "session", "periods_per_year", "bars"),
    [
        (
            QuantBarInterval.HOUR,
            QuantMarketCalendar.CONTINUOUS,
            QuantMarketSession.CONTINUOUS,
            8760,
            [_bar(0), _bar(1)],
        ),
        (
            QuantBarInterval.FOUR_HOURS,
            QuantMarketCalendar.CONTINUOUS,
            QuantMarketSession.CONTINUOUS,
            2190,
            [_bar(0), _bar(4)],
        ),
        (
            QuantBarInterval.DAILY,
            QuantMarketCalendar.XNYS,
            QuantMarketSession.REGULAR,
            252,
            [_bar(), _bar().model_copy(update={"timestamp": datetime(2024, 1, 3, tzinfo=UTC)})],
        ),
    ],
)
def test_market_dataset_accepts_declared_interval_and_annualization_metadata(
    interval: QuantBarInterval,
    calendar: QuantMarketCalendar,
    session: QuantMarketSession,
    periods_per_year: int,
    bars: list[QuantMarketBar],
) -> None:
    dataset = QuantMarketBarDataset.model_validate(
        _payload(
            interval=interval,
            calendar=calendar,
            session=session,
            periods_per_year=periods_per_year,
            bars=bars,
        )
    )

    assert dataset.interval is interval
    assert dataset.periods_per_year == periods_per_year
    assert periods_per_year_for(calendar=calendar, interval=interval) == periods_per_year
    assert dataset.digest == QuantMarketBarDataset.digest_for(dataset.digest_payload())


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2024, 1, 2),
        datetime(2024, 1, 2, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_market_bar_requires_utc_aware_timestamps(timestamp: datetime) -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        QuantMarketBar(
            timestamp=timestamp,
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            volume=Decimal("0"),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("high", "100", "high must be"),
        ("low", "101", "low must be"),
        ("volume", -1, "greater than or equal to 0"),
    ],
)
def test_market_bar_validates_ohlcv(field: str, value: object, message: str) -> None:
    values: dict[str, object] = {
        "timestamp": datetime(2024, 1, 2, tzinfo=UTC),
        "open": "100",
        "high": "102",
        "low": "99",
        "close": "101",
        "volume": 0,
    }
    values[field] = value
    with pytest.raises(ValidationError, match=message):
        QuantMarketBar.model_validate(values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("open", "0"),
        ("close", "-0.00000001"),
        ("open", "1234567890123.123456789012345678"),
        ("high", "NaN"),
        ("low", "Infinity"),
        ("volume", "-Infinity"),
    ],
)
def test_market_bar_rejects_invalid_or_nonfinite_v2_decimal_values(field: str, value: str) -> None:
    values: dict[str, object] = {
        "timestamp": datetime(2024, 1, 2, tzinfo=UTC),
        "open": "100",
        "high": "102",
        "low": "99",
        "close": "101",
        "volume": "0",
    }
    values[field] = value

    with pytest.raises(ValidationError):
        QuantMarketBar.model_validate(values)


def test_market_bar_accepts_eight_decimal_prices_and_digests_them() -> None:
    first = QuantMarketBar(
        timestamp=datetime(2024, 1, 2, tzinfo=UTC),
        open=Decimal("100.12345678"),
        high=Decimal("102.12345678"),
        low=Decimal("99.12345678"),
        close=Decimal("101.12345678"),
        volume=Decimal("12.34567890"),
    )
    second = first.model_copy(update={"timestamp": datetime(2024, 1, 3, tzinfo=UTC)})
    dataset = QuantMarketBarDataset.model_validate(_payload(bars=[first, second]))
    changed = QuantMarketBarDataset.model_validate(
        _payload(
            bars=[
                first.model_copy(update={"close": Decimal("101.12345679")}),
                second,
            ]
        )
    )

    assert dataset.bars[0].close == Decimal("101.12345678")
    assert dataset.digest != changed.digest


def test_market_bar_preserves_decimal_volume_in_the_canonical_digest() -> None:
    first = _bar().model_copy(update={"volume": Decimal("12.34567890")})
    second = first.model_copy(update={"timestamp": datetime(2024, 1, 3, tzinfo=UTC)})
    dataset = QuantMarketBarDataset.model_validate(_payload(bars=[first, second]))
    changed = QuantMarketBarDataset.model_validate(
        _payload(
            bars=[
                first.model_copy(update={"volume": Decimal("12.34567891")}),
                second,
            ]
        )
    )

    assert dataset.bars[0].volume == Decimal("12.34567890")
    assert dataset.digest != changed.digest


def test_market_dataset_rejects_unordered_or_duplicate_timestamps() -> None:
    first = _bar()
    second = first.model_copy(update={"timestamp": datetime(2024, 1, 3, tzinfo=UTC)})

    duplicate = _payload(bars=[first, first])
    with pytest.raises(ValidationError, match="strictly ordered"):
        QuantMarketBarDataset.model_validate(duplicate)

    unordered = _payload(bars=[second, first])
    unordered["covered_start"] = first.timestamp
    unordered["covered_end"] = second.timestamp
    unordered["digest"] = QuantMarketBarDataset.digest_for(
        {key: value for key, value in unordered.items() if key != "digest"}
    )
    with pytest.raises(ValidationError, match="strictly ordered"):
        QuantMarketBarDataset.model_validate(unordered)


@pytest.mark.parametrize(
    ("interval", "timestamp"),
    [
        (QuantBarInterval.HOUR, datetime(2024, 1, 2, 0, 30, tzinfo=UTC)),
        (QuantBarInterval.FOUR_HOURS, datetime(2024, 1, 2, 2, tzinfo=UTC)),
        (QuantBarInterval.DAILY, datetime(2024, 1, 2, 1, tzinfo=UTC)),
    ],
)
def test_market_dataset_requires_interval_aligned_timestamps(
    interval: QuantBarInterval, timestamp: datetime
) -> None:
    with pytest.raises(ValidationError, match="aligned"):
        QuantMarketBarDataset.model_validate(
            _payload(
                interval=interval,
                bars=[
                    _bar() if interval is QuantBarInterval.DAILY else _bar(0),
                    _bar().model_copy(update={"timestamp": timestamp}),
                ],
                calendar=QuantMarketCalendar.CONTINUOUS,
                session=QuantMarketSession.CONTINUOUS,
                periods_per_year={
                    QuantBarInterval.HOUR: 8760,
                    QuantBarInterval.FOUR_HOURS: 2190,
                    QuantBarInterval.DAILY: 365,
                }[interval],
            )
        )


@pytest.mark.parametrize(
    ("calendar", "session", "periods_per_year", "message"),
    [
        (QuantMarketCalendar.XNAS, QuantMarketSession.REGULAR, 365, "252"),
        (QuantMarketCalendar.CONTINUOUS, QuantMarketSession.CONTINUOUS, 252, "365"),
        (QuantMarketCalendar.XSHG, QuantMarketSession.CONTINUOUS, 252, "regular"),
        (QuantMarketCalendar.UNKNOWN, QuantMarketSession.UNKNOWN, 252, "unknown"),
    ],
)
def test_market_dataset_requires_explicit_valid_calendar_annualization(
    calendar: QuantMarketCalendar,
    session: QuantMarketSession,
    periods_per_year: int | None,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        QuantMarketBarDataset.model_validate(
            _payload(
                calendar=calendar,
                session=session,
                periods_per_year=periods_per_year,
            )
        )


def test_unknown_calendar_explicitly_has_no_annualization() -> None:
    dataset = QuantMarketBarDataset.model_validate(
        _payload(
            calendar=QuantMarketCalendar.UNKNOWN,
            session=QuantMarketSession.UNKNOWN,
            periods_per_year=None,
        )
    )
    assert dataset.periods_per_year is None
    assert (
        periods_per_year_for(calendar=QuantMarketCalendar.UNKNOWN, interval=QuantBarInterval.HOUR)
        is None
    )


@pytest.mark.parametrize(
    "calendar",
    [
        QuantMarketCalendar.WEEKDAY,
        QuantMarketCalendar.XNYS,
        QuantMarketCalendar.XNAS,
        QuantMarketCalendar.XSHG,
        QuantMarketCalendar.XSHE,
    ],
)
def test_market_dataset_rejects_unsupported_regular_session_intraday_cadence(
    calendar: QuantMarketCalendar,
) -> None:
    with pytest.raises(ValidationError, match="only 1D"):
        QuantMarketBarDataset.model_validate(
            _payload(
                interval=QuantBarInterval.HOUR,
                calendar=calendar,
                session=QuantMarketSession.REGULAR,
                periods_per_year=252,
                bars=[_bar(0), _bar(1)],
            )
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("market_calendar", "LSE", "market_calendar"),
        ("periods_per_year", 0, "greater than or equal to 1"),
        ("time_zone", "Mars/Olympus", "valid IANA"),
    ],
)
def test_market_dataset_rejects_invalid_metadata(field: str, value: object, message: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(ValidationError, match=message):
        QuantMarketBarDataset.model_validate(payload)


@pytest.mark.parametrize(
    ("calendar", "time_zone", "message"),
    [
        (QuantMarketCalendar.CONTINUOUS, "America/New_York", "time_zone=UTC"),
        (QuantMarketCalendar.XNYS, "UTC", "America/New_York"),
        (QuantMarketCalendar.XNAS, "UTC", "America/New_York"),
        (QuantMarketCalendar.XSHG, "UTC", "Asia/Shanghai"),
        (QuantMarketCalendar.XSHE, "UTC", "Asia/Shanghai"),
    ],
)
def test_market_dataset_requires_calendar_time_zone_binding(
    calendar: QuantMarketCalendar, time_zone: str, message: str
) -> None:
    periods_per_year = 365 if calendar is QuantMarketCalendar.CONTINUOUS else 252
    session = (
        QuantMarketSession.CONTINUOUS
        if calendar is QuantMarketCalendar.CONTINUOUS
        else QuantMarketSession.REGULAR
    )
    with pytest.raises(ValidationError, match=message):
        QuantMarketBarDataset.model_validate(
            _payload(
                calendar=calendar,
                session=session,
                periods_per_year=periods_per_year,
                time_zone=time_zone,
            )
        )


def test_weekday_daily_requires_explicit_but_unmapped_iana_time_zone() -> None:
    dataset = QuantMarketBarDataset.model_validate(
        _payload(
            calendar=QuantMarketCalendar.WEEKDAY,
            session=QuantMarketSession.REGULAR,
            periods_per_year=252,
            time_zone="Europe/London",
        )
    )
    assert dataset.time_zone == "Europe/London"


def test_market_dataset_digest_includes_interval_timestamp_and_annualization() -> None:
    hourly = QuantMarketBarDataset.model_validate(
        _payload(
            interval=QuantBarInterval.HOUR,
            calendar=QuantMarketCalendar.CONTINUOUS,
            session=QuantMarketSession.CONTINUOUS,
            periods_per_year=8760,
            bars=[_bar(0), _bar(1)],
        )
    )
    four_hour = QuantMarketBarDataset.model_validate(
        _payload(
            interval=QuantBarInterval.FOUR_HOURS,
            calendar=QuantMarketCalendar.CONTINUOUS,
            session=QuantMarketSession.CONTINUOUS,
            periods_per_year=2190,
            bars=[_bar(0), _bar(4)],
        )
    )
    shifted = QuantMarketBarDataset.model_validate(
        _payload(
            interval=QuantBarInterval.HOUR,
            calendar=QuantMarketCalendar.CONTINUOUS,
            session=QuantMarketSession.CONTINUOUS,
            periods_per_year=8760,
            bars=[_bar(1), _bar(2)],
        )
    )
    continuous_daily = QuantMarketBarDataset.model_validate(
        _payload(
            interval=QuantBarInterval.DAILY,
            calendar=QuantMarketCalendar.CONTINUOUS,
            session=QuantMarketSession.CONTINUOUS,
            periods_per_year=365,
            bars=[
                _bar(0),
                _bar().model_copy(update={"timestamp": datetime(2024, 1, 3, tzinfo=UTC)}),
            ],
        )
    )
    nyse_daily = QuantMarketBarDataset.model_validate(
        _payload(
            interval=QuantBarInterval.DAILY,
            calendar=QuantMarketCalendar.XNYS,
            session=QuantMarketSession.REGULAR,
            periods_per_year=252,
            bars=[
                _bar(0),
                _bar().model_copy(update={"timestamp": datetime(2024, 1, 3, tzinfo=UTC)}),
            ],
        )
    )

    assert (
        len(
            {
                hourly.digest,
                four_hour.digest,
                shifted.digest,
                continuous_daily.digest,
                nyse_daily.digest,
            }
        )
        == 5
    )


def test_daily_adapter_is_deterministic_without_changing_v1_identity() -> None:
    legacy_digest = SPY_DAILY_FIXTURE.digest
    assert legacy_digest == (
        "sha256:b675da3aa6fac3c199ae8d8ab51968aff32e660d5b487a35e4da9e7e74edf919"
    )

    first = daily_bar_dataset_to_market_dataset(SPY_DAILY_FIXTURE)
    second = daily_bar_dataset_to_market_dataset(SPY_DAILY_FIXTURE)

    assert SPY_DAILY_FIXTURE.digest == legacy_digest
    assert first == second
    assert first.interval is QuantBarInterval.DAILY
    assert first.market_calendar is QuantMarketCalendar.UNKNOWN
    assert first.market_session is QuantMarketSession.UNKNOWN
    assert first.periods_per_year is None
    assert first.bars[0].timestamp == datetime(2018, 1, 2, tzinfo=UTC)
