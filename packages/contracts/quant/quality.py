"""Deterministic, calendar-conservative data-quality assessment for Quant datasets."""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from packages.domain.canonical import canonical_digest

from ..base import ContractModel, Digest, NonEmptyString, VersionString
from .data import QuantDailyBarDataset

QUANT_DATA_QUALITY_SCHEMA_VERSION = "quant-data-quality-v1"
QUANT_DATA_QUALITY_POLICY_VERSION = "weekday-gap-price-jump-v1"

_CALENDAR_TIME_ZONES = {
    "XNYS": "America/New_York",
    "XNAS": "America/New_York",
    "XSHG": "Asia/Shanghai",
    "XSHE": "Asia/Shanghai",
}


class QuantDataQualityIssue(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    code: NonEmptyString = Field(max_length=80)
    severity: Literal["warning", "blocked"]
    message: NonEmptyString = Field(max_length=500)
    count: int = Field(ge=0)


class QuantDatasetDataQuality(ContractModel):
    """A report external to immutable dataset identity and safe for persistence."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: VersionString = QUANT_DATA_QUALITY_SCHEMA_VERSION
    policy_version: VersionString = QUANT_DATA_QUALITY_POLICY_VERSION
    status: Literal["passed", "warning", "blocked"]
    verification_status: Literal["checked", "rejected"]
    report_digest: Digest
    dataset_digest: Digest
    market_calendar: NonEmptyString
    time_zone: NonEmptyString
    price_adjustment: NonEmptyString
    bar_count: int = Field(ge=1)
    calendar_gap_count: int = Field(ge=0)
    largest_calendar_gap_days: int = Field(ge=0)
    unexpected_session_count: int = Field(ge=0)
    zero_volume_bar_count: int = Field(ge=0)
    price_jump_count: int = Field(ge=0)
    issues: tuple[QuantDataQualityIssue, ...] = ()
    notes: tuple[NonEmptyString, ...] = ()

    @classmethod
    def digest_for(cls, payload: dict[str, object]) -> str:
        return canonical_digest(payload)

    def digest_payload(self) -> dict[str, object]:
        value = self.model_dump(mode="json")
        value.pop("report_digest")
        return value

    @model_validator(mode="after")
    def validate_report_digest(self) -> QuantDatasetDataQuality:
        if self.report_digest != self.digest_for(self.digest_payload()):
            raise ValueError("data-quality report digest does not match report content")
        return self


def _weekday_gap_count(dataset: QuantDailyBarDataset) -> int:
    missing = 0
    dates = [bar.trading_date for bar in dataset.bars]
    for previous, current in zip(dates, dates[1:], strict=False):
        cursor = previous + timedelta(days=1)
        while cursor < current:
            if cursor.weekday() < 5:
                missing += 1
            cursor += timedelta(days=1)
    return missing


def assess_daily_bar_quality(
    dataset: QuantDailyBarDataset,
    *,
    market_calendar: str | None,
    time_zone: str | None,
    price_adjustment: str | None,
) -> QuantDatasetDataQuality:
    """Assess daily bars without asserting exchange-holiday knowledge.

    Weekdays absent between consecutive observations are counted, but are only a
    warning because exchange holidays and source-specific trading schedules are
    intentionally outside this Phase 1B contract.
    """
    dates = [bar.trading_date for bar in dataset.bars]
    elapsed = [
        max(0, (current - previous).days - 1)
        for previous, current in zip(dates, dates[1:], strict=False)
    ]
    largest_gap = max(elapsed, default=0)
    calendar_gap_count = _weekday_gap_count(dataset)
    zero_volume = sum(bar.volume == 0 for bar in dataset.bars)
    unexpected_sessions = sum(bar.trading_date.weekday() >= 5 for bar in dataset.bars)
    jumps = sum(
        abs(float(current.close / previous.close) - 1) >= 0.5
        for previous, current in zip(dataset.bars, dataset.bars[1:], strict=False)
    )
    issues: list[QuantDataQualityIssue] = []
    calendar = market_calendar.strip().upper() if market_calendar else ""
    expected_zone = _CALENDAR_TIME_ZONES.get(calendar)
    if calendar not in {*_CALENDAR_TIME_ZONES, "WEEKDAY"}:
        issues.append(
            QuantDataQualityIssue(
                code="UNKNOWN_MARKET_CALENDAR",
                severity="warning",
                message="Market calendar is unknown; holiday-aware validation was not performed.",
                count=1,
            )
        )
    elif expected_zone is not None and time_zone != expected_zone:
        issues.append(
            QuantDataQualityIssue(
                code="MARKET_CALENDAR_TIME_ZONE_MISMATCH",
                severity="blocked",
                message=f"{calendar} requires time zone {expected_zone}.",
                count=1,
            )
        )
    if largest_gap > 14:
        issues.append(
            QuantDataQualityIssue(
                code="EXCESSIVE_ELAPSED_GAP",
                severity="blocked",
                message="A consecutive-bar elapsed gap exceeded 14 calendar days.",
                count=sum(gap > 14 for gap in elapsed),
            )
        )
    if calendar_gap_count:
        issues.append(
            QuantDataQualityIssue(
                code="MISSING_WEEKDAYS",
                severity="warning",
                message=(
                    "Weekdays absent between bars were detected; "
                    "exchange holidays are not inferred."
                ),
                count=calendar_gap_count,
            )
        )
    if calendar in {*_CALENDAR_TIME_ZONES, "WEEKDAY"} and unexpected_sessions:
        issues.append(
            QuantDataQualityIssue(
                code="UNEXPECTED_WEEKEND_SESSIONS",
                severity="warning",
                message="Saturday or Sunday bars conflict with the declared weekday calendar.",
                count=unexpected_sessions,
            )
        )
    if zero_volume:
        issues.append(
            QuantDataQualityIssue(
                code="ZERO_VOLUME_BARS",
                severity="warning",
                message="Bars with zero volume were detected.",
                count=zero_volume,
            )
        )
    if jumps:
        issue_code = (
            "POSSIBLE_ADJUSTMENT_DISCONTINUITY"
            if price_adjustment in {"split_adjusted", "total_return_adjusted"}
            else "LARGE_CLOSE_TO_CLOSE_JUMPS"
        )
        issues.append(
            QuantDataQualityIssue(
                code=issue_code,
                severity="warning",
                message=(
                    "Close-to-close absolute price changes of at least 50% were detected; "
                    "corporate-action validation requires an external reference feed."
                ),
                count=jumps,
            )
        )
    if price_adjustment not in {
        "unadjusted",
        "split_adjusted",
        "total_return_adjusted",
    }:
        issues.append(
            QuantDataQualityIssue(
                code="UNKNOWN_PRICE_ADJUSTMENT",
                severity="warning",
                message="The source did not declare a recognized price-adjustment policy.",
                count=1,
            )
        )
    issues.sort(key=lambda item: (item.severity, item.code))
    blocked = any(item.severity == "blocked" for item in issues)
    status: Literal["passed", "warning", "blocked"] = (
        "blocked" if blocked else "warning" if issues else "passed"
    )
    payload: dict[str, object] = {
        "schema_version": QUANT_DATA_QUALITY_SCHEMA_VERSION,
        "policy_version": QUANT_DATA_QUALITY_POLICY_VERSION,
        "status": status,
        "verification_status": "rejected" if blocked else "checked",
        "dataset_digest": dataset.digest,
        "market_calendar": market_calendar or "unknown",
        "time_zone": time_zone or "UTC",
        "price_adjustment": price_adjustment or "unknown",
        "bar_count": len(dataset.bars),
        "calendar_gap_count": calendar_gap_count,
        "largest_calendar_gap_days": largest_gap,
        "unexpected_session_count": unexpected_sessions,
        "zero_volume_bar_count": zero_volume,
        "price_jump_count": jumps,
        "issues": [item.model_dump(mode="json") for item in issues],
        "notes": [
            "Weekday gap counts do not identify exchange holidays.",
            "Corporate actions are not independently verified without an external reference feed.",
            "This report is not part of the immutable dataset digest.",
        ],
    }
    return QuantDatasetDataQuality.model_validate(
        {**payload, "report_digest": QuantDatasetDataQuality.digest_for(payload)}
    )
