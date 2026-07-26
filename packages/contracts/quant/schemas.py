"""Quant REST schemas."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ..base import ContractModel, Digest, NonEmptyString, VersionString
from ..enums import DataAuthenticity
from ..schemas.common import ImmutableResource, MutableResource
from .data import QuantDailyBarInterval
from .enums import (
    QuantArtifactKind,
    QuantArtifactReviewStatus,
    QuantExperimentVerdict,
    QuantPlanDecision,
    QuantProjectStatus,
    QuantRunMode,
    QuantRunState,
)
from .market_data import (
    NonNegativeMarketVolume,
    PositiveMarketPrice,
    QuantBarInterval,
    QuantMarketDatasetCadenceQuality,
    QuantMarketDatasetEvidence,
    QuantMarketSession,
)
from .market_data import (
    QuantMarketCalendar as QuantMarketBarCalendar,
)
from .quality import QuantDatasetDataQuality
from .series import (
    QuantResearchLoopPolicy,
    QuantResearchSeriesContext,
    research_loop_policy_digest,
)

QuantMarketCalendar = Literal["unknown", "weekday", "24x7", "XNYS", "XNAS", "XSHG", "XSHE"]
QUANT_MARKET_RUN_CONTRACT_VERSION = "quant-market-run-v2"


def _strict_utc_rfc3339(value: object) -> datetime:
    """Accept only an aware UTC datetime, with an explicit RFC3339 UTC wire value."""

    if isinstance(value, str):
        if not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)",
            value,
        ):
            raise ValueError("timestamp must be an RFC3339 UTC datetime")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("timestamp must be an RFC3339 UTC datetime")
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("timestamp must use the UTC offset")
    return parsed


StrictUtcDateTime = Annotated[AwareDatetime, BeforeValidator(_strict_utc_rfc3339)]


def _validated_time_zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("time_zone must be a valid IANA time zone") from exc
    return value


class QuantDatasetImportRequest(ContractModel):
    name: NonEmptyString = Field(max_length=200)
    symbol: NonEmptyString = Field(pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,15}$")
    csv_text: NonEmptyString = Field(max_length=10_000_000)
    file_name: NonEmptyString | None = Field(default=None, max_length=255, pattern=r"^[^/\\\x00]+$")
    source_name: NonEmptyString = Field(default="User-provided CSV", max_length=200)
    source_reference: NonEmptyString | None = Field(default=None, max_length=2000)
    market_calendar: QuantMarketCalendar = "unknown"
    time_zone: NonEmptyString = Field(default="UTC", max_length=100)
    price_adjustment: Literal[
        "unknown", "unadjusted", "split_adjusted", "total_return_adjusted"
    ] = "unknown"

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        return _validated_time_zone(value)


class QuantBinanceSpotFetchRequest(ContractModel):
    name: NonEmptyString | None = Field(default=None, max_length=200)
    symbol: NonEmptyString = Field(default="BTCUSDT", pattern=r"^[A-Z][A-Z0-9]{4,15}$")
    interval: Literal["1d"] = "1d"
    limit: int = Field(default=365, ge=252, le=1000)


class QuantNasdaqEquityFetchRequest(ContractModel):
    name: NonEmptyString | None = Field(default=None, max_length=200)
    symbol: NonEmptyString = Field(default="AAPL", pattern=r"^[A-Z][A-Z.\-]{0,9}$")
    lookback_days: int = Field(default=730, ge=370, le=3650)


class QuantProviderResponseAttestation(ContractModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["daily_bars", "instrument_info", "dividends", "splits"]
    digest: Digest
    source_reference: NonEmptyString = Field(max_length=2000)


class QuantSplitEventSummary(ContractModel):
    model_config = ConfigDict(frozen=True)

    effective_date: date
    ratio_numerator: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    ratio_denominator: Decimal = Field(gt=0, max_digits=18, decimal_places=8)


class QuantCorporateActionsAttestation(ContractModel):
    model_config = ConfigDict(frozen=True)

    dividends_status: Literal[
        "not_requested", "unavailable", "retrieved_unverified", "verified", "conflict"
    ]
    splits_status: Literal[
        "not_requested", "unavailable", "retrieved_unverified", "verified", "conflict"
    ]
    # Deprecated dividend aliases retained so Phase 1D records remain readable.
    coverage_start: date | None = None
    coverage_end: date | None = None
    dividend_coverage_start: date | None = None
    dividend_coverage_end: date | None = None
    split_coverage_start: date | None = None
    split_coverage_end: date | None = None
    split_snapshot_as_of: date | None = None
    split_completeness_status: Literal[
        "unknown", "current_snapshot_only", "partial_history", "historically_complete"
    ] = "unknown"
    split_reconciliation_status: Literal[
        "not_attempted", "consistent", "conflict", "unavailable"
    ] = "unavailable"
    dividend_event_count: int | None = Field(default=None, ge=0)
    split_event_count: int | None = Field(default=None, ge=0)
    split_events: tuple[QuantSplitEventSummary, ...] = Field(default=(), max_length=100)
    note: NonEmptyString = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_coverage(self) -> QuantCorporateActionsAttestation:
        coverage_pairs = (
            (self.coverage_start, self.coverage_end, "legacy dividend"),
            (self.dividend_coverage_start, self.dividend_coverage_end, "dividend"),
            (self.split_coverage_start, self.split_coverage_end, "split"),
        )
        for start, end, label in coverage_pairs:
            if start is not None and end is not None and start > end:
                raise ValueError(f"{label} coverage start must not exceed end")
        if (
            self.coverage_start is not None
            and self.dividend_coverage_start is not None
            and self.coverage_start != self.dividend_coverage_start
        ) or (
            self.coverage_end is not None
            and self.dividend_coverage_end is not None
            and self.coverage_end != self.dividend_coverage_end
        ):
            raise ValueError("legacy and explicit dividend coverage must agree")
        if self.split_completeness_status == "current_snapshot_only" and (
            self.splits_status != "retrieved_unverified"
            or self.split_snapshot_as_of is None
            or self.split_coverage_start is None
            or self.split_coverage_end is None
        ):
            raise ValueError(
                "current split snapshot requires retrieved evidence and bounded coverage"
            )
        if self.split_snapshot_as_of is not None and (
            self.split_coverage_start is None
            or self.split_coverage_end is None
            or not (
                self.split_coverage_start <= self.split_snapshot_as_of <= self.split_coverage_end
            )
        ):
            raise ValueError("split snapshot date must lie within split coverage")
        if self.split_events:
            if self.split_event_count != len(self.split_events):
                raise ValueError("split event count must match retained split events")
            if self.split_coverage_start is None or self.split_coverage_end is None:
                raise ValueError("retained split events require split coverage")
            if any(
                not self.split_coverage_start <= event.effective_date <= self.split_coverage_end
                for event in self.split_events
            ):
                raise ValueError("retained split events must lie within split coverage")
        elif (
            self.split_completeness_status == "current_snapshot_only"
            and self.split_event_count != 0
        ):
            raise ValueError("empty current split snapshot requires zero target events")
        return self


class QuantDatasetSourceMetadata(ContractModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["csv_upload", "provider_fetch"] = "csv_upload"
    file_name: NonEmptyString | None = Field(default=None, max_length=255)
    source_name: NonEmptyString = Field(default="User-provided CSV", max_length=200)
    source_reference: NonEmptyString | None = Field(default=None, max_length=2000)
    submitted_csv_digest: Digest | None = None
    provider_id: Literal["binance_spot", "nasdaq_equity"] | None = None
    provider_response_digest: Digest | None = None
    provider_response_attestations: tuple[QuantProviderResponseAttestation, ...] = ()
    corporate_actions_attestation: QuantCorporateActionsAttestation | None = None
    price_adjustment_verification_status: Literal[
        "not_applicable", "unverified", "verified", "conflict"
    ] = "unverified"
    retrieved_at: datetime | None = None
    requested_limit: int | None = Field(default=None, ge=1)
    returned_bar_count: int | None = Field(default=None, ge=1)
    dropped_incomplete_count: int | None = Field(default=None, ge=0)
    normalization_note: NonEmptyString | None = Field(default=None, max_length=1000)
    attestation_status: Literal["declared", "provider_retrieved"] = "declared"
    market_calendar: QuantMarketCalendar = "unknown"
    time_zone: NonEmptyString = Field(default="UTC", max_length=100)
    price_adjustment: Literal[
        "unknown", "unadjusted", "split_adjusted", "total_return_adjusted"
    ] = "unknown"

    @field_validator("time_zone")
    @classmethod
    def validate_time_zone(cls, value: str) -> str:
        return _validated_time_zone(value)

    @model_validator(mode="after")
    def validate_provider_attestation(self) -> QuantDatasetSourceMetadata:
        provider_fields = (
            self.provider_id,
            self.provider_response_digest,
            self.retrieved_at,
            self.requested_limit,
            self.returned_bar_count,
            self.dropped_incomplete_count,
            self.normalization_note,
        )
        if self.kind == "provider_fetch":
            if any(value is None for value in provider_fields):
                raise ValueError("provider_fetch metadata requires provider attestation fields")
            if self.attestation_status != "provider_retrieved":
                raise ValueError("provider_fetch metadata requires provider_retrieved status")
        elif any(value is not None for value in provider_fields):
            raise ValueError("CSV metadata cannot contain provider attestation fields")
        elif self.attestation_status != "declared":
            raise ValueError("CSV metadata requires declared attestation status")
        if self.provider_response_attestations and not any(
            item.kind == "daily_bars" for item in self.provider_response_attestations
        ):
            raise ValueError("provider response attestations require daily_bars evidence")
        response_kinds = [item.kind for item in self.provider_response_attestations]
        if len(response_kinds) != len(set(response_kinds)):
            raise ValueError("provider response attestation kinds must be unique")
        daily_evidence = next(
            (item for item in self.provider_response_attestations if item.kind == "daily_bars"),
            None,
        )
        if daily_evidence is not None and daily_evidence.digest != self.provider_response_digest:
            raise ValueError("daily-bars evidence must match provider response digest")
        if self.provider_id == "nasdaq_equity" and set(response_kinds) not in (
            {"daily_bars", "instrument_info", "dividends"},
            {"daily_bars", "instrument_info", "dividends", "splits"},
        ):
            raise ValueError(
                "Nasdaq equity metadata requires bars, listing, dividends, "
                "and optional split evidence"
            )
        actions = self.corporate_actions_attestation
        if actions is not None:
            if self.provider_id != "nasdaq_equity":
                raise ValueError("corporate-action evidence is only supported for Nasdaq equity")
            if (
                actions.dividends_status
                in {
                    "retrieved_unverified",
                    "verified",
                    "conflict",
                }
                and "dividends" not in response_kinds
            ):
                raise ValueError("dividend status requires dividend response evidence")
            if (
                actions.splits_status
                in {
                    "retrieved_unverified",
                    "verified",
                    "conflict",
                }
                and "splits" not in response_kinds
            ):
                raise ValueError("split status requires split response evidence")
            if actions.split_completeness_status != "unknown" and "splits" not in response_kinds:
                raise ValueError("split completeness requires split response evidence")
        if self.kind == "csv_upload" and (
            self.provider_response_attestations or self.corporate_actions_attestation is not None
        ):
            raise ValueError("CSV metadata cannot contain provider evidence")
        if self.price_adjustment == "unadjusted":
            if self.price_adjustment_verification_status not in {
                "not_applicable",
                "unverified",
            }:
                raise ValueError("unadjusted prices cannot claim adjustment verification")
        elif self.price_adjustment_verification_status == "verified":
            if actions is None or actions.splits_status != "verified":
                raise ValueError("verified adjusted prices require verified split evidence")
            if (
                self.price_adjustment == "total_return_adjusted"
                and actions.dividends_status != "verified"
            ):
                raise ValueError("verified total-return prices require verified dividend evidence")
        return self


class QuantDatasetResponse(ContractModel):
    dataset_id: VersionString
    workspace_id: UUID
    name: NonEmptyString
    symbol: NonEmptyString
    interval: QuantDailyBarInterval
    covered_start: date
    covered_end: date
    bar_count: int = Field(ge=1)
    schema_version: VersionString
    parser_version: VersionString
    digest: Digest
    source_metadata: QuantDatasetSourceMetadata
    data_quality: QuantDatasetDataQuality
    data_authenticity: DataAuthenticity
    created_at: datetime


class QuantDatasetPreviewBar(ContractModel):
    date: date
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_ohlc_bounds(self) -> QuantDatasetPreviewBar:
        if self.high < max(self.open, self.close):
            raise ValueError("high must be at least open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be at most open and close")
        return self


class QuantDatasetPreviewResponse(ContractModel):
    dataset_id: VersionString
    symbol: NonEmptyString
    interval: QuantDailyBarInterval
    data_authenticity: DataAuthenticity
    covered_start: date
    covered_end: date
    total_bar_count: int = Field(ge=1)
    returned_bar_count: int = Field(ge=1, le=400)
    max_points: int = Field(ge=50, le=400)
    sampling_rule: Literal["latest_contiguous"]
    bars: tuple[QuantDatasetPreviewBar, ...] = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def validate_preview(self) -> QuantDatasetPreviewResponse:
        if self.returned_bar_count != len(self.bars):
            raise ValueError("returned_bar_count must match bars length")
        if self.returned_bar_count > self.max_points:
            raise ValueError("preview bars cannot exceed max_points")
        if any(
            current.date >= following.date
            for current, following in zip(self.bars, self.bars[1:], strict=False)
        ):
            raise ValueError("preview bars must be strictly ordered by date")
        return self


class QuantMarketDatasetV2ImportRequest(ContractModel):
    """Explicit C2B upload boundary for an isolated v2 market dataset."""

    name: NonEmptyString = Field(max_length=200)
    symbol: NonEmptyString = Field(pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,15}$")
    interval: QuantBarInterval
    csv_text: NonEmptyString = Field(max_length=10_000_000)
    file_name: NonEmptyString | None = Field(default=None, max_length=255)
    source_name: NonEmptyString = Field(default="User-provided CSV", max_length=200)
    source_reference: NonEmptyString | None = Field(default=None, max_length=2_000)

    @field_validator("file_name")
    @classmethod
    def validate_file_name(cls, value: str | None) -> str | None:
        if value is not None and any(character in value for character in ("/", "\\", "\x00")):
            raise ValueError("file_name must be a file name, not a path")
        return value


class QuantMarketBinanceFetchRequest(ContractModel):
    """Bounded v2 Binance request; the route has no implicit interval default."""

    name: NonEmptyString | None = Field(default=None, max_length=200)
    symbol: NonEmptyString = Field(pattern=r"^[A-Z][A-Z0-9]{4,15}$")
    interval: QuantBarInterval
    limit: int = Field(ge=1, le=5_000)


class QuantConnectorDirectoryResponse(ContractModel):
    """One server-owned D1 connector capability; no client-provided endpoint."""

    data_authenticity: Literal[DataAuthenticity.GENERATED]
    connector_id: Literal["kraken-spot-ohlc-v1"]
    provider: Literal["kraken_spot"]
    display_name: Literal["Kraken Spot public OHLC"]
    source_kind: Literal["market_bars"]
    supported_symbols: tuple[Literal["BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"], ...] = Field(
        min_length=4, max_length=4
    )
    supported_intervals: tuple[Literal["4h", "1D"], ...] = Field(min_length=2, max_length=2)
    minimum_recent_bars: dict[Literal["4h", "1D"], StrictInt]
    maximum_recent_bars: Literal[719]
    fetch_endpoint: Literal["/v1/quant/connectors/kraken-spot-ohlc-v1/fetch"]
    connector_version: Literal["kraken-spot-ohlc-v1"]
    source_terms_url: Literal["https://www.kraken.com/legal"]
    source_documentation_url: Literal[
        "https://docs.kraken.com/api-reference/market-data/get-ohlc-data"
    ]

    @model_validator(mode="after")
    def validate_directory_capability(self) -> QuantConnectorDirectoryResponse:
        if self.supported_symbols != ("BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"):
            raise ValueError("Kraken connector symbols must match the server allowlist")
        if self.supported_intervals != ("4h", "1D"):
            raise ValueError("Kraken connector intervals must match the server allowlist")
        if self.minimum_recent_bars != {"4h": 548, "1D": 252}:
            raise ValueError("Kraken connector minimum bars must match research eligibility")
        return self


class QuantKrakenSpotFetchRequest(ContractModel):
    """Bounded Kraken Spot OHLC fetch through the fixed D1 connector."""

    name: NonEmptyString | None = Field(default=None, max_length=200)
    symbol: Literal["BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"]
    interval: Literal[QuantBarInterval.FOUR_HOURS, QuantBarInterval.DAILY]
    limit: StrictInt = Field(ge=252, le=719)

    @model_validator(mode="after")
    def validate_research_eligible_limit(self) -> QuantKrakenSpotFetchRequest:
        minimum = 548 if self.interval is QuantBarInterval.FOUR_HOURS else 252
        if self.limit < minimum:
            raise ValueError(
                f"Kraken {self.interval.value} requires at least {minimum} recent bars"
            )
        return self


class QuantMarketDatasetV2Response(ContractModel):
    """Separate v2 dataset directory row; never part of legacy datasets responses."""

    dataset_id: VersionString
    workspace_id: UUID
    name: NonEmptyString
    symbol: NonEmptyString
    interval: QuantBarInterval
    covered_start: datetime
    covered_end: datetime
    bar_count: int = Field(ge=1, le=5_000)
    market_calendar: QuantMarketBarCalendar
    market_session: QuantMarketSession
    time_zone: NonEmptyString
    periods_per_year: int | None = Field(default=None, ge=1, le=10_000)
    schema_version: VersionString
    digest: Digest
    record_digest: Digest
    evidence: QuantMarketDatasetEvidence
    quality: QuantMarketDatasetCadenceQuality
    research_eligible: bool = False
    data_authenticity: DataAuthenticity
    created_at: datetime

    @model_validator(mode="after")
    def validate_market_dataset_response(self) -> QuantMarketDatasetV2Response:
        for value in (self.covered_start, self.covered_end):
            offset = value.utcoffset()
            if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
                raise ValueError("v2 coverage must use the UTC offset")
        if self.covered_start > self.covered_end:
            raise ValueError("v2 coverage start must not exceed end")
        return self


class QuantMarketDatasetV2PreviewBar(ContractModel):
    timestamp: datetime
    open: PositiveMarketPrice
    high: PositiveMarketPrice
    low: PositiveMarketPrice
    close: PositiveMarketPrice
    volume: NonNegativeMarketVolume

    @model_validator(mode="after")
    def validate_market_bar(self) -> QuantMarketDatasetV2PreviewBar:
        offset = self.timestamp.utcoffset()
        if self.timestamp.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("v2 preview timestamps must use the UTC offset")
        if self.high < max(self.open, self.close):
            raise ValueError("high must be at least open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be at most open and close")
        return self


class QuantMarketDatasetV2PreviewResponse(ContractModel):
    dataset: QuantMarketDatasetV2Response
    data_authenticity: DataAuthenticity
    total_bar_count: int = Field(ge=1, le=5_000)
    returned_bar_count: int = Field(ge=1, le=400)
    max_points: int = Field(ge=1, le=400)
    sampling_rule: Literal["latest_contiguous"]
    bars: tuple[QuantMarketDatasetV2PreviewBar, ...] = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def validate_market_preview(self) -> QuantMarketDatasetV2PreviewResponse:
        if self.data_authenticity is not self.dataset.data_authenticity:
            raise ValueError("preview authenticity must match the persisted dataset")
        if self.returned_bar_count != len(self.bars):
            raise ValueError("returned_bar_count must match bars length")
        if self.returned_bar_count > self.max_points:
            raise ValueError("preview bars cannot exceed max_points")
        if any(
            current.timestamp >= following.timestamp
            for current, following in zip(self.bars, self.bars[1:], strict=False)
        ):
            raise ValueError("preview bars must be strictly ordered by timestamp")
        return self


class QuantStrategyReportMarkdownExportRequest(ContractModel):
    export_type: Literal["strategy_report_markdown"]
    run_id: UUID
    candidate_id: UUID


class QuantStrategyEvidenceBundleExportRequest(ContractModel):
    export_type: Literal["strategy_evidence_bundle_json"]
    run_id: UUID
    candidate_id: UUID


class QuantStrategyReportMarkdownExportResponse(ContractModel):
    export_type: Literal["strategy_report_markdown"]
    run_id: UUID
    candidate_id: UUID
    data_authenticity: DataAuthenticity
    filename: NonEmptyString = Field(max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\.md$")
    media_type: Literal["text/markdown"]
    rendered_content: Annotated[str, StringConstraints(strip_whitespace=False, min_length=1)] = (
        Field(max_length=262_144)
    )
    content_digest: Digest


class QuantStrategyEvidenceBundleExportResponse(ContractModel):
    export_type: Literal["strategy_evidence_bundle_json"]
    run_id: UUID
    candidate_id: UUID
    data_authenticity: DataAuthenticity
    filename: NonEmptyString = Field(max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*\.json$")
    media_type: Literal["application/json"]
    rendered_content: Annotated[str, StringConstraints(strip_whitespace=False, min_length=1)] = (
        Field(max_length=1_048_576)
    )
    content_digest: Digest


QuantStrategyReportExportRequest = Annotated[
    QuantStrategyReportMarkdownExportRequest | QuantStrategyEvidenceBundleExportRequest,
    Field(discriminator="export_type"),
]
QuantStrategyReportExportResponse = Annotated[
    QuantStrategyReportMarkdownExportResponse | QuantStrategyEvidenceBundleExportResponse,
    Field(discriminator="export_type"),
]


class QuantWorkspaceTradeProjection(ContractModel):
    """One retained trade in a daily or timestamped workspace snapshot."""

    id: NonEmptyString
    candidate_id: NonEmptyString = Field(alias="candidateId")
    entry_date: NonEmptyString = Field(alias="entryDate")
    exit_date: NonEmptyString = Field(alias="exitDate")
    return_pct: float = Field(alias="returnPct")
    holding_days: StrictInt | None = Field(default=None, ge=0, alias="holdingDays")
    holding_bars: StrictInt | None = Field(default=None, ge=0, alias="holdingBars")
    holding_elapsed_seconds: StrictInt | None = Field(
        default=None, ge=0, alias="holdingElapsedSeconds"
    )
    reason: NonEmptyString

    @model_validator(mode="after")
    def validate_holding_identity(self) -> QuantWorkspaceTradeProjection:
        market_values = (self.holding_bars, self.holding_elapsed_seconds)
        if self.holding_days is not None:
            if any(value is not None for value in market_values):
                raise ValueError("daily holding days cannot be mixed with market holding fields")
            return self
        if any(value is None for value in market_values):
            raise ValueError("market trades require holding_bars and holding_elapsed_seconds")
        return self


class QuantProjectCreateRequest(ContractModel):
    name: NonEmptyString = Field(max_length=200)
    objective: NonEmptyString = Field(max_length=2000)


class QuantProjectResponse(MutableResource):
    name: NonEmptyString
    objective: NonEmptyString
    status: QuantProjectStatus
    data_authenticity: DataAuthenticity


class QuantRunCreateRequest(ContractModel):
    project_id: UUID
    mode: QuantRunMode = QuantRunMode.PLAN
    question: NonEmptyString = Field(max_length=2000)
    expected_project_row_version: int = Field(ge=1)
    dataset_id: VersionString | None = None
    research_start: date | None = None
    research_end: date | None = None
    parent_run_id: UUID | None = None
    seed_candidate_id: UUID | None = None
    refinement_reason: NonEmptyString | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_research_range(self) -> QuantRunCreateRequest:
        if (self.research_start is None) != (self.research_end is None):
            raise ValueError("research_start and research_end must be supplied together")
        if self.research_start and self.research_end and self.research_start > self.research_end:
            raise ValueError("research_start must not be after research_end")
        refinement = (self.parent_run_id, self.seed_candidate_id, self.refinement_reason)
        if any(value is not None for value in refinement) and not all(refinement):
            raise ValueError(
                "parent_run_id, seed_candidate_id and refinement_reason must be supplied together"
            )
        return self


class QuantRunResponse(MutableResource):
    project_id: UUID
    dataset_id: VersionString
    dataset_digest: Digest
    research_start: date
    research_end: date
    state: QuantRunState
    mode: QuantRunMode
    question: NonEmptyString
    plan_revision: int = Field(ge=0)
    attempt_number: int = Field(ge=1)
    retry_of_run_id: UUID | None = None
    parent_run_id: UUID | None = None
    seed_candidate_id: UUID | None = None
    refinement_reason: NonEmptyString | None = None
    latest_sequence: int = Field(ge=0)
    trace_id: NonEmptyString
    failure_reason: NonEmptyString | None = None
    agent_iteration: int = Field(default=0, ge=0)
    agent_status: NonEmptyString = "idle"
    max_agent_iterations: int = Field(default=12, ge=1)
    max_experiments: int = Field(default=3, ge=0)
    max_repairs: int = Field(default=2, ge=0)
    used_experiments: int = Field(default=0, ge=0)
    used_repairs: int = Field(default=0, ge=0)
    last_action: NonEmptyString | None = None
    last_observation: NonEmptyString | None = None
    final_conclusion: NonEmptyString | None = None
    provider: NonEmptyString = "mock"
    model: NonEmptyString | None = None
    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_state_fields(self) -> QuantRunResponse:
        if self.state == QuantRunState.FAILED:
            if self.failure_reason is None:
                raise ValueError("a failed Quant run requires failure_reason")
        elif self.failure_reason is not None:
            raise ValueError("failure_reason is valid only for a failed Quant run")
        if (
            self.state
            in {
                QuantRunState.WAITING_PLAN_APPROVAL,
                QuantRunState.RUNNING_EXPERIMENTS,
                QuantRunState.COMPLETED,
            }
            and self.plan_revision < 1
        ):
            raise ValueError(f"{self.state.value} requires a published plan revision")
        return self


class QuantMarketRunV2CreateRequest(ContractModel):
    """Explicit bounded UTC create boundary for a stored v2 market dataset."""

    project_id: UUID
    mode: QuantRunMode = QuantRunMode.PLAN
    question: NonEmptyString = Field(max_length=2_000)
    expected_project_row_version: int = Field(ge=1)
    dataset_id: VersionString
    research_start_utc: StrictUtcDateTime
    research_end_utc: StrictUtcDateTime
    parent_run_id: UUID | None = None
    seed_candidate_id: UUID | None = None
    refinement_reason: NonEmptyString | None = Field(default=None, max_length=2_000)
    research_loop: QuantResearchLoopPolicy | None = None

    @model_validator(mode="after")
    def validate_research_range(self) -> QuantMarketRunV2CreateRequest:
        if self.research_start_utc > self.research_end_utc:
            raise ValueError("research_start_utc must not be after research_end_utc")
        refinement = (self.parent_run_id, self.seed_candidate_id, self.refinement_reason)
        if any(value is not None for value in refinement) and not all(
            value is not None for value in refinement
        ):
            raise ValueError(
                "parent_run_id, seed_candidate_id and refinement_reason must be supplied together"
            )
        if self.research_loop is not None:
            if self.mode is not QuantRunMode.AUTO:
                raise ValueError("research_loop is supported only for Auto Research")
            if self.parent_run_id is not None:
                raise ValueError("research_loop can be enabled only on a root research Run")
        return self


class QuantMarketRunV2Response(MutableResource):
    """Pinned identity for one public, cadence-aware v2 market research run."""

    schema_version: Literal["quant-market-run-v2"] = QUANT_MARKET_RUN_CONTRACT_VERSION
    project_id: UUID
    dataset_id: VersionString
    dataset_digest: Digest
    symbol: NonEmptyString
    interval: QuantBarInterval
    periods_per_year: int = Field(ge=1, le=10_000)
    research_start_utc: AwareDatetime
    research_end_utc: AwareDatetime
    runtime_descriptor_digest: Digest
    sealed_split_digest: Digest
    state: QuantRunState
    mode: QuantRunMode
    question: NonEmptyString
    plan_revision: int = Field(ge=0)
    attempt_number: int = Field(ge=1)
    retry_of_run_id: UUID | None = None
    parent_run_id: UUID | None = None
    seed_candidate_id: UUID | None = None
    refinement_reason: NonEmptyString | None = None
    research_loop: QuantResearchLoopPolicy | None = None
    research_series: QuantResearchSeriesContext | None = None
    latest_sequence: int = Field(ge=0)
    trace_id: NonEmptyString
    failure_reason: NonEmptyString | None = None
    agent_iteration: int = Field(default=0, ge=0)
    agent_status: NonEmptyString = "idle"
    max_agent_iterations: int = Field(default=12, ge=1)
    max_experiments: int = Field(default=3, ge=0)
    max_repairs: int = Field(default=2, ge=0)
    used_experiments: int = Field(default=0, ge=0)
    used_repairs: int = Field(default=0, ge=0)
    last_action: NonEmptyString | None = None
    last_observation: NonEmptyString | None = None
    final_conclusion: NonEmptyString | None = None
    provider: NonEmptyString = "mock"
    model: NonEmptyString | None = None

    @model_validator(mode="after")
    def validate_research_series_projection(self) -> QuantMarketRunV2Response:
        if (self.research_loop is None) != (self.research_series is None):
            raise ValueError("research_loop and research_series must be projected together")
        if self.research_series is not None:
            if self.mode is not QuantRunMode.AUTO:
                raise ValueError("a research series must use Auto Research")
            if self.research_series.current_run_id != str(self.id):
                raise ValueError("research_series current_run_id must match the response Run")
            assert self.research_loop is not None
            if self.research_series.policy_digest != research_loop_policy_digest(
                self.research_loop
            ):
                raise ValueError("research_series policy_digest does not match research_loop")
            if "finish_without_follow_up" not in self.research_series.allowed_actions:
                raise ValueError("research_series must allow finishing without a follow-up")
            may_refine = "precommit_one_refinement" in self.research_series.allowed_actions
            if (
                self.research_series.version_number == 2
                and self.research_series.remaining_versions != 0
            ):
                raise ValueError("research series version two has no remaining version budget")
            if self.research_series.remaining_versions == 1 and (
                self.research_series.version_number != 1 or self.research_loop.max_versions != 2
            ):
                raise ValueError("research_series remaining budget is inconsistent")
            expected_refine = (
                self.research_loop.follow_up_mode == "one_train_only_follow_up"
                and self.research_series.remaining_versions == 1
            )
            if may_refine != expected_refine:
                raise ValueError("research_series actions do not match its remaining budget")
        return self

    data_authenticity: DataAuthenticity

    @model_validator(mode="after")
    def validate_market_run(self) -> QuantMarketRunV2Response:
        if self.research_start_utc > self.research_end_utc:
            raise ValueError("research_start_utc must not be after research_end_utc")
        allowed_periods = {
            QuantBarInterval.HOUR: {8_760},
            QuantBarInterval.FOUR_HOURS: {2_190},
            QuantBarInterval.DAILY: {252, 365},
        }
        if self.periods_per_year not in allowed_periods[self.interval]:
            raise ValueError("interval and periods_per_year are inconsistent")
        if self.state == QuantRunState.FAILED:
            if self.failure_reason is None:
                raise ValueError("a failed Quant market run requires failure_reason")
        elif self.failure_reason is not None:
            raise ValueError("failure_reason is valid only for a failed Quant market run")
        if (
            self.state
            in {
                QuantRunState.WAITING_PLAN_APPROVAL,
                QuantRunState.RUNNING_EXPERIMENTS,
                QuantRunState.COMPLETED,
            }
            and self.plan_revision < 1
        ):
            raise ValueError(f"{self.state.value} requires a published plan revision")
        refinement = (self.parent_run_id, self.seed_candidate_id, self.refinement_reason)
        if any(value is not None for value in refinement) and not all(
            value is not None for value in refinement
        ):
            raise ValueError(
                "parent_run_id, seed_candidate_id and refinement_reason must be supplied together"
            )
        return self


class QuantPlanApproveRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    reason: NonEmptyString = Field(default="Plan approved.", max_length=500)


class QuantPlanChangesRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    plan_revision: int = Field(ge=1)
    change_request: NonEmptyString = Field(max_length=1000)


class QuantRunCancelRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    reason: NonEmptyString = Field(max_length=500)


class QuantRunRetryRequest(ContractModel):
    expected_row_version: int = Field(ge=1)
    reason: NonEmptyString = Field(max_length=500)


class QuantFixtureCommandRequest(ContractModel):
    command: Literal[
        "ask",
        "generate_plan",
        "start_auto_research",
        "approve_plan",
        "run_fixture",
        "request_plan_changes",
        "cancel_run",
        "retry_run",
        "complete_review",
    ]
    expected_row_version: int = Field(ge=1)
    payload: dict[str, object] = Field(default_factory=dict)


class QuantPlanDecisionResponse(ImmutableResource):
    run_id: UUID
    plan_revision: int = Field(ge=1)
    decision: QuantPlanDecision
    actor_id: UUID
    reason: NonEmptyString
    request_id: NonEmptyString
    occurred_at: datetime
    data_authenticity: DataAuthenticity


class QuantExperimentResponse(ImmutableResource):
    run_id: UUID
    ordinal: int = Field(ge=1)
    name: NonEmptyString
    hypothesis: NonEmptyString
    verdict: QuantExperimentVerdict
    summary: NonEmptyString
    template: NonEmptyString = "fixture"
    parameters: dict[str, object] = Field(default_factory=dict)
    state: NonEmptyString = "completed"
    metrics: dict[str, object] = Field(default_factory=dict)
    repair_count: int = Field(default=0, ge=0)
    candidate_key: NonEmptyString | None = None
    parent_experiment_id: NonEmptyString | None = None
    created_at: datetime
    data_authenticity: DataAuthenticity


class QuantArtifactResponse(ImmutableResource):
    run_id: UUID
    ordinal: int = Field(ge=1)
    kind: QuantArtifactKind
    title: NonEmptyString
    digest: NonEmptyString
    review_status: QuantArtifactReviewStatus
    created_at: datetime
    data_authenticity: DataAuthenticity
