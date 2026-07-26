from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.contracts.quant import assess_daily_bar_quality, parse_ohlcv_csv


def _dataset(rows: str):
    return parse_ohlcv_csv(
        "date,open,high,low,close,volume\n" + rows,
        name="Quality test bars",
        symbol="SPY",
    )


def test_quality_report_is_deterministic_and_excludes_its_own_digest() -> None:
    dataset = _dataset("2024-01-02,100,102,99,101,100\n2024-01-03,101,103,100,102,100\n")
    first = assess_daily_bar_quality(
        dataset,
        market_calendar="XNYS",
        time_zone="America/New_York",
        price_adjustment="split_adjusted",
    )
    second = assess_daily_bar_quality(
        dataset,
        market_calendar="XNYS",
        time_zone="America/New_York",
        price_adjustment="split_adjusted",
    )
    assert first == second
    assert first.status == "passed"
    assert first.report_digest == first.digest_for(first.digest_payload())
    assert first.dataset_digest == dataset.digest
    with pytest.raises(ValidationError, match="digest does not match"):
        first.__class__.model_validate(
            {**first.model_dump(mode="json"), "zero_volume_bar_count": 1}
        )


def test_quality_warns_without_claiming_holiday_knowledge() -> None:
    report = assess_daily_bar_quality(
        _dataset("2024-01-05,100,102,99,101,0\n2024-01-09,101,153,100,152,10\n"),
        market_calendar=None,
        time_zone=None,
        price_adjustment="unknown",
    )
    assert report.status == "warning"
    assert report.calendar_gap_count == 1
    assert report.zero_volume_bar_count == 1
    assert report.price_jump_count == 1
    assert [issue.code for issue in report.issues] == sorted(issue.code for issue in report.issues)


def test_quality_flags_weekend_rows_for_a_declared_exchange_calendar() -> None:
    report = assess_daily_bar_quality(
        _dataset("2024-01-05,100,102,99,101,1\n2024-01-06,101,103,100,102,1\n"),
        market_calendar="XNYS",
        time_zone="America/New_York",
        price_adjustment="unadjusted",
    )
    assert report.unexpected_session_count == 1
    assert "UNEXPECTED_WEEKEND_SESSIONS" in {issue.code for issue in report.issues}


def test_quality_blocks_time_zone_mismatch_and_long_elapsed_gap() -> None:
    report = assess_daily_bar_quality(
        _dataset("2024-01-02,100,102,99,101,1\n2024-01-18,101,103,100,102,1\n"),
        market_calendar="XSHG",
        time_zone="America/New_York",
        price_adjustment="unadjusted",
    )
    assert report.status == "blocked"
    assert report.verification_status == "rejected"
    assert report.largest_calendar_gap_days == 15
    assert {issue.code for issue in report.issues} >= {
        "MARKET_CALENDAR_TIME_ZONE_MISMATCH",
        "EXCESSIVE_ELAPSED_GAP",
    }


def test_24x7_quality_counts_all_missing_days_and_allows_weekend_sessions() -> None:
    report = assess_daily_bar_quality(
        _dataset("2024-01-05,100,102,99,101,1\n2024-01-08,101,103,100,102,1\n"),
        market_calendar="24x7",
        time_zone="UTC",
        price_adjustment="unadjusted",
    )
    assert report.calendar_gap_count == 2
    assert report.unexpected_session_count == 0
    assert "MISSING_CALENDAR_DAYS" in {issue.code for issue in report.issues}
    assert "UNEXPECTED_WEEKEND_SESSIONS" not in {issue.code for issue in report.issues}


def test_24x7_quality_blocks_non_utc_time_zone() -> None:
    report = assess_daily_bar_quality(
        _dataset("2024-01-05,100,102,99,101,1\n2024-01-06,101,103,100,102,1\n"),
        market_calendar="24x7",
        time_zone="America/New_York",
        price_adjustment="unadjusted",
    )
    assert report.status == "blocked"
    assert "MARKET_CALENDAR_TIME_ZONE_MISMATCH" in {issue.code for issue in report.issues}


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("2023-12-29", "2024-01-02"),  # New Year observed
        ("2024-01-12", "2024-01-16"),  # MLK Day
        ("2024-02-16", "2024-02-20"),  # Presidents Day
        ("2024-03-28", "2024-04-01"),  # Good Friday
        ("2024-05-24", "2024-05-28"),  # Memorial Day
        ("2024-06-18", "2024-06-20"),  # Juneteenth
        ("2024-07-03", "2024-07-05"),  # Independence Day
        ("2024-08-30", "2024-09-03"),  # Labor Day
        ("2024-11-27", "2024-11-29"),  # Thanksgiving
        ("2024-12-24", "2024-12-26"),  # Christmas
        ("2025-06-18", "2025-06-20"),  # 2025 Juneteenth
        ("2026-04-02", "2026-04-06"),  # 2026 Good Friday
    ],
)
def test_us_exchange_regular_holidays_do_not_count_as_missing_weekdays(
    before: str, after: str
) -> None:
    report = assess_daily_bar_quality(
        _dataset(f"{before},100,102,99,101,1\n{after},101,103,100,102,1\n"),
        market_calendar="XNYS",
        time_zone="America/New_York",
        price_adjustment="unadjusted",
    )
    assert report.calendar_gap_count == 0
    assert "MISSING_WEEKDAYS" not in {issue.code for issue in report.issues}


def test_us_exchange_true_missing_trading_day_still_counts_as_a_gap() -> None:
    report = assess_daily_bar_quality(
        _dataset("2024-01-02,100,102,99,101,1\n2024-01-04,101,103,100,102,1\n"),
        market_calendar="XNAS",
        time_zone="America/New_York",
        price_adjustment="unadjusted",
    )
    assert report.calendar_gap_count == 1
    assert "MISSING_WEEKDAYS" in {issue.code for issue in report.issues}


def test_us_exchange_does_not_observe_saturday_new_year_on_friday() -> None:
    report = assess_daily_bar_quality(
        _dataset("2021-12-30,100,102,99,101,1\n2022-01-03,101,103,100,102,1\n"),
        market_calendar="XNAS",
        time_zone="America/New_York",
        price_adjustment="unadjusted",
    )
    assert report.calendar_gap_count == 1
