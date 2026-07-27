"""Versioned generic market-bar contracts for future multi-interval Quant data.

This v2 contract deliberately coexists with :mod:`.data` rather than widening
the established v1 daily-bar boundary.  Nothing in the current importer,
runtime, backtest engine, or UI consumes it yet.  In particular, C1 records
annualization metadata but does not change the existing daily ``252`` metric
calculations; that belongs to the later runtime migration.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ConfigDict, Field, field_validator, model_validator

from packages.domain.canonical import canonical_digest

from ..base import ContractModel, Digest, NonEmptyString, VersionString
from .data import QuantDailyBarDataset

QUANT_MARKET_BAR_SCHEMA_VERSION = "quant-market-bars-v2"
NonNegativeMarketVolume = Annotated[Decimal, Field(ge=0, max_digits=30, decimal_places=18)]
PositiveMarketPrice = Annotated[Decimal, Field(gt=0, max_digits=30, decimal_places=18)]


class QuantBarInterval(StrEnum):
    """Supported v2 market-bar intervals, expressed in provider-neutral form."""

    HOUR = "1h"
    FOUR_HOURS = "4h"
    DAILY = "1D"


class QuantMarketCalendar(StrEnum):
    """Declared market calendar used to interpret session and annualization metadata."""

    UNKNOWN = "unknown"
    WEEKDAY = "weekday"
    CONTINUOUS = "24x7"
    XNYS = "XNYS"
    XNAS = "XNAS"
    XSHG = "XSHG"
    XSHE = "XSHE"


class QuantMarketSession(StrEnum):
    """The source session convention represented by each bar timestamp."""

    UNKNOWN = "unknown"
    REGULAR = "regular"
    CONTINUOUS = "continuous"


class QuantMarketDataProvenance(StrEnum):
    """How a v2 market-bar dataset entered the future dataset boundary."""

    SYNTHETIC_FIXTURE = "synthetic_fixture"
    IMPORTED_FIXTURE = "imported_fixture"
    CSV_UPLOAD = "csv_upload"
    PROVIDER_FETCH = "provider_fetch"


class QuantMarketDatasetEvidence(ContractModel):
    """Minimal normalized-source evidence retained with a v2 dataset.

    Provider rows are represented only by their bounded summary and page hashes;
    raw provider payloads are deliberately not a persistence concern.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    source_kind: QuantMarketDataProvenance
    source_name: NonEmptyString = Field(max_length=200)
    source_reference: NonEmptyString | None = Field(default=None, max_length=2_000)
    file_name: NonEmptyString | None = Field(default=None, max_length=255, pattern=r"^[^/\\\x00]+$")
    submitted_csv_digest: Digest | None = None
    retrieved_at_utc: datetime | None = None
    requested_bar_count: int | None = Field(default=None, ge=1, le=5_000)
    returned_bar_count: int | None = Field(default=None, ge=0, le=5_000)
    retained_bar_count: int | None = Field(default=None, ge=0, le=5_000)
    closed_dropped_count: int | None = Field(default=None, ge=0, le=5_000)
    deduplicated_count: int | None = Field(default=None, ge=0, le=5_000)
    page_raw_sha256: tuple[Digest, ...] = Field(default=(), max_length=5)
    batch_digest: Digest | None = None
    termination_reason: Literal["requested_limit", "history_exhausted", "page_cap"] | None = None
    target_satisfied: bool | None = None
    normalizer_version: VersionString
    connector_version: VersionString | None = None
    source_request_digest: Digest | None = None
    terms_reference: NonEmptyString | None = Field(default=None, max_length=2_000)

    @field_validator("retrieved_at_utc")
    @classmethod
    def validate_retrieved_at_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("retrieved_at_utc must use the UTC offset")
        return value.astimezone(UTC)

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str | None) -> str | None:
        if value is not None and any(character in value for character in ("/", "\\", "\x00")):
            raise ValueError("file_name must be a file name, not a path")
        return value

    @model_validator(mode="after")
    def validate_source_shape(self) -> QuantMarketDatasetEvidence:
        provider_fields = (
            self.retrieved_at_utc,
            self.requested_bar_count,
            self.returned_bar_count,
            self.retained_bar_count,
            self.closed_dropped_count,
            self.deduplicated_count,
            self.batch_digest,
            self.termination_reason,
            self.target_satisfied,
        )
        if self.source_kind is QuantMarketDataProvenance.PROVIDER_FETCH:
            if self.source_reference is None or any(value is None for value in provider_fields):
                raise ValueError("provider_fetch evidence requires bounded provider fields")
            if not self.page_raw_sha256:
                raise ValueError("provider_fetch evidence requires page hashes")
            if self.submitted_csv_digest is not None:
                raise ValueError("provider_fetch evidence cannot contain a CSV digest")
            if self.file_name is not None:
                raise ValueError("provider_fetch evidence cannot contain a CSV file name")
        elif self.source_kind is QuantMarketDataProvenance.CSV_UPLOAD:
            if self.submitted_csv_digest is None:
                raise ValueError("csv_upload evidence requires a submitted CSV digest")
            if any(value is not None for value in provider_fields) or self.page_raw_sha256:
                raise ValueError("csv_upload evidence cannot contain provider page evidence")
        else:
            raise ValueError("v2 stored datasets require provider_fetch or csv_upload evidence")
        connector_fields = (
            self.connector_version,
            self.source_request_digest,
            self.terms_reference,
        )
        if any(value is not None for value in connector_fields) and any(
            value is None for value in connector_fields
        ):
            raise ValueError(
                "connector evidence requires version, request digest and terms reference together"
            )
        if (
            self.connector_version is not None
            and self.source_kind is not QuantMarketDataProvenance.PROVIDER_FETCH
        ):
            raise ValueError("connector evidence is valid only for provider_fetch sources")
        return self


class QuantMarketDatasetCadenceQuality(ContractModel):
    """C2A cadence result stored without fabricating missing bars."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    status: Literal["accepted", "blocked"]
    cadence_gap_count: int = Field(ge=0)
    normalization_note: NonEmptyString = Field(max_length=1_000)

    @model_validator(mode="after")
    def validate_gap_status(self) -> QuantMarketDatasetCadenceQuality:
        if (self.cadence_gap_count > 0) != (self.status == "blocked"):
            raise ValueError("cadence status must match the detected gap count")
        return self


_CALENDAR_TIME_ZONES: dict[QuantMarketCalendar, str] = {
    QuantMarketCalendar.CONTINUOUS: "UTC",
    QuantMarketCalendar.XNYS: "America/New_York",
    QuantMarketCalendar.XNAS: "America/New_York",
    QuantMarketCalendar.XSHG: "Asia/Shanghai",
    QuantMarketCalendar.XSHE: "Asia/Shanghai",
}

EXCHANGE_MARKET_CALENDARS = frozenset(
    {
        QuantMarketCalendar.XNYS,
        QuantMarketCalendar.XNAS,
        QuantMarketCalendar.XSHG,
        QuantMarketCalendar.XSHE,
    }
)


def market_calendar_metadata(
    *, calendar: QuantMarketCalendar, interval: QuantBarInterval
) -> tuple[QuantMarketSession, str, int]:
    """Derive supported import metadata from one declared calendar."""

    if calendar is QuantMarketCalendar.CONTINUOUS:
        periods_per_year = periods_per_year_for(calendar=calendar, interval=interval)
        if periods_per_year is None:
            raise ValueError("continuous calendar requires annualization metadata")
        return QuantMarketSession.CONTINUOUS, "UTC", periods_per_year
    if calendar in EXCHANGE_MARKET_CALENDARS:
        periods_per_year = periods_per_year_for(calendar=calendar, interval=interval)
        if periods_per_year is None:
            raise ValueError("exchange calendar requires annualization metadata")
        return (
            QuantMarketSession.REGULAR,
            _CALENDAR_TIME_ZONES[calendar],
            periods_per_year,
        )
    raise ValueError(f"{calendar.value} calendar is not supported by market CSV import")


def market_bar_label_is_consistent(
    *,
    timestamp: datetime,
    calendar: QuantMarketCalendar,
    interval: QuantBarInterval,
) -> bool:
    """Check deterministic session-label rules without inferring holidays."""

    if calendar in EXCHANGE_MARKET_CALENDARS or calendar is QuantMarketCalendar.WEEKDAY:
        return interval is QuantBarInterval.DAILY and timestamp.weekday() < 5
    return True


def market_bar_transition_is_consistent(
    *,
    left: datetime,
    right: datetime,
    calendar: QuantMarketCalendar,
    interval: QuantBarInterval,
) -> bool:
    """Return whether two stored labels obey the declared cadence semantics."""

    if not (
        market_bar_label_is_consistent(timestamp=left, calendar=calendar, interval=interval)
        and market_bar_label_is_consistent(timestamp=right, calendar=calendar, interval=interval)
    ):
        return False
    if calendar in EXCHANGE_MARKET_CALENDARS or calendar is QuantMarketCalendar.WEEKDAY:
        # Without an authoritative holiday schedule, a multi-day weekday gap
        # cannot truthfully be classified as either a closure or missing data.
        return right > left
    expected_delta = {
        QuantBarInterval.HOUR: timedelta(hours=1),
        QuantBarInterval.FOUR_HOURS: timedelta(hours=4),
        QuantBarInterval.DAILY: timedelta(days=1),
    }[interval]
    return right - left == expected_delta


class QuantMarketBar(ContractModel):
    """One UTC-aligned OHLCV observation at a declared v2 interval."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    timestamp: datetime
    open: PositiveMarketPrice
    high: PositiveMarketPrice
    low: PositiveMarketPrice
    close: PositiveMarketPrice
    volume: NonNegativeMarketVolume

    @field_validator("open", "high", "low", "close", "volume", mode="before")
    @classmethod
    def validate_finite_ohlcv(cls, value: object) -> object:
        """Reject non-finite values before decimal bounds are evaluated."""

        try:
            numeric_value = Decimal(str(value))
        except (ArithmeticError, ValueError):
            return value
        if not numeric_value.is_finite():
            raise ValueError("OHLCV values must be finite")
        return value

    @field_validator("timestamp")
    @classmethod
    def validate_utc_timestamp(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("timestamp must use the UTC offset")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_ohlc_bounds(self) -> QuantMarketBar:
        if self.high < max(self.open, self.close):
            raise ValueError("high must be at least open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be at most open and close")
        return self


class QuantMarketBarDataset(ContractModel):
    """Immutable, hash-verified v2 bars with explicit market metadata.

    ``periods_per_year`` is the number of bars per year, not the number of
    calendar days. ``unknown`` intentionally carries ``None``. Consumers must
    resolve or reject that state; the contract never guesses an annualization
    factor. Current v1 calculations continue to use their established daily
    assumptions until a later engine migration consumes v2.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    dataset_id: VersionString
    provenance: QuantMarketDataProvenance
    symbol: NonEmptyString = Field(pattern=r"^[A-Z0-9][A-Z0-9.\-]{0,15}$")
    interval: QuantBarInterval
    covered_start: datetime
    covered_end: datetime
    market_calendar: QuantMarketCalendar
    market_session: QuantMarketSession
    time_zone: NonEmptyString = Field(max_length=100)
    periods_per_year: int | None = Field(default=None, ge=1, le=10_000)
    schema_version: VersionString = QUANT_MARKET_BAR_SCHEMA_VERSION
    digest: Digest
    bars: tuple[QuantMarketBar, ...] = Field(min_length=1)

    @field_validator("covered_start", "covered_end")
    @classmethod
    def validate_utc_coverage(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("coverage timestamps must use the UTC offset")
        return value.astimezone(UTC)

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("time_zone must be a valid IANA time zone") from exc
        return value

    @classmethod
    def digest_for(cls, value: dict[str, Any]) -> str:
        """Return the canonical digest for the complete v2 market payload."""

        return canonical_digest(value)

    def digest_payload(self) -> dict[str, Any]:
        """Return every immutable field covered by the v2 digest."""

        return {
            "dataset_id": self.dataset_id,
            "provenance": self.provenance.value,
            "symbol": self.symbol,
            "interval": self.interval.value,
            "covered_start": self.covered_start,
            "covered_end": self.covered_end,
            "market_calendar": self.market_calendar.value,
            "market_session": self.market_session.value,
            "time_zone": self.time_zone,
            "periods_per_year": self.periods_per_year,
            "schema_version": self.schema_version,
            "bars": [bar.model_dump(mode="json") for bar in self.bars],
        }

    @model_validator(mode="after")
    def validate_dataset(self) -> QuantMarketBarDataset:
        if self.schema_version != QUANT_MARKET_BAR_SCHEMA_VERSION:
            raise ValueError(f"unsupported market-bar schema version: {self.schema_version}")
        timestamps = tuple(bar.timestamp for bar in self.bars)
        if any(
            current >= following
            for current, following in zip(timestamps, timestamps[1:], strict=False)
        ):
            raise ValueError("bars must be strictly ordered by timestamp without duplicates")
        if self.covered_start > self.covered_end:
            raise ValueError("covered_start must not be after covered_end")
        if timestamps[0] != self.covered_start or timestamps[-1] != self.covered_end:
            raise ValueError("covered range must exactly match the first and last bar")
        if any(not _is_interval_aligned(timestamp, self.interval) for timestamp in timestamps):
            raise ValueError("bar timestamps must be aligned to the declared interval")

        _validate_market_metadata(
            calendar=self.market_calendar,
            session=self.market_session,
            time_zone=self.time_zone,
            interval=self.interval,
            periods_per_year=self.periods_per_year,
        )
        expected_digest = self.digest_for(self.digest_payload())
        if self.digest != expected_digest:
            raise ValueError("dataset digest does not match canonical dataset content")
        return self


def _is_interval_aligned(timestamp: datetime, interval: QuantBarInterval) -> bool:
    if timestamp.second != 0 or timestamp.microsecond != 0:
        return False
    if interval is QuantBarInterval.HOUR:
        return timestamp.minute == 0
    if interval is QuantBarInterval.FOUR_HOURS:
        return timestamp.minute == 0 and timestamp.hour % 4 == 0
    return (
        timestamp.hour == 0
        and timestamp.minute == 0
        and timestamp.second == 0
        and timestamp.microsecond == 0
    )


def periods_per_year_for(
    *, calendar: QuantMarketCalendar, interval: QuantBarInterval
) -> int | None:
    """Return the declared bar cadence or reject an unsupported cadence.

    Generic weekday and exchange calendars have no trustworthy intraday
    session-cadence model in C1, so their intraday combinations are rejected
    instead of inferring a bar count. ``unknown`` remains explicitly
    non-annualizable until a later data contract resolves its calendar.
    """

    if calendar is QuantMarketCalendar.UNKNOWN:
        return None
    if calendar is QuantMarketCalendar.CONTINUOUS:
        return {
            QuantBarInterval.HOUR: 24 * 365,
            QuantBarInterval.FOUR_HOURS: 6 * 365,
            QuantBarInterval.DAILY: 365,
        }[interval]
    if interval is not QuantBarInterval.DAILY:
        raise ValueError(
            f"{calendar.value} calendar supports only 1D until an intraday "
            "session cadence is declared"
        )
    return 252


def _validate_market_metadata(
    *,
    calendar: QuantMarketCalendar,
    session: QuantMarketSession,
    time_zone: str,
    interval: QuantBarInterval,
    periods_per_year: int | None,
) -> None:
    if calendar is QuantMarketCalendar.UNKNOWN:
        if session is not QuantMarketSession.UNKNOWN or periods_per_year is not None:
            raise ValueError("unknown calendar requires unknown session and no periods_per_year")
        return
    expected_periods = periods_per_year_for(calendar=calendar, interval=interval)
    expected_session = (
        QuantMarketSession.CONTINUOUS
        if calendar is QuantMarketCalendar.CONTINUOUS
        else QuantMarketSession.REGULAR
    )
    if session is not expected_session:
        raise ValueError(f"{calendar.value} calendar requires {expected_session.value} session")
    if periods_per_year != expected_periods:
        raise ValueError(f"{calendar.value} calendar requires periods_per_year={expected_periods}")
    required_time_zone = _CALENDAR_TIME_ZONES.get(calendar)
    if required_time_zone is not None and time_zone != required_time_zone:
        raise ValueError(f"{calendar.value} calendar requires time_zone={required_time_zone}")


def daily_bar_dataset_to_market_dataset(dataset: QuantDailyBarDataset) -> QuantMarketBarDataset:
    """Adapt a v1 daily dataset to v2 without changing the v1 dataset or digest.

    v1 contains no calendar or annualization declaration.  The adapter therefore
    preserves that absence explicitly as ``unknown`` / ``None`` rather than
    inferring the current runtime's daily ``252`` convention.
    """

    bars = tuple(
        QuantMarketBar(
            timestamp=datetime.combine(bar.trading_date, time.min, tzinfo=UTC),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=Decimal(bar.volume),
        )
        for bar in dataset.bars
    )
    source_identity = canonical_digest(
        {"legacy_dataset_id": dataset.dataset_id, "legacy_digest": dataset.digest}
    ).removeprefix("sha256:")[:16]
    content: dict[str, Any] = {
        "dataset_id": f"market-{source_identity}",
        "provenance": QuantMarketDataProvenance(dataset.provenance.value).value,
        "symbol": dataset.symbol,
        "interval": QuantBarInterval.DAILY.value,
        "covered_start": bars[0].timestamp,
        "covered_end": bars[-1].timestamp,
        "market_calendar": QuantMarketCalendar.UNKNOWN.value,
        "market_session": QuantMarketSession.UNKNOWN.value,
        "time_zone": "UTC",
        "periods_per_year": None,
        "schema_version": QUANT_MARKET_BAR_SCHEMA_VERSION,
        "bars": [bar.model_dump(mode="json") for bar in bars],
    }
    return QuantMarketBarDataset.model_validate(
        {**content, "digest": QuantMarketBarDataset.digest_for(content)}
    )
