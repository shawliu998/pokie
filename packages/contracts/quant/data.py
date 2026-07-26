"""Immutable daily-bar dataset contracts for bounded Quant research.

These contracts deliberately model a local, pinned dataset boundary. They do
not retrieve, transform, or execute market data; the pure backtest engine can
consume :class:`QuantDailyBarDataset` after provenance and content-digest
verification.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from packages.domain.canonical import canonical_digest

from ..base import ContractModel, Digest, NonEmptyString, VersionString

QUANT_DAILY_BAR_SCHEMA_VERSION = "quant-daily-bars-v1"

PositivePrice = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]


class QuantDailyBarInterval(StrEnum):
    """The only interval admitted by the first bounded dataset boundary."""

    DAILY = "1D"


class QuantDatasetProvenance(StrEnum):
    """How a dataset entered the bounded Quant runtime."""

    SYNTHETIC_FIXTURE = "synthetic_fixture"
    IMPORTED_FIXTURE = "imported_fixture"


class QuantDailyBar(ContractModel):
    """One fully adjusted-or-unadjusted-as-declared daily OHLCV observation."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    trading_date: date
    open: PositivePrice
    high: PositivePrice
    low: PositivePrice
    close: PositivePrice
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc_bounds(self) -> QuantDailyBar:
        if self.high < max(self.open, self.close):
            raise ValueError("high must be at least open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be at most open and close")
        return self


class QuantDailyBarDataset(ContractModel):
    """A frozen, hash-verified contiguous-in-order sequence of daily bars.

    ``covered_start`` and ``covered_end`` name the exact bounds represented by
    the first and last bar.  Missing market sessions inside that range are not
    inferred: holidays and exchange calendars remain the responsibility of a
    later engine or importer.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    dataset_id: VersionString
    provenance: QuantDatasetProvenance
    symbol: NonEmptyString = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,15}$")
    interval: QuantDailyBarInterval
    covered_start: date
    covered_end: date
    schema_version: VersionString = QUANT_DAILY_BAR_SCHEMA_VERSION
    digest: Digest
    bars: tuple[QuantDailyBar, ...] = Field(min_length=1)

    @field_validator("interval", mode="before")
    @classmethod
    def reject_unsupported_intervals(cls, value: object) -> object:
        if value != QuantDailyBarInterval.DAILY and value != QuantDailyBarInterval.DAILY.value:
            raise ValueError("only the daily '1D' interval is supported")
        return value

    @classmethod
    def digest_for(cls, value: dict[str, Any]) -> str:
        """Return the canonical content digest for a dataset payload.

        The supplied mapping must contain every dataset field except ``digest``.
        Keeping digest construction here makes producers and consumers use the
        same canonical representation without making a network or storage call.
        """

        return canonical_digest(value)

    def digest_payload(self) -> dict[str, Any]:
        """Return the complete immutable content addressed by ``digest``."""

        return {
            "dataset_id": self.dataset_id,
            "provenance": self.provenance.value,
            "symbol": self.symbol,
            "interval": self.interval.value,
            "covered_start": self.covered_start,
            "covered_end": self.covered_end,
            "schema_version": self.schema_version,
            # JSON mode represents Decimal prices as strings, avoiding any
            # runtime-specific Decimal serialization in the canonical hash.
            "bars": [bar.model_dump(mode="json") for bar in self.bars],
        }

    @model_validator(mode="after")
    def validate_dataset(self) -> QuantDailyBarDataset:
        if self.schema_version != QUANT_DAILY_BAR_SCHEMA_VERSION:
            raise ValueError(f"unsupported daily-bar schema version: {self.schema_version}")
        if self.covered_start > self.covered_end:
            raise ValueError("covered_start must not be after covered_end")

        dates = tuple(bar.trading_date for bar in self.bars)
        if dates[0] != self.covered_start or dates[-1] != self.covered_end:
            raise ValueError("covered range must exactly match the first and last bar")
        if any(current >= following for current, following in zip(dates, dates[1:], strict=False)):
            raise ValueError("bars must be strictly ordered by trading_date without duplicates")

        expected_digest = self.digest_for(self.digest_payload())
        if self.digest != expected_digest:
            raise ValueError("dataset digest does not match canonical dataset content")
        return self
