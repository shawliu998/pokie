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
    dataset = _dataset(
        "2024-01-02,100,102,99,101,100\n"
        "2024-01-03,101,103,100,102,100\n"
    )
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
