from __future__ import annotations

import base64
import os
import re
from dataclasses import asdict, dataclass, field
from dataclasses import fields as dataclass_fields
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from math import ceil, isfinite, sqrt
from statistics import median, pstdev
from threading import RLock
from typing import Any, Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from packages.contracts.enums import DataAuthenticity
from packages.contracts.quant import (
    QUANT_MARKET_BAR_SCHEMA_VERSION,
    QUANT_MARKET_OHLCV_CSV_PARSER_VERSION,
    QUANT_MARKET_RUN_CONTRACT_VERSION,
    QUANT_OHLCV_CSV_PARSER_VERSION,
    QuantAgentAction,
    QuantAgentDecision,
    QuantAgentPlan,
    QuantBarInterval,
    QuantCorporateActionsAttestation,
    QuantDailyBarDataset,
    QuantDatasetDataQuality,
    QuantDatasetSourceMetadata,
    QuantEvidenceReplanDecision,
    QuantIterationFeedback,
    QuantLearningEventRef,
    QuantLearningFieldDelta,
    QuantLearningTrace,
    QuantLearningViolation,
    QuantMarketBar,
    QuantMarketBarDataset,
    QuantMarketCalendar,
    QuantMarketDataProvenance,
    QuantMarketDatasetCadenceQuality,
    QuantMarketDatasetEvidence,
    QuantProviderResponseAttestation,
    QuantRepairMemory,
    QuantRepairMemoryEntry,
    QuantRepairMemoryReuseReceipt,
    QuantResearchDecision,
    QuantResearchLoopPolicy,
    QuantResearchMemoryContext,
    QuantResearchSeriesContext,
    QuantResearchSeriesDecision,
    QuantRobustnessSensitivity,
    QuantStrategyScopeDecision,
    QuantToolObservation,
    QuantToolRepair,
    assess_daily_bar_quality,
    market_bar_label_is_consistent,
    market_bar_transition_is_consistent,
    parse_market_ohlcv_csv,
    parse_ohlcv_csv,
    quant_tool_identity,
    research_loop_policy_digest,
    validate_quant_tool_arguments,
)
from packages.contracts.quant.enums import (
    QuantArtifactKind,
    QuantArtifactReviewStatus,
    QuantCandidateVerdict,
    QuantExperimentVerdict,
    QuantFixtureScenario,
    QuantProjectStatus,
    QuantRunMode,
    QuantRunState,
)
from packages.contracts.quant.fixture_data import SPY_DAILY_FIXTURE
from packages.domain.canonical import canonical_digest
from packages.domain.quant_backtest import (
    BacktestBar,
    BacktestCadence,
    BacktestInterval,
    BacktestMetrics,
    DailyBar,
    ExecutionConfig,
    MarketBar,
    StrategySpec,
    backtest_buy_and_hold,
    run_backtest,
)
from services.api.app.core.errors import invalid_state, not_found, version_conflict
from services.api.app.db.models import QuantRepositoryState
from services.api.app.db.session import get_session_factory, set_rls_context
from services.api.app.modules.quant.execution import (
    BASELINE_EXECUTION,
    COST_SENSITIVITY_SCENARIOS,
    EXECUTION_RULE_VERSION,
    PARAMETER_NEIGHBORHOOD_RULE_VERSION,
)

MIN_AUTONOMOUS_RESEARCH_BARS = 252
AGENT_TRAIN_PERCENT = 80
AGENT_SPLIT_RULE_VERSION = "chronological-80-20-v1"
AGENT_WALK_FORWARD_RULE_VERSION = "expanding-3fold-20pct-regime-v1"
AGENT_WALK_FORWARD_FOLDS = 3
AGENT_WALK_FORWARD_STATE_RULE_VERSION = "trailing-60bar-trend-vol-v1"
AGENT_WALK_FORWARD_STATE_LOOKBACK_BARS = 60
AGENT_WALK_FORWARD_TREND_THRESHOLD = 0.03
AGENT_WALK_FORWARD_HIGH_VOLATILITY_THRESHOLD = 0.25
MAX_CONSECUTIVE_AGENT_PROVIDER_FAILURES = 3
RUNTIME_DESCRIPTOR_RULE_VERSION = "quant-runtime-descriptor-v1"
RUNTIME_SPLIT_SEAL_RULE_VERSION = "quant-runtime-split-seal-v1"
SUPPORTED_AGENT_CANDIDATE_FAMILIES = (
    "sma_crossover",
    "rsi_mean_reversion",
    "breakout",
)
DEFAULT_AGENT_COMPLETION_CRITERIA = (
    "Backtest every judged candidate with the local kernel.",
    "Compare completed candidates before selecting one.",
    "Retain a report even when no candidate meets the goal.",
)
SUPPORTED_AGENT_SELECTION_OBJECTIVES = (
    "risk_adjusted_return",
    "total_return",
    "drawdown_control",
)
DEFAULT_SUPPORTED_STRATEGY_SCOPE_REASON = (
    "The request fits the registered long-or-cash strategy templates."
)
LEGACY_SUPPORTED_STRATEGY_SCOPE_REASON = (
    "Legacy retained plan predates strategy-scope classification and is treated as supported."
)
RESEARCH_MEMORY_MAX_SOURCE_RUNS = 5
RESEARCH_MEMORY_MAX_CANDIDATE_KEYS = 15
RESEARCH_MEMORY_CONTRACT_VERSION = "quant-research-memory-v1"
LEGACY_RESEARCH_MEMORY_CONTRACT_VERSION = "legacy-pre-p17"
VERIFIED_LEARNING_REPOSITORY_CONTRACT_VERSION = "qvl1:"
VERIFIED_LEARNING_POLICY_VERSION = "quant-verified-learning-policy-v1"
EVIDENCE_REPLAN_REPOSITORY_PREFIX = "p18v1:"
LEGACY_EVIDENCE_REPLAN_REPOSITORY_MARKER = "legacy-pre-p18"
RESEARCH_DECISION_REPOSITORY_PREFIX = "p19v1:"
LEGACY_RESEARCH_DECISION_REPOSITORY_MARKER = "legacy-pre-p19"
_UNSET_RESEARCH_DECISION_REPOSITORY_MARKER = object()
_UNSET_VERIFIED_LEARNING_REPOSITORY_MARKER = object()
HoldoutEvidenceState = Literal["fresh_sealed", "development_only", "not_evaluated"]
RESEARCH_MEMORY_TERMINAL_STATES = frozenset(
    {
        QuantRunState.COMPLETED,
        QuantRunState.FAILED,
        QuantRunState.CANCELLED,
    }
)
_INTERNAL_REPORT_LANGUAGE = re.compile(
    r"\b(?:iteration(?:[_\s-]+)feedback|feedback[_\s-]+artifact|tool[_\s-]+(?:call|invocation|execution))\b",
    flags=re.IGNORECASE,
)
_STRICT_ITERATION_FINISH_ERRORS = {
    "ITERATION_BASE_CANDIDATES_REQUIRED",
    "ITERATION_FEEDBACK_REQUIRED",
    "ITERATION_FEEDBACK_INVALID",
    "ITERATION_CANDIDATE_REQUIRED",
    "ITERATION_CANDIDATE_RATIONALE_REQUIRED",
    "ITERATION_REPLAN_DECISION_INVALID",
    "ITERATION_CANDIDATE_CANONICAL_IDENTITY_INVALID",
    "ITERATION_CANDIDATE_NOT_NOVEL",
}


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _uuid(label: str, *parts: object) -> UUID:
    return uuid5(
        NAMESPACE_URL, "pokiequant.quant:" + ":".join(str(part) for part in (label, *parts))
    )


def _text(*parts: object) -> str:
    return " ".join(str(part) for part in parts if part is not None).strip()


def user_facing_report_text(value: object, *, fallback: str) -> str:
    """Reject internal Agent implementation wording from durable report copy."""

    text = " ".join(str(value).split())
    return fallback if not text or _INTERNAL_REPORT_LANGUAGE.search(text) else text


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="json"))
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _datetime(value: str | datetime) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _optional_datetime(value: str | datetime | None) -> datetime | None:
    return None if value is None else _datetime(value)


def _default_strategy_scope() -> QuantStrategyScopeDecision:
    return QuantStrategyScopeDecision(
        status="supported",
        reason=DEFAULT_SUPPORTED_STRATEGY_SCOPE_REASON,
    )


def _legacy_strategy_scope() -> QuantStrategyScopeDecision:
    return QuantStrategyScopeDecision(
        status="supported",
        reason=LEGACY_SUPPORTED_STRATEGY_SCOPE_REASON,
    )


def _evidence_replan_repository_marker(legacy_candidate_ids: list[str]) -> str:
    digest = canonical_digest(sorted(legacy_candidate_ids)).removeprefix("sha256:")
    return f"{EVIDENCE_REPLAN_REPOSITORY_PREFIX}{digest[:56]}"


def _research_decision_repository_marker(
    report_identities: list[dict[str, Any]],
    comparison_identities: list[dict[str, Any]],
) -> str:
    """Bind every P19 report and its referenced final training comparison."""

    digest = canonical_digest(
        {
            "reports": sorted(report_identities, key=lambda item: str(item["artifact_id"])),
            "comparisons": sorted(comparison_identities, key=lambda item: str(item["artifact_id"])),
        }
    ).removeprefix("sha256:")
    return f"{RESEARCH_DECISION_REPOSITORY_PREFIX}{digest[:56]}"


def _research_decision_report_manifest_digest(
    report_identities: list[dict[str, Any]],
) -> str:
    return canonical_digest(sorted(report_identities, key=lambda item: str(item["artifact_id"])))


def _verified_learning_repository_marker(policy_digest: str) -> str:
    """Encode the full policy SHA-256 in the existing 64-character repository column."""

    if re.fullmatch(r"sha256:[0-9a-f]{64}", policy_digest) is None:
        raise ValueError("The verified-learning policy digest is invalid.")
    encoded = base64.urlsafe_b64encode(
        bytes.fromhex(policy_digest.removeprefix("sha256:"))
    ).decode()
    marker = f"{VERIFIED_LEARNING_REPOSITORY_CONTRACT_VERSION}{encoded.rstrip('=')}"
    if len(marker) > 64:  # pragma: no cover - guards the durable String(64) contract
        raise ValueError("The verified-learning repository marker exceeds its durable boundary.")
    return marker


def _repository_memory_marker_for_state(state: dict[str, Any]) -> str:
    raw_policy = state.get("verified_learning_policy")
    if not isinstance(raw_policy, dict) or not isinstance(raw_policy.get("policy_digest"), str):
        return RESEARCH_MEMORY_CONTRACT_VERSION
    return _verified_learning_repository_marker(raw_policy["policy_digest"])


def _research_decision_report_identity(artifact: QuantArtifactRecord) -> dict[str, Any]:
    return {
        "artifact_id": artifact.id,
        "workspace_id": artifact.workspace_id,
        "run_id": artifact.run_id,
        "selected_candidate_id": artifact.content.get("selected_candidate_id"),
        "decision_exempt": artifact.content.get("research_decision") is None,
        "artifact_digest": artifact.digest,
        "content_digest": canonical_digest(artifact.content),
    }


def _research_decision_comparison_identity(artifact: QuantArtifactRecord) -> dict[str, Any]:
    return {
        "artifact_id": artifact.id,
        "workspace_id": artifact.workspace_id,
        "run_id": artifact.run_id,
        "artifact_digest": artifact.digest,
        "content_digest": canonical_digest(artifact.content),
    }


def _research_decision_comparison_identities(
    report_artifacts: list[QuantArtifactRecord],
    artifacts: dict[str, QuantArtifactRecord],
) -> list[dict[str, Any]]:
    identities: dict[str, dict[str, Any]] = {}
    for report in report_artifacts:
        decision = report.content.get("research_decision")
        if decision is None:
            continue
        source_id = (
            decision.get("source_comparison_artifact_id") if isinstance(decision, dict) else None
        )
        comparison = artifacts.get(source_id) if isinstance(source_id, str) else None
        if (
            comparison is None
            or comparison.kind is not QuantArtifactKind.VALIDATION_REPORT
            or comparison.workspace_id != report.workspace_id
            or comparison.run_id != report.run_id
        ):
            raise ValueError("Persisted Quant P19 comparison identity is missing or invalid.")
        identities[comparison.id] = _research_decision_comparison_identity(comparison)
    return list(identities.values())


def _restore_market_dataset_v2_record(
    workspace_id: str, item: dict[str, Any]
) -> QuantMarketDatasetV2Record:
    """Restore only the known v2 schema; unknown/tampered state fails closed."""

    payload = item.get("dataset")
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != QUANT_MARKET_BAR_SCHEMA_VERSION
    ):
        raise ValueError("Unsupported persisted Quant market dataset schema.")
    dataset = QuantMarketBarDataset.model_validate(payload)
    if item.get("id") != dataset.dataset_id:
        raise ValueError("Persisted Quant market dataset identity does not match its payload.")
    evidence = QuantMarketDatasetEvidence.model_validate(item["evidence"])
    quality = QuantMarketDatasetCadenceQuality.model_validate(item["quality"])
    expected_authenticity = _market_dataset_v2_authenticity(evidence)
    if DataAuthenticity(item["data_authenticity"]) is not expected_authenticity:
        raise ValueError(
            "Persisted Quant market dataset authenticity does not match its source evidence."
        )
    record_digest = _market_dataset_v2_record_digest(
        dataset=dataset, evidence=evidence, quality=quality
    )
    if item.get("record_digest") != record_digest:
        raise ValueError("Persisted Quant market dataset record digest does not match content.")
    return QuantMarketDatasetV2Record(
        id=dataset.dataset_id,
        workspace_id=workspace_id,
        name=str(item["name"]),
        dataset=dataset,
        evidence=evidence,
        quality=quality,
        record_digest=record_digest,
        created_at=_datetime(item["created_at"]),
        data_authenticity=expected_authenticity,
    )


def _market_dataset_v2_record_digest(
    *,
    dataset: QuantMarketBarDataset,
    evidence: QuantMarketDatasetEvidence,
    quality: QuantMarketDatasetCadenceQuality,
) -> str:
    """Digest every immutable v2 record input except the storage timestamp/name."""

    evidence_payload = evidence.model_dump(mode="json")
    connector_fields = (
        "connector_version",
        "source_request_digest",
        "terms_reference",
    )
    if all(evidence_payload[field] is None for field in connector_fields):
        # D1 added the connector trio to the evidence model. Pre-D1 records did
        # not serialize those keys, so omitting only this all-None additive
        # group preserves their checked record digests without weakening any
        # of the older optional evidence fields.
        for field in connector_fields:
            evidence_payload.pop(field)
    return canonical_digest(
        {
            "record_schema_version": "quant-market-dataset-record-v2",
            "dataset_digest": dataset.digest,
            "normalizer_version": evidence.normalizer_version,
            "evidence": evidence_payload,
            "quality": quality.model_dump(mode="json"),
        }
    )


def _same_connector_refetch(
    left: QuantMarketDatasetEvidence,
    right: QuantMarketDatasetEvidence,
) -> bool:
    """Recognize another retrieval of the same fixed connector request.

    The canonical dataset keeps the first retained fetch evidence. Volatile
    retrieval time and raw-response hashes do not create duplicate datasets,
    while a different connector version, request digest or terms boundary
    remains a conflict.
    """

    connector_fields = (
        "connector_version",
        "source_request_digest",
        "terms_reference",
    )
    return (
        left.source_kind is QuantMarketDataProvenance.PROVIDER_FETCH
        and right.source_kind is QuantMarketDataProvenance.PROVIDER_FETCH
        and all(getattr(left, field) is not None for field in connector_fields)
        and all(getattr(left, field) == getattr(right, field) for field in connector_fields)
    )


def _market_dataset_v2_authenticity(
    evidence: QuantMarketDatasetEvidence,
) -> DataAuthenticity:
    """Derive v2 origin from the closed evidence contract, never stored text."""

    return (
        DataAuthenticity.COLLECTED
        if evidence.source_kind is QuantMarketDataProvenance.PROVIDER_FETCH
        else DataAuthenticity.IMPORTED
    )


@dataclass(slots=True)
class QuantProjectRecord:
    id: str
    workspace_id: str
    name: str
    objective: str
    status: QuantProjectStatus = QuantProjectStatus.ACTIVE
    latest_run_id: str | None = None
    row_version: int = 1
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED


def _legacy_dataset_source_metadata() -> QuantDatasetSourceMetadata:
    return QuantDatasetSourceMetadata(source_name="Legacy CSV import")


def _dataset_quality(record: QuantDatasetRecord) -> QuantDatasetDataQuality:
    return record.data_quality or assess_daily_bar_quality(
        record.dataset,
        market_calendar=record.source_metadata.market_calendar,
        time_zone=record.source_metadata.time_zone,
        price_adjustment=record.source_metadata.price_adjustment,
    )


def _market_interval_delta(interval: QuantBarInterval) -> timedelta:
    return {
        QuantBarInterval.HOUR: timedelta(hours=1),
        QuantBarInterval.FOUR_HOURS: timedelta(hours=4),
        QuantBarInterval.DAILY: timedelta(days=1),
    }[interval]


def _market_dataset_cadence_quality(
    dataset: QuantMarketBarDataset,
) -> QuantMarketDatasetCadenceQuality:
    invalid_label_count = sum(
        not market_bar_label_is_consistent(
            timestamp=bar.timestamp,
            calendar=dataset.market_calendar,
            interval=dataset.interval,
        )
        for bar in dataset.bars
    )
    transition_violation_count = sum(
        1
        for left, right in zip(dataset.bars, dataset.bars[1:], strict=False)
        if not market_bar_transition_is_consistent(
            left=left.timestamp,
            right=right.timestamp,
            calendar=dataset.market_calendar,
            interval=dataset.interval,
        )
    )
    gap_count = invalid_label_count + transition_violation_count
    calendar_completeness_note = (
        " Session labels are weekday-consistent; exchange holiday completeness is not inferred."
        if dataset.market_calendar
        in {
            QuantMarketCalendar.XNYS,
            QuantMarketCalendar.XNAS,
            QuantMarketCalendar.XSHG,
            QuantMarketCalendar.XSHE,
        }
        else ""
    )
    return QuantMarketDatasetCadenceQuality(
        status="blocked" if gap_count else "accepted",
        cadence_gap_count=gap_count,
        normalization_note=(
            f"No cadence consistency violations detected.{calendar_completeness_note}"
            if not gap_count
            else "Cadence consistency violations were retained without filling; "
            "research remains unavailable."
        ),
    )


def _latest_contiguous_market_tail(
    dataset: QuantMarketBarDataset, *, max_points: int
) -> tuple[QuantMarketBar, ...]:
    """Return only the latest real continuous segment; never sample across a gap."""

    start_index = len(dataset.bars) - 1
    while start_index > 0 and market_bar_transition_is_consistent(
        left=dataset.bars[start_index - 1].timestamp,
        right=dataset.bars[start_index].timestamp,
        calendar=dataset.market_calendar,
        interval=dataset.interval,
    ):
        start_index -= 1
    return dataset.bars[max(start_index, len(dataset.bars) - max_points) :]


def _pin_seed_family_to_plan(
    plan: QuantAgentPlan | None, *, seed_template: str | None
) -> QuantAgentPlan | None:
    """Keep a Continue plan inside the selected seed's registered strategy scope."""

    if (
        plan is None
        or seed_template is None
        or plan.strategy_scope.status == "unsupported"
        or seed_template in plan.candidate_families
    ):
        return plan
    if seed_template not in SUPPORTED_AGENT_CANDIDATE_FAMILIES:
        raise invalid_state("A Continue seed uses an unsupported strategy family.")
    retained_families = list(plan.candidate_families)
    if len(retained_families) >= 3:
        retained_families = retained_families[:2]
    retained_families.append(seed_template)
    return QuantAgentPlan.model_validate(
        {
            **plan.model_dump(mode="python"),
            "candidate_families": retained_families,
        }
    )


@dataclass(frozen=True, slots=True)
class QuantDatasetRecord:
    id: str
    workspace_id: str
    name: str
    dataset: QuantDailyBarDataset
    source_metadata: QuantDatasetSourceMetadata = field(
        default_factory=_legacy_dataset_source_metadata
    )
    data_quality: QuantDatasetDataQuality | None = None
    parser_version: str = QUANT_OHLCV_CSV_PARSER_VERSION
    created_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.IMPORTED


@dataclass(frozen=True, slots=True)
class QuantMarketDatasetV2Record:
    """Isolated C2B record for stored, previewable but non-researchable v2 bars."""

    id: str
    workspace_id: str
    name: str
    dataset: QuantMarketBarDataset
    evidence: QuantMarketDatasetEvidence
    quality: QuantMarketDatasetCadenceQuality
    record_digest: str
    created_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.IMPORTED


@dataclass(frozen=True, slots=True)
class QuantRuntimeDatasetDescriptor:
    """Private immutable dataset boundary shared by every runtime evaluation."""

    dataset_id: str
    dataset_digest: str
    record_digest: str | None
    symbol: str
    interval: BacktestInterval
    periods_per_year: int
    coverage_start_utc: datetime
    coverage_end_utc: datetime
    data_authenticity: DataAuthenticity
    quality_status: str
    bars: tuple[BacktestBar, ...]
    cadence: BacktestCadence | None
    descriptor_digest: str


@dataclass(frozen=True, slots=True)
class QuantMarketResearchSufficiency:
    required_bars: int
    inclusive_coverage: timedelta
    required_coverage: timedelta
    eligible: bool


def _market_research_sufficiency(
    *,
    interval: QuantBarInterval,
    periods_per_year: int,
    bar_count: int,
    coverage_start_utc: datetime,
    coverage_end_utc: datetime,
) -> QuantMarketResearchSufficiency:
    interval_delta = _market_interval_delta(interval)
    required_bars = max(MIN_AUTONOMOUS_RESEARCH_BARS, ceil(periods_per_year / 4))
    inclusive_coverage = coverage_end_utc - coverage_start_utc + interval_delta
    required_coverage = interval_delta * required_bars
    return QuantMarketResearchSufficiency(
        required_bars=required_bars,
        inclusive_coverage=inclusive_coverage,
        required_coverage=required_coverage,
        eligible=bar_count >= required_bars and inclusive_coverage >= required_coverage,
    )


@dataclass(frozen=True, slots=True)
class QuantRuntimeSplit:
    """Private chronological split derived from one pinned runtime descriptor."""

    all_bars: tuple[BacktestBar, ...]
    training_bars: tuple[BacktestBar, ...]
    split_index: int
    metadata: dict[str, Any]
    seal_digest: str | None


@dataclass(frozen=True, slots=True)
class QuantRuntimeProjection:
    """Validated runtime plus its source record for non-mutating internal projections."""

    descriptor: QuantRuntimeDatasetDescriptor
    split: QuantRuntimeSplit
    daily_dataset: QuantDailyBarDataset | None
    daily_record: QuantDatasetRecord | None
    market_record: QuantMarketDatasetV2Record | None


def _runtime_bar_timestamp(bar: BacktestBar) -> datetime:
    if isinstance(bar, MarketBar):
        return bar.timestamp
    return datetime.combine(bar.date, datetime.min.time(), tzinfo=UTC)


def _runtime_bar_label(bar: BacktestBar) -> str:
    return bar.timestamp.isoformat() if isinstance(bar, MarketBar) else bar.date.isoformat()


def _runtime_holdout_bar_keys(
    dataset_digest: str,
    bars: tuple[BacktestBar, ...] | list[BacktestBar],
) -> set[str]:
    return {f"{dataset_digest}:{_runtime_bar_label(bar)}" for bar in bars}


def _runtime_descriptor_digest(
    *,
    dataset_id: str,
    dataset_digest: str,
    record_digest: str | None,
    symbol: str,
    interval: BacktestInterval,
    periods_per_year: int,
    coverage_start_utc: datetime,
    coverage_end_utc: datetime,
    data_authenticity: DataAuthenticity,
    quality_status: str,
    bar_count: int,
) -> str:
    return canonical_digest(
        {
            "rule_version": RUNTIME_DESCRIPTOR_RULE_VERSION,
            "dataset_id": dataset_id,
            "dataset_digest": dataset_digest,
            "record_digest": record_digest,
            "symbol": symbol,
            "interval": interval.value,
            "periods_per_year": periods_per_year,
            "coverage_start_utc": coverage_start_utc,
            "coverage_end_utc": coverage_end_utc,
            "data_authenticity": data_authenticity.value,
            "quality_status": quality_status,
            "bar_count": bar_count,
        }
    )


def _decimal_to_runtime_float(value: Decimal, *, field_name: str) -> float:
    """Convert a contract Decimal without permitting float overflow/non-finite values."""

    converted = float(value)
    if not isfinite(converted):
        raise ValueError(f"Market bar {field_name} cannot be represented as a finite float.")
    return converted


def _market_runtime_descriptor(
    record: QuantMarketDatasetV2Record,
    *,
    coverage_start_utc: datetime | None = None,
    coverage_end_utc: datetime | None = None,
) -> QuantRuntimeDatasetDescriptor:
    """Build one immutable runtime view over a stored market dataset.

    Public Runs may select an inclusive, cadence-aligned subrange.  The stored
    dataset and record digests continue to identify the source; the descriptor
    digest and split seal identify the selected research window.
    """

    dataset = record.dataset
    if record.quality.status != "accepted" or record.quality.cadence_gap_count != 0:
        raise ValueError(
            "Runtime research requires accepted, cadence-consistent market data quality."
        )
    if dataset.periods_per_year is None:
        raise ValueError("Runtime research requires declared periods_per_year metadata.")
    cadence = BacktestCadence(BacktestInterval(dataset.interval.value), dataset.periods_per_year)
    if any(
        not market_bar_transition_is_consistent(
            left=left.timestamp,
            right=right.timestamp,
            calendar=dataset.market_calendar,
            interval=dataset.interval,
        )
        for left, right in zip(dataset.bars, dataset.bars[1:], strict=False)
    ):
        raise ValueError("Runtime research requires a cadence-consistent market-bar range.")
    if len(dataset.bars) < MIN_AUTONOMOUS_RESEARCH_BARS:
        raise ValueError(
            f"Runtime research requires at least {MIN_AUTONOMOUS_RESEARCH_BARS} market bars."
        )
    if (coverage_start_utc is None) != (coverage_end_utc is None):
        raise ValueError("Runtime research requires both UTC range bounds together.")
    selected_source_bars = dataset.bars
    if coverage_start_utc is not None and coverage_end_utc is not None:
        for value in (coverage_start_utc, coverage_end_utc):
            offset = value.utcoffset()
            if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
                raise ValueError("Market research timestamps must use the UTC offset.")
        if coverage_start_utc > coverage_end_utc:
            raise ValueError("Market research start must not be after its end.")
        if coverage_start_utc < dataset.covered_start or coverage_end_utc > dataset.covered_end:
            raise ValueError("Market research range must stay inside the stored UTC coverage.")
        timestamp_indexes = {bar.timestamp: index for index, bar in enumerate(dataset.bars)}
        start_index = timestamp_indexes.get(coverage_start_utc)
        end_index = timestamp_indexes.get(coverage_end_utc)
        if start_index is None or end_index is None:
            raise ValueError(
                "Market research range must align exactly with stored interval timestamps."
            )
        selected_source_bars = dataset.bars[start_index : end_index + 1]

    if len(selected_source_bars) < MIN_AUTONOMOUS_RESEARCH_BARS:
        raise ValueError(
            f"Runtime research requires at least {MIN_AUTONOMOUS_RESEARCH_BARS} market bars."
        )
    selected_start_utc = selected_source_bars[0].timestamp
    selected_end_utc = selected_source_bars[-1].timestamp
    bars = tuple(
        MarketBar(
            timestamp=bar.timestamp,
            open=_decimal_to_runtime_float(bar.open, field_name="open"),
            high=_decimal_to_runtime_float(bar.high, field_name="high"),
            low=_decimal_to_runtime_float(bar.low, field_name="low"),
            close=_decimal_to_runtime_float(bar.close, field_name="close"),
            volume=_decimal_to_runtime_float(bar.volume, field_name="volume"),
        )
        for bar in selected_source_bars
    )
    descriptor_digest = _runtime_descriptor_digest(
        dataset_id=dataset.dataset_id,
        dataset_digest=dataset.digest,
        record_digest=record.record_digest,
        symbol=dataset.symbol,
        interval=cadence.interval,
        periods_per_year=cadence.periods_per_year,
        coverage_start_utc=selected_start_utc,
        coverage_end_utc=selected_end_utc,
        data_authenticity=record.data_authenticity,
        quality_status=record.quality.status,
        bar_count=len(bars),
    )
    return QuantRuntimeDatasetDescriptor(
        dataset_id=dataset.dataset_id,
        dataset_digest=dataset.digest,
        record_digest=record.record_digest,
        symbol=dataset.symbol,
        interval=cadence.interval,
        periods_per_year=cadence.periods_per_year,
        coverage_start_utc=selected_start_utc,
        coverage_end_utc=selected_end_utc,
        data_authenticity=record.data_authenticity,
        quality_status=record.quality.status,
        bars=bars,
        cadence=cadence,
        descriptor_digest=descriptor_digest,
    )


def _runtime_split(descriptor: QuantRuntimeDatasetDescriptor) -> QuantRuntimeSplit:
    bars = descriptor.bars
    if len(bars) < MIN_AUTONOMOUS_RESEARCH_BARS:
        raise ValueError(
            "Runtime research requires at least "
            f"{MIN_AUTONOMOUS_RESEARCH_BARS} bars before splitting."
        )
    split_index = len(bars) * AGENT_TRAIN_PERCENT // 100
    split_index = max(1, min(split_index, len(bars) - 1))
    if split_index < 201 or len(bars) - split_index < 1:
        raise ValueError("Runtime research requires enough bars for strategy history and holdout.")
    if descriptor.cadence is None:
        metadata = {
            "method": "chronological",
            "rule_version": AGENT_SPLIT_RULE_VERSION,
            "train_bar_count": split_index,
            "holdout_bar_count": len(bars) - split_index,
            "train_start": _runtime_bar_label(bars[0]),
            "train_end": _runtime_bar_label(bars[split_index - 1]),
            "holdout_start": _runtime_bar_label(bars[split_index]),
            "holdout_end": _runtime_bar_label(bars[-1]),
            "cutoff_date": _runtime_bar_label(bars[split_index]),
            "dataset_id": descriptor.dataset_id,
            "dataset_digest": descriptor.dataset_digest,
        }
        return QuantRuntimeSplit(bars, bars[:split_index], split_index, metadata, None)

    seal_payload = {
        "rule_version": RUNTIME_SPLIT_SEAL_RULE_VERSION,
        "split_rule_version": AGENT_SPLIT_RULE_VERSION,
        "dataset_id": descriptor.dataset_id,
        "dataset_digest": descriptor.dataset_digest,
        "descriptor_digest": descriptor.descriptor_digest,
        "interval": descriptor.interval.value,
        "periods_per_year": descriptor.periods_per_year,
        "range_start_utc": descriptor.coverage_start_utc,
        "range_end_utc": descriptor.coverage_end_utc,
        "train_bar_count": split_index,
        "holdout_bar_count": len(bars) - split_index,
        "train_start_utc": _runtime_bar_timestamp(bars[0]),
        "train_end_utc": _runtime_bar_timestamp(bars[split_index - 1]),
        "holdout_start_utc": _runtime_bar_timestamp(bars[split_index]),
        "holdout_end_utc": _runtime_bar_timestamp(bars[-1]),
    }
    seal_digest = canonical_digest(seal_payload)
    metadata = {
        "method": "chronological",
        "rule_version": AGENT_SPLIT_RULE_VERSION,
        "train_bar_count": split_index,
        "holdout_bar_count": len(bars) - split_index,
        "train_start": _runtime_bar_timestamp(bars[0]).isoformat(),
        "train_end": _runtime_bar_timestamp(bars[split_index - 1]).isoformat(),
        "holdout_start": _runtime_bar_timestamp(bars[split_index]).isoformat(),
        "holdout_end": _runtime_bar_timestamp(bars[-1]).isoformat(),
        "cutoff_date": _runtime_bar_timestamp(bars[split_index]).isoformat(),
        "cutoff_timestamp_utc": _runtime_bar_timestamp(bars[split_index]).isoformat(),
        "dataset_id": descriptor.dataset_id,
        "dataset_digest": descriptor.dataset_digest,
        "descriptor_digest": descriptor.descriptor_digest,
        "interval": descriptor.interval.value,
        "periods_per_year": descriptor.periods_per_year,
        "range_start_utc": descriptor.coverage_start_utc.isoformat(),
        "range_end_utc": descriptor.coverage_end_utc.isoformat(),
        "seal_rule_version": RUNTIME_SPLIT_SEAL_RULE_VERSION,
        "seal_digest": seal_digest,
    }
    return QuantRuntimeSplit(bars, bars[:split_index], split_index, metadata, seal_digest)


def _restored_runtime_descriptor(
    run: QuantRunRecord,
    *,
    daily_record: QuantDatasetRecord | None,
    market_record: QuantMarketDatasetV2Record | None,
) -> QuantRuntimeDatasetDescriptor:
    """Resolve a parsed Run without consulting or mutating the live store cache."""

    if market_record is not None:
        if run.research_start_utc is None or run.research_end_utc is None:
            raise ValueError("Persisted market Run has incomplete UTC bounds.")
        return _market_runtime_descriptor(
            market_record,
            coverage_start_utc=run.research_start_utc,
            coverage_end_utc=run.research_end_utc,
        )

    dataset = daily_record.dataset if daily_record is not None else SPY_DAILY_FIXTURE
    if dataset.dataset_id != run.dataset_id or dataset.digest != run.dataset_digest:
        raise ValueError("Persisted daily Run dataset identity is invalid.")
    source_bars = tuple(
        bar for bar in dataset.bars if run.research_start <= bar.trading_date <= run.research_end
    )
    bars = tuple(
        DailyBar(
            date=bar.trading_date,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )
        for bar in source_bars
    )
    if len(bars) < MIN_AUTONOMOUS_RESEARCH_BARS:
        raise ValueError("Persisted daily Run has too few runtime bars.")
    quality_status = _dataset_quality(daily_record).status if daily_record is not None else "passed"
    coverage_start_utc = datetime.combine(bars[0].date, datetime.min.time(), tzinfo=UTC)
    coverage_end_utc = datetime.combine(bars[-1].date, datetime.min.time(), tzinfo=UTC)
    descriptor_digest = _runtime_descriptor_digest(
        dataset_id=dataset.dataset_id,
        dataset_digest=dataset.digest,
        record_digest=None,
        symbol=dataset.symbol,
        interval=BacktestInterval.DAILY,
        periods_per_year=252,
        coverage_start_utc=coverage_start_utc,
        coverage_end_utc=coverage_end_utc,
        data_authenticity=run.data_authenticity,
        quality_status=quality_status,
        bar_count=len(bars),
    )
    return QuantRuntimeDatasetDescriptor(
        dataset_id=dataset.dataset_id,
        dataset_digest=dataset.digest,
        record_digest=None,
        symbol=dataset.symbol,
        interval=BacktestInterval.DAILY,
        periods_per_year=252,
        coverage_start_utc=coverage_start_utc,
        coverage_end_utc=coverage_end_utc,
        data_authenticity=run.data_authenticity,
        quality_status=quality_status,
        bars=bars,
        cadence=None,
        descriptor_digest=descriptor_digest,
    )


@dataclass(slots=True)
class QuantRunRecord:
    id: str
    workspace_id: str
    project_id: str
    question: str
    mode: QuantRunMode
    dataset_id: str = SPY_DAILY_FIXTURE.dataset_id
    dataset_digest: str = SPY_DAILY_FIXTURE.digest
    research_start: date = SPY_DAILY_FIXTURE.covered_start
    research_end: date = SPY_DAILY_FIXTURE.covered_end
    research_start_utc: datetime | None = None
    research_end_utc: datetime | None = None
    runtime_interval: BacktestInterval | None = None
    runtime_periods_per_year: int | None = None
    runtime_descriptor_digest: str | None = None
    runtime_split_digest: str | None = None
    market_run_contract_version: str | None = None
    state: QuantRunState = QuantRunState.QUEUED
    plan_revision: int = 1
    attempt_number: int = 1
    latest_sequence: int = 0
    trace_id: str = field(default_factory=lambda: str(_uuid("trace", "pending")))
    plan_artifact_id: str | None = None
    retry_of_run_id: str | None = None
    parent_run_id: str | None = None
    seed_candidate_id: str | None = None
    refinement_reason: str | None = None
    research_loop_policy: QuantResearchLoopPolicy | None = None
    research_series_root_run_id: str | None = None
    research_series_version: int | None = None
    research_series_child_run_id: str | None = None
    research_series_decision: QuantResearchSeriesDecision | None = None
    research_memory_contract_version: str | None = None
    research_memory: QuantResearchMemoryContext | None = None
    repair_memory: QuantRepairMemory | None = None
    plan_summary: str | None = None
    strategy_scope: QuantStrategyScopeDecision = field(default_factory=_default_strategy_scope)
    planned_candidate_families: list[str] = field(
        default_factory=lambda: list(SUPPORTED_AGENT_CANDIDATE_FAMILIES)
    )
    selection_objective: str = "risk_adjusted_return"
    completion_criteria: list[str] = field(
        default_factory=lambda: list(DEFAULT_AGENT_COMPLETION_CRITERIA)
    )
    plan_change_request: str | None = None
    approval_reason: str | None = None
    failure_reason: str | None = None
    cancelled_reason: str | None = None
    retry_child_run_id: str | None = None
    agent_iteration: int = 0
    agent_status: str = "idle"
    max_agent_iterations: int = 12
    max_experiments: int = 3
    max_repairs: int = 2
    used_experiments: int = 0
    used_repairs: int = 0
    last_action: str | None = None
    last_observation: str | None = None
    final_conclusion: str | None = None
    provider: str = "mock"
    model: str | None = None
    consecutive_provider_failures: int = 0
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    row_version: int = 1
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED


@dataclass(slots=True)
class QuantEventRecord:
    id: str
    workspace_id: str
    run_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    trace_id: str
    occurred_at: datetime
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED

    def to_contract(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_id": self.id,
            "event_type": self.event_type,
            "payload": self.payload,
            "trace_id": self.trace_id,
            "timestamp": self.occurred_at,
            "data_authenticity": self.data_authenticity,
        }


@dataclass(slots=True)
class QuantArtifactRecord:
    id: str
    workspace_id: str
    run_id: str
    ordinal: int
    kind: QuantArtifactKind
    title: str
    digest: str
    review_status: QuantArtifactReviewStatus = QuantArtifactReviewStatus.UNREVIEWED
    content: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED


@dataclass(slots=True)
class QuantExperimentRecord:
    id: str
    workspace_id: str
    run_id: str
    ordinal: int
    name: str
    hypothesis: str
    verdict: QuantExperimentVerdict
    summary: str
    template: str = "fixture"
    parameters: dict[str, Any] = field(default_factory=dict)
    state: str = "completed"
    metrics: dict[str, Any] = field(default_factory=dict)
    repair_count: int = 0
    candidate_key: str | None = None
    parent_experiment_id: str | None = None
    feedback_artifact_id: str | None = None
    change_rationale: str | None = None
    replan_decision: QuantEvidenceReplanDecision | None = None
    latest_observation: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    data_authenticity: DataAuthenticity = DataAuthenticity.GENERATED


@dataclass(frozen=True, slots=True)
class QuantFixtureLease:
    workspace_id: str
    run_id: str
    token: str
    fencing_version: int
    expires_at: datetime
    worker_id: str = ""
    attempt_number: int = 1


@dataclass(frozen=True, slots=True)
class _WorkspaceMutationBaseline:
    state: dict[str, Any]
    storage_version: int | None
    loaded: bool
    project_references: dict[str, QuantProjectRecord]
    run_references: dict[str, QuantRunRecord]


@dataclass(frozen=True, slots=True)
class _DurableWorkspaceTruth:
    state: dict[str, Any]
    storage_version: int
    research_memory_contract_version: str | None
    evidence_replan_contract_marker: str | None
    research_decision_contract_marker: str | None
    worker_lease_token: str | None
    worker_lease_expires_at: datetime | None
    worker_lease_run_id: str | None
    worker_lease_worker_id: str | None
    worker_lease_attempt_number: int | None
    worker_fencing_version: int


class QuantStore:
    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._lock = RLock()
        self._session_factory = session_factory or get_session_factory()
        self._loaded_workspaces: set[str] = set()
        self._storage_versions: dict[str, int] = {}
        self._datasets: dict[tuple[str, str], QuantDatasetRecord] = {}
        self._market_datasets_v2: dict[tuple[str, str], QuantMarketDatasetV2Record] = {}
        self._projects: dict[str, QuantProjectRecord] = {}
        self._runs: dict[str, QuantRunRecord] = {}
        self._events: dict[str, list[QuantEventRecord]] = {}
        self._artifacts: dict[str, QuantArtifactRecord] = {}
        self._experiments: dict[str, QuantExperimentRecord] = {}

    def clear(self) -> None:
        with self._lock:
            self._projects.clear()
            self._datasets.clear()
            self._market_datasets_v2.clear()
            self._runs.clear()
            self._events.clear()
            self._artifacts.clear()
            self._experiments.clear()
            self._loaded_workspaces.clear()
            self._storage_versions.clear()

    def _ensure_workspace_loaded(self, workspace_id: str) -> None:
        if workspace_id in self._loaded_workspaces:
            return
        baseline = self._workspace_mutation_baseline(workspace_id)
        legacy_migration_started = False
        attempted_migration_state: dict[str, Any] | None = None
        try:
            with self._session_factory() as db:
                set_rls_context(db, workspace_id, "quant-repository")
                row = db.scalar(
                    select(QuantRepositoryState)
                    .where(QuantRepositoryState.workspace_id == workspace_id)
                    .with_for_update()
                )
                if row is not None:
                    repository_memory_contract_version = row.research_memory_contract_version
                    legacy_migration_started = (
                        repository_memory_contract_version
                        == LEGACY_RESEARCH_MEMORY_CONTRACT_VERSION
                    )
                    self._restore_workspace(
                        workspace_id,
                        row.state_json or {},
                        repository_memory_contract_version=repository_memory_contract_version,
                        repository_replan_contract_marker=(row.evidence_replan_contract_marker),
                        repository_research_decision_contract_marker=(
                            row.research_decision_contract_marker
                        ),
                    )
                    if legacy_migration_started:
                        attempted_migration_state = self._workspace_state(workspace_id)
                        row.state_json = attempted_migration_state
                        row.research_memory_contract_version = RESEARCH_MEMORY_CONTRACT_VERSION
                        row.row_version += 1
                        row.updated_at = _utcnow()
                        db.commit()
                    self._storage_versions[workspace_id] = row.row_version
                else:
                    self._storage_versions[workspace_id] = 0
        except Exception:
            if not legacy_migration_started:
                raise
            if attempted_migration_state is not None:
                try:
                    durable = self._durable_workspace_truth(workspace_id)
                except Exception:
                    self._restore_mutation_baseline(workspace_id, baseline)
                    raise
                if (
                    durable.research_memory_contract_version == RESEARCH_MEMORY_CONTRACT_VERSION
                    and canonical_digest(durable.state)
                    == canonical_digest(attempted_migration_state)
                ):
                    self._storage_versions[workspace_id] = durable.storage_version
                    self._loaded_workspaces.add(workspace_id)
                    return
            self._restore_mutation_baseline(workspace_id, baseline)
            raise
        self._loaded_workspaces.add(workspace_id)

    def _restore_workspace(
        self,
        workspace_id: str,
        state: dict[str, Any],
        *,
        repository_memory_contract_version: str | object = (
            _UNSET_VERIFIED_LEARNING_REPOSITORY_MARKER
        ),
        repository_replan_contract_marker: str = LEGACY_EVIDENCE_REPLAN_REPOSITORY_MARKER,
        repository_research_decision_contract_marker: str | None | object = (
            _UNSET_RESEARCH_DECISION_REPOSITORY_MARKER
        ),
    ) -> None:
        """Parse one complete workspace before replacing any cached records.

        A persisted workspace is a single transaction boundary.  Do not turn a
        late malformed legacy record into a mixed old/new in-memory cache.
        """

        if repository_memory_contract_version is _UNSET_VERIFIED_LEARNING_REPOSITORY_MARKER:
            # Direct in-memory validation has no durable repository row. Production
            # restore always supplies the independently stored marker.
            repository_memory_contract_version = _repository_memory_marker_for_state(state)
        if not isinstance(repository_memory_contract_version, str):
            raise ValueError("Persisted Quant repository Research Memory contract is invalid.")
        if (
            repository_research_decision_contract_marker
            is _UNSET_RESEARCH_DECISION_REPOSITORY_MARKER
        ):
            embedded_marker = state.get("research_decision_contract_marker")
            repository_research_decision_contract_marker = (
                embedded_marker
                if isinstance(embedded_marker, str)
                else LEGACY_RESEARCH_DECISION_REPOSITORY_MARKER
            )
        p18_repository = repository_replan_contract_marker.startswith(
            EVIDENCE_REPLAN_REPOSITORY_PREFIX
        )
        p19_repository = isinstance(
            repository_research_decision_contract_marker, str
        ) and repository_research_decision_contract_marker.startswith(
            RESEARCH_DECISION_REPOSITORY_PREFIX
        )
        verified_learning_repository = repository_memory_contract_version.startswith(
            VERIFIED_LEARNING_REPOSITORY_CONTRACT_VERSION
        )
        if (
            repository_memory_contract_version
            not in {
                RESEARCH_MEMORY_CONTRACT_VERSION,
                LEGACY_RESEARCH_MEMORY_CONTRACT_VERSION,
            }
            and not verified_learning_repository
        ):
            raise ValueError("Persisted Quant repository Research Memory contract is unsupported.")
        if (
            repository_replan_contract_marker != LEGACY_EVIDENCE_REPLAN_REPOSITORY_MARKER
            and not p18_repository
        ):
            raise ValueError("Persisted Quant repository P18 replan contract is unsupported.")
        if (
            repository_research_decision_contract_marker
            != LEGACY_RESEARCH_DECISION_REPOSITORY_MARKER
            and not p19_repository
        ):
            raise ValueError("Persisted Quant repository P19 research decision is unsupported.")
        embedded_research_decision_marker = state.get("research_decision_contract_marker")
        embedded_research_decision_report_manifest = state.get(
            "research_decision_report_manifest_digest"
        )
        if embedded_research_decision_marker is not None and (
            not isinstance(embedded_research_decision_marker, str)
            or embedded_research_decision_marker != repository_research_decision_contract_marker
        ):
            raise ValueError(
                "Persisted Quant P19 repository marker does not match its state manifest."
            )
        if p19_repository and embedded_research_decision_marker is None:
            raise ValueError("Persisted Quant P19 repository state manifest is missing.")
        if (
            not p19_repository
            and isinstance(embedded_research_decision_marker, str)
            and embedded_research_decision_marker.startswith(RESEARCH_DECISION_REPOSITORY_PREFIX)
        ):
            raise ValueError("Persisted Quant P19 repository marker was downgraded.")
        if p19_repository and not isinstance(embedded_research_decision_report_manifest, str):
            raise ValueError("Persisted Quant P19 report manifest is missing.")
        legacy_repository = (
            repository_memory_contract_version == LEGACY_RESEARCH_MEMORY_CONTRACT_VERSION
        )

        def workspace_items(section: str) -> list[dict[str, Any]]:
            raw_items = state.get(section, [])
            if not isinstance(raw_items, list):
                raise ValueError(f"Persisted Quant {section} must be a list.")
            items: list[dict[str, Any]] = []
            for item in raw_items:
                if not isinstance(item, dict):
                    raise ValueError(f"Persisted Quant {section} entries must be objects.")
                if item.get("workspace_id") != workspace_id:
                    raise ValueError(
                        f"Persisted Quant {section} entry does not belong to this workspace."
                    )
                items.append(item)
            return items

        def add_unique(records: dict[Any, Any], key: Any, record: Any, section: str) -> None:
            if key in records:
                raise ValueError(f"Persisted Quant {section} contains a duplicate identity.")
            records[key] = record

        raw_learning_policy = state.get("verified_learning_policy")
        if raw_learning_policy is None:
            learning_policy_pins: dict[str, dict[str, str]] | None = None
        elif (
            not isinstance(raw_learning_policy, dict)
            or set(raw_learning_policy)
            != {
                "schema_version",
                "pins",
                "policy_digest",
            }
            or raw_learning_policy.get("schema_version") != VERIFIED_LEARNING_POLICY_VERSION
            or not isinstance(raw_learning_policy.get("pins"), dict)
            or not isinstance(raw_learning_policy.get("policy_digest"), str)
        ):
            raise ValueError("Persisted Quant verified-learning policy marker is invalid.")
        else:
            raw_learning_pins = cast(dict[Any, Any], raw_learning_policy["pins"])
            if not raw_learning_pins or any(
                not isinstance(run_id, str)
                or not isinstance(pin, dict)
                or set(pin) != {"schema_version", "context_digest"}
                or pin.get("schema_version") != "quant-repair-memory-v1"
                or not isinstance(pin.get("context_digest"), str)
                for run_id, pin in raw_learning_pins.items()
            ):
                raise ValueError("Persisted Quant verified-learning policy pins are invalid.")
            policy_payload = {
                "schema_version": VERIFIED_LEARNING_POLICY_VERSION,
                "pins": raw_learning_pins,
            }
            if raw_learning_policy["policy_digest"] != canonical_digest(policy_payload):
                raise ValueError("Persisted Quant verified-learning policy digest is invalid.")
            expected_repository_marker = _verified_learning_repository_marker(
                raw_learning_policy["policy_digest"]
            )
            if (
                verified_learning_repository
                and repository_memory_contract_version != expected_repository_marker
            ):
                raise ValueError(
                    "Persisted Quant verified-learning repository marker does not match "
                    "its policy manifest."
                )
            learning_policy_pins = cast(dict[str, dict[str, str]], raw_learning_pins)
        if verified_learning_repository and learning_policy_pins is None:
            raise ValueError(
                "Persisted Quant verified-learning policy marker is missing for this repository."
            )
        if not verified_learning_repository and learning_policy_pins is not None:
            raise ValueError("Persisted Quant verified-learning repository marker was downgraded.")

        raw_memory_manifest = state.get("research_memory_manifest")
        if raw_memory_manifest is None:
            memory_manifest: dict[str, dict[str, str]] = {}
        elif not isinstance(raw_memory_manifest, dict) or any(
            not isinstance(run_id, str)
            or not isinstance(pin, dict)
            or set(pin) != {"contract_version", "context_digest"}
            or not isinstance(pin.get("contract_version"), str)
            or not isinstance(pin.get("context_digest"), str)
            for run_id, pin in raw_memory_manifest.items()
        ):
            raise ValueError("Persisted Quant Research Memory manifest is invalid.")
        else:
            memory_manifest = cast(dict[str, dict[str, str]], raw_memory_manifest)

        daily_records: dict[tuple[str, str], QuantDatasetRecord] = {}
        for item in workspace_items("datasets"):
            record = QuantDatasetRecord(
                **cast(
                    Any,
                    {
                        **item,
                        "dataset": QuantDailyBarDataset.model_validate(item["dataset"]),
                        "source_metadata": QuantDatasetSourceMetadata.model_validate(
                            item.get(
                                "source_metadata",
                                _legacy_dataset_source_metadata().model_dump(mode="json"),
                            )
                        ),
                        "data_quality": (
                            QuantDatasetDataQuality.model_validate(item["data_quality"])
                            if item.get("data_quality") is not None
                            else None
                        ),
                        "created_at": _datetime(item["created_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    },
                )
            )
            add_unique(daily_records, (workspace_id, record.id), record, "datasets")

        market_records: dict[tuple[str, str], QuantMarketDatasetV2Record] = {}
        for item in workspace_items("market_datasets_v2"):
            record = _restore_market_dataset_v2_record(workspace_id, item)
            add_unique(market_records, (workspace_id, record.id), record, "market_datasets_v2")

        project_records: dict[str, QuantProjectRecord] = {}
        for item in workspace_items("projects"):
            record = QuantProjectRecord(
                **cast(
                    Any,
                    {
                        **item,
                        "status": QuantProjectStatus(item["status"]),
                        "created_at": _datetime(item["created_at"]),
                        "updated_at": _datetime(item["updated_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    },
                )
            )
            add_unique(project_records, record.id, record, "projects")

        run_records: dict[str, QuantRunRecord] = {}
        run_plan_field_presence: dict[str, frozenset[str]] = {}
        run_strategy_scope_presence: dict[str, bool] = {}
        run_memory_field_presence: dict[str, frozenset[str]] = {}
        run_repair_memory_presence: dict[str, bool] = {}
        run_latest_sequence_presence: dict[str, bool] = {}
        for item in workspace_items("runs"):
            dataset_id = str(item.get("dataset_id", SPY_DAILY_FIXTURE.dataset_id))
            daily_record = daily_records.get((workspace_id, dataset_id))
            market_record = market_records.get((workspace_id, dataset_id))
            if (
                dataset_id != SPY_DAILY_FIXTURE.dataset_id
                and daily_record is None
                and market_record is None
            ):
                raise ValueError("Persisted Quant run references a missing dataset.")
            fallback_dataset = (
                daily_record.dataset if daily_record is not None else SPY_DAILY_FIXTURE
            )
            runtime_interval = item.get("runtime_interval")
            record = QuantRunRecord(
                **cast(
                    Any,
                    {
                        **item,
                        "mode": QuantRunMode(item["mode"]),
                        "state": QuantRunState(item["state"]),
                        "research_start": date.fromisoformat(
                            item.get("research_start") or fallback_dataset.covered_start.isoformat()
                        ),
                        "research_end": date.fromisoformat(
                            item.get("research_end") or fallback_dataset.covered_end.isoformat()
                        ),
                        "research_start_utc": _optional_datetime(item.get("research_start_utc")),
                        "research_end_utc": _optional_datetime(item.get("research_end_utc")),
                        "runtime_interval": (
                            BacktestInterval(runtime_interval)
                            if runtime_interval is not None
                            else None
                        ),
                        "research_loop_policy": (
                            QuantResearchLoopPolicy.model_validate(item["research_loop_policy"])
                            if item.get("research_loop_policy") is not None
                            else None
                        ),
                        "research_series_decision": (
                            QuantResearchSeriesDecision.model_validate(
                                item["research_series_decision"]
                            )
                            if item.get("research_series_decision") is not None
                            else None
                        ),
                        "research_memory": (
                            QuantResearchMemoryContext.model_validate(item["research_memory"])
                            if item.get("research_memory") is not None
                            else None
                        ),
                        "repair_memory": (
                            QuantRepairMemory.model_validate(item["repair_memory"])
                            if item.get("repair_memory") is not None
                            else None
                        ),
                        "strategy_scope": (
                            QuantStrategyScopeDecision.model_validate(item["strategy_scope"])
                            if "strategy_scope" in item
                            else _default_strategy_scope()
                        ),
                        "created_at": _datetime(item["created_at"]),
                        "updated_at": _datetime(item["updated_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    },
                )
            )
            if (
                len(record.planned_candidate_families) > 3
                or len(set(record.planned_candidate_families))
                != len(record.planned_candidate_families)
                or any(
                    family not in SUPPORTED_AGENT_CANDIDATE_FAMILIES
                    for family in record.planned_candidate_families
                )
            ):
                raise ValueError("Persisted Quant Run has an invalid executable candidate plan.")
            if (
                record.strategy_scope.status == "unsupported" and record.planned_candidate_families
            ) or (
                record.strategy_scope.status != "unsupported"
                and not record.planned_candidate_families
            ):
                raise ValueError(
                    "Persisted Quant Run strategy scope and candidate plan do not match."
                )
            if record.strategy_scope.status == "unsupported" and (
                record.state
                not in {
                    QuantRunState.WAITING_PLAN_APPROVAL,
                    QuantRunState.CANCELLED,
                }
                or record.agent_iteration != 0
                or record.used_experiments != 0
                or record.used_repairs != 0
                or record.final_conclusion is not None
            ):
                raise ValueError("Persisted unsupported Quant scope contains execution state.")
            if (
                not record.completion_criteria
                or len(record.completion_criteria) > 8
                or any(
                    not criterion.strip() or criterion != criterion.strip()
                    for criterion in record.completion_criteria
                )
            ):
                raise ValueError("Persisted Quant Run has invalid completion criteria.")
            if record.selection_objective not in SUPPORTED_AGENT_SELECTION_OBJECTIVES:
                raise ValueError("Persisted Quant Run has an invalid selection objective.")
            runtime_pin_values = (
                record.research_start_utc,
                record.research_end_utc,
                record.runtime_interval,
                record.runtime_periods_per_year,
                record.runtime_descriptor_digest,
                record.runtime_split_digest,
            )
            if market_record is None:
                if any(value is not None for value in runtime_pin_values) or (
                    record.market_run_contract_version is not None
                ):
                    raise ValueError(
                        "Persisted daily Quant run cannot contain market runtime pins."
                    )
            else:
                if record.market_run_contract_version not in {
                    None,
                    QUANT_MARKET_RUN_CONTRACT_VERSION,
                }:
                    raise ValueError("Unsupported persisted public market-run contract version.")
                if any(value is None for value in runtime_pin_values):
                    raise ValueError(
                        "Persisted market Quant run requires a complete runtime pin set."
                    )
                assert record.research_start_utc is not None
                assert record.research_end_utc is not None
                descriptor = _market_runtime_descriptor(
                    market_record,
                    coverage_start_utc=record.research_start_utc,
                    coverage_end_utc=record.research_end_utc,
                )
                split = _runtime_split(descriptor)
                if (
                    record.dataset_digest != descriptor.dataset_digest
                    or record.research_start_utc != descriptor.coverage_start_utc
                    or record.research_end_utc != descriptor.coverage_end_utc
                    or record.research_start != descriptor.coverage_start_utc.date()
                    or record.research_end != descriptor.coverage_end_utc.date()
                    or record.runtime_interval is not descriptor.interval
                    or record.runtime_periods_per_year != descriptor.periods_per_year
                    or record.runtime_descriptor_digest != descriptor.descriptor_digest
                    or record.runtime_split_digest != split.seal_digest
                    or record.data_authenticity is not descriptor.data_authenticity
                ):
                    raise ValueError(
                        "Persisted market Quant run runtime pins do not match the stored dataset."
                    )
            add_unique(run_records, record.id, record, "runs")
            run_plan_field_presence[record.id] = frozenset(
                field
                for field in (
                    "planned_candidate_families",
                    "selection_objective",
                    "completion_criteria",
                )
                if field in item
            )
            run_strategy_scope_presence[record.id] = "strategy_scope" in item
            run_memory_field_presence[record.id] = frozenset(
                field
                for field in (
                    "research_memory_contract_version",
                    "research_memory",
                )
                if field in item
            )
            run_repair_memory_presence[record.id] = "repair_memory" in item
            run_latest_sequence_presence[record.id] = "latest_sequence" in item

        legacy_memory_run_ids: set[str] = set()
        # The external repository contract is the downgrade boundary. Only a
        # row explicitly marked by the database migration may omit both Run
        # fields; current rows cannot become "legacy" by deleting JSON fields.
        for run in run_records.values():
            memory_presence = run_memory_field_presence[run.id]
            if not memory_presence:
                if not legacy_repository:
                    raise ValueError(
                        "Persisted Quant Research Memory identity is required "
                        "by the repository contract."
                    )
                if (
                    run.research_memory_contract_version is not None
                    or run.research_memory is not None
                ):
                    raise ValueError("Persisted Quant Research Memory legacy identity is invalid.")
                run.research_memory = self._empty_research_memory()
                legacy_memory_run_ids.add(run.id)
                continue
            if memory_presence != frozenset(
                {
                    "research_memory_contract_version",
                    "research_memory",
                }
            ):
                raise ValueError("Persisted Quant Research Memory identity is incomplete.")
            if (
                run.research_memory_contract_version != RESEARCH_MEMORY_CONTRACT_VERSION
                or run.research_memory is None
            ):
                raise ValueError("Persisted Quant Research Memory contract is unsupported.")
        expected_memory_manifest = {
            run.id: {
                "contract_version": RESEARCH_MEMORY_CONTRACT_VERSION,
                "context_digest": run.research_memory.context_digest,
            }
            for run in run_records.values()
            if run.research_memory_contract_version is not None and run.research_memory is not None
        }
        if memory_manifest != expected_memory_manifest:
            raise ValueError(
                "Persisted Quant Research Memory manifest does not match its required Run pins."
            )
        for run in run_records.values():
            if run_repair_memory_presence[run.id] != (run.repair_memory is not None):
                raise ValueError("Persisted Quant repair memory marker is malformed.")
        verified_learning_run_ids: set[str] = set()
        if learning_policy_pins is None:
            if any(run.repair_memory is not None for run in run_records.values()):
                raise ValueError(
                    "Persisted Quant repair memory is missing its repository policy marker."
                )
        else:
            verified_learning_run_ids = set(learning_policy_pins)
            pinned_run_ids = {
                run.id for run in run_records.values() if run.repair_memory is not None
            }
            if verified_learning_run_ids != pinned_run_ids:
                raise ValueError(
                    "Persisted Quant verified-learning policy pins do not match current Runs."
                )
            for run_id, pin in learning_policy_pins.items():
                run = run_records.get(run_id)
                if (
                    run is None
                    or run.repair_memory is None
                    or run.repair_memory.schema_version != pin["schema_version"]
                    or run.repair_memory.context_digest != pin["context_digest"]
                ):
                    raise ValueError(
                        "Persisted Quant verified-learning policy pin identity is invalid."
                    )

        for project in project_records.values():
            if project.latest_run_id is not None and project.latest_run_id not in run_records:
                raise ValueError("Persisted Quant project references a missing run.")
        for run in run_records.values():
            if run.project_id not in project_records:
                raise ValueError("Persisted Quant run references a missing project.")
            for related_run_id in (
                run.retry_of_run_id,
                run.retry_child_run_id,
                run.parent_run_id,
                run.research_series_root_run_id,
                run.research_series_child_run_id,
            ):
                if related_run_id is not None and related_run_id not in run_records:
                    raise ValueError("Persisted Quant run references a missing related run.")
            series_fields = (
                run.research_series_root_run_id,
                run.research_series_version,
            )
            if run.research_loop_policy is None:
                if any(value is not None for value in series_fields) or any(
                    value is not None
                    for value in (
                        run.research_series_child_run_id,
                        run.research_series_decision,
                    )
                ):
                    raise ValueError("Persisted Quant Run has series state without a policy.")
            else:
                if any(value is None for value in series_fields):
                    raise ValueError("Persisted Quant research series identity is incomplete.")
                if run.mode is not QuantRunMode.AUTO:
                    raise ValueError("Persisted Quant research series must use Auto Research.")
                if run.research_series_version not in {1, 2}:
                    raise ValueError("Persisted Quant research series version is unsupported.")
                assert run.research_series_root_run_id is not None
                root = run_records[run.research_series_root_run_id]
                if root.research_series_root_run_id != root.id:
                    raise ValueError("Persisted Quant research series root identity is invalid.")
                if root.research_loop_policy != run.research_loop_policy:
                    raise ValueError("Persisted Quant research series policy pins do not match.")
                if (
                    run.research_series_version == 1
                    and run.id != root.id
                    and run.retry_of_run_id is None
                ):
                    raise ValueError("Persisted Quant research series root version is invalid.")
                if run.research_series_version == 2:
                    if run.parent_run_id is None:
                        raise ValueError("Persisted Quant follow-up requires a source version.")
                    source_version = run_records[run.parent_run_id]
                    if (
                        source_version.research_series_root_run_id != root.id
                        or source_version.research_series_version != 1
                    ):
                        raise ValueError(
                            "Persisted Quant follow-up must refine series version one."
                        )
                if run.research_series_child_run_id is not None:
                    child = run_records[run.research_series_child_run_id]
                    if (
                        run.id != root.id
                        or child.research_series_root_run_id != root.id
                        or child.research_series_version != 2
                        or child.parent_run_id is None
                        or run_records[child.parent_run_id].research_series_root_run_id != root.id
                    ):
                        raise ValueError("Persisted Quant research series child link is invalid.")
            if (
                run.market_run_contract_version == QUANT_MARKET_RUN_CONTRACT_VERSION
                and run.retry_of_run_id is not None
                and run_records[run.retry_of_run_id].market_run_contract_version
                != QUANT_MARKET_RUN_CONTRACT_VERSION
            ):
                raise ValueError(
                    "Persisted public market retry must reference a public market Run."
                )
            refinement_fields = (
                run.parent_run_id,
                run.seed_candidate_id,
                run.refinement_reason,
            )
            if any(value is not None for value in refinement_fields):
                if not all(value is not None for value in refinement_fields):
                    raise ValueError(
                        "Persisted Quant refinement lineage must contain parent, seed and reason."
                    )
                if (
                    not isinstance(run.refinement_reason, str)
                    or not run.refinement_reason.strip()
                    or run.refinement_reason != run.refinement_reason.strip()
                    or len(run.refinement_reason) > 2_000
                ):
                    raise ValueError(
                        "Persisted Quant refinement reason must contain 1 to 2,000 characters."
                    )
                assert run.parent_run_id is not None
                parent = run_records[run.parent_run_id]
                relationship_error = self._refinement_pair_error(parent, run)
                if relationship_error is not None:
                    raise ValueError(f"Persisted {relationship_error}")

        for run in run_records.values():
            visited: set[str] = set()
            current = run
            while current.parent_run_id is not None:
                if current.id in visited:
                    raise ValueError("Persisted Quant refinement lineage contains a cycle.")
                visited.add(current.id)
                current = run_records[current.parent_run_id]
            if current.id in visited:
                raise ValueError("Persisted Quant refinement lineage contains a cycle.")
        retry_children_by_source: dict[str, list[QuantRunRecord]] = {}
        for child in run_records.values():
            if child.retry_of_run_id is not None:
                retry_children_by_source.setdefault(child.retry_of_run_id, []).append(child)
        for source in run_records.values():
            children = retry_children_by_source.get(source.id, [])
            if len(children) > 1:
                raise ValueError("Persisted Quant run has conflicting retry children.")
            if source.retry_child_run_id is None:
                if children:
                    raise ValueError(
                        "Persisted Quant retry child is not linked from its source Run."
                    )
                continue
            child = run_records[source.retry_child_run_id]
            relationship_error = self._retry_pair_error(source, child)
            if relationship_error is not None:
                raise ValueError(f"Persisted {relationship_error}")

        event_records: dict[str, list[QuantEventRecord]] = {}
        event_ids: set[str] = set()
        for item in workspace_items("events"):
            event = QuantEventRecord(
                **cast(
                    Any,
                    {
                        **item,
                        "occurred_at": _datetime(item["occurred_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    },
                )
            )
            if event.id in event_ids:
                raise ValueError("Persisted Quant events contain a duplicate identity.")
            if event.run_id not in run_records:
                raise ValueError("Persisted Quant event references a missing run.")
            event_ids.add(event.id)
            event_records.setdefault(event.run_id, []).append(event)

        for run_id, run in run_records.items():
            events = event_records.get(run_id, [])
            sequences = [event.sequence for event in events]
            expected_sequences = list(range(1, len(events) + 1))
            if sequences != expected_sequences:
                raise ValueError(
                    "Persisted Quant event sequences must be unique, ordered, and continuous."
                )
            if run_latest_sequence_presence[run_id]:
                if run.latest_sequence != len(events):
                    raise ValueError(
                        "Persisted Quant Run latest_sequence does not match its event stream."
                    )
            else:
                run.latest_sequence = len(events)

        for events in event_records.values():
            ordered_events = events
            for index, event in enumerate(ordered_events):
                repair_payload = event.payload.get("tool_repair")
                call_fingerprint = event.payload.get("call_fingerprint")
                is_invalid_arguments = (
                    event.event_type == "tool.failed"
                    and event.payload.get("error_code") == "INVALID_ARGUMENTS"
                )
                if is_invalid_arguments and (
                    (call_fingerprint is None) != (repair_payload is None)
                ):
                    raise ValueError(
                        "Persisted Quant invalid tool failure must retain its call "
                        "fingerprint and repair together."
                    )
                if repair_payload is None:
                    continue
                if not is_invalid_arguments or not isinstance(repair_payload, dict):
                    raise ValueError(
                        "Persisted Quant tool repair is not bound to an invalid tool failure."
                    )
                try:
                    repair = QuantToolRepair.model_validate(repair_payload)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Persisted Quant tool repair is invalid.") from exc
                if (
                    event.payload.get("action") != repair.action.value
                    or call_fingerprint != repair.call_fingerprint
                ):
                    raise ValueError(
                        "Persisted Quant tool repair identity does not match its failure."
                    )
                if index == 0:
                    raise ValueError(
                        "Persisted Quant tool repair is missing its started tool call."
                    )
                started = ordered_events[index - 1]
                started_arguments = started.payload.get("arguments")
                if (
                    started.event_type != "tool.started"
                    or started.sequence + 1 != event.sequence
                    or started.payload.get("action") != repair.action.value
                    or not isinstance(started_arguments, dict)
                    or canonical_digest(
                        {
                            "action": repair.action.value,
                            "arguments": started_arguments,
                        }
                    )
                    != repair.call_fingerprint
                ):
                    raise ValueError(
                        "Persisted Quant tool repair does not match its started tool call."
                    )

        artifact_records: dict[str, QuantArtifactRecord] = {}
        for item in workspace_items("artifacts"):
            record = QuantArtifactRecord(
                **cast(
                    Any,
                    {
                        **item,
                        "kind": QuantArtifactKind(item["kind"]),
                        "review_status": QuantArtifactReviewStatus(item["review_status"]),
                        "created_at": _datetime(item["created_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    },
                )
            )
            if record.run_id not in run_records:
                raise ValueError("Persisted Quant artifact references a missing run.")
            add_unique(artifact_records, record.id, record, "artifacts")

        traced_failed_event_ids: set[str] = set()
        learning_traces_by_id: dict[str, QuantLearningTrace] = {}
        for artifact in artifact_records.values():
            if artifact.kind is not QuantArtifactKind.LEARNING_TRACE:
                continue
            trace = self._validate_learning_trace_artifact(
                artifact=artifact,
                run=run_records[artifact.run_id],
                events=event_records.get(artifact.run_id, []),
            )
            failed_event_id = str(trace.failed_event.event_id)
            if failed_event_id in traced_failed_event_ids:
                raise ValueError("Persisted Quant repair episode has multiple learning traces.")
            traced_failed_event_ids.add(failed_event_id)
            learning_traces_by_id[str(trace.trace_id)] = trace

        for run in run_records.values():
            ordered_events = sorted(
                event_records.get(run.id, []),
                key=lambda item: item.sequence,
            )
            for index, event in enumerate(ordered_events):
                raw_receipt = event.payload.get("repair_memory_reuse")
                if event.event_type != "agent.repair_memory_reused":
                    if raw_receipt is not None:
                        raise ValueError(
                            "Persisted Quant repair reuse receipt has an invalid event type."
                        )
                    continue
                if (
                    not isinstance(raw_receipt, dict)
                    or index == 0
                    or index + 1 >= len(ordered_events)
                ):
                    raise ValueError("Persisted Quant repair reuse receipt is malformed.")
                receipt = QuantRepairMemoryReuseReceipt.model_validate(raw_receipt)
                selected = ordered_events[index - 1]
                started = ordered_events[index + 1]
                selected_arguments = selected.payload.get("arguments")
                started_arguments = started.payload.get("arguments")
                if (
                    selected.event_type != "agent.action_selected"
                    or started.event_type != "tool.started"
                    or selected.payload.get("action") != receipt.action.value
                    or started.payload.get("action") != receipt.action.value
                    or not isinstance(selected_arguments, dict)
                    or not isinstance(started_arguments, dict)
                    or selected_arguments != started_arguments
                    or canonical_digest(
                        {
                            "action": receipt.action.value,
                            "arguments": started_arguments,
                        }
                    )
                    != receipt.corrected_call_fingerprint
                ):
                    raise ValueError(
                        "Persisted Quant repair reuse receipt decision binding is invalid."
                    )
                validate_quant_tool_arguments(receipt.action, started_arguments)
                memory = run.repair_memory
                entry = (
                    next(
                        (
                            item
                            for item in memory.entries
                            if item.action == receipt.action
                            and item.failed_call_fingerprint == receipt.original_call_fingerprint
                            and item.source_trace_ids == receipt.source_trace_ids
                            and item.remove_paths == receipt.changed_paths
                            and item.tool == quant_tool_identity(receipt.action)
                        ),
                        None,
                    )
                    if memory is not None
                    else None
                )
                if entry is None or any(
                    str(source_id) not in learning_traces_by_id
                    or learning_traces_by_id[str(source_id)].outcome != "resolved"
                    for source_id in receipt.source_trace_ids
                ):
                    raise ValueError("Persisted Quant repair reuse receipt source pin is invalid.")

        for run in run_records.values():
            if run.id not in verified_learning_run_ids:
                continue
            ordered_events = sorted(
                event_records.get(run.id, []),
                key=lambda item: item.sequence,
            )
            for index, failed_event in enumerate(ordered_events):
                if (
                    failed_event.event_type != "tool.failed"
                    or failed_event.payload.get("error_code") != "INVALID_ARGUMENTS"
                    or not isinstance(failed_event.payload.get("tool_repair"), dict)
                ):
                    continue
                repair = QuantToolRepair.model_validate(failed_event.payload["tool_repair"])
                closed = False
                for later_index in range(index + 1, len(ordered_events)):
                    later = ordered_events[later_index]
                    if (
                        later.event_type == "agent.decision_failed"
                        and later.payload.get("reason_code") == "agent_contract_repair_exhausted"
                        and later.payload.get("rejected_call_fingerprint")
                        == repair.call_fingerprint
                    ):
                        closed = True
                        break
                    if later.event_type not in {"tool.completed", "tool.failed"}:
                        continue
                    if later.payload.get("action") != repair.action.value:
                        break
                    closed = True
                    break
                if closed and failed_event.id not in traced_failed_event_ids:
                    raise ValueError("Persisted Quant repair episode learning trace is missing.")

        for run in run_records.values():
            if run.strategy_scope.status == "unsupported" and any(
                artifact.run_id == run.id and artifact.kind is not QuantArtifactKind.PLAN
                for artifact in artifact_records.values()
            ):
                raise ValueError(
                    "Persisted unsupported Quant scope contains quantitative evidence."
                )
            if run.plan_artifact_id is None:
                raise ValueError("Persisted Quant Run references a missing plan artifact.")
            plan_artifact = artifact_records.get(run.plan_artifact_id)
            if (
                plan_artifact is None
                or plan_artifact.workspace_id != run.workspace_id
                or plan_artifact.run_id != run.id
                or plan_artifact.kind is not QuantArtifactKind.PLAN
            ):
                raise ValueError("Persisted Quant Run plan artifact identity is invalid.")
            content = plan_artifact.content
            run_has_strategy_scope = run_strategy_scope_presence[run.id]
            artifact_has_strategy_scope = "strategy_scope" in content
            if run_has_strategy_scope != artifact_has_strategy_scope:
                raise ValueError(
                    "Persisted Quant Run and plan artifact strategy scope fields do not match."
                )
            if run_has_strategy_scope:
                artifact_strategy_scope = QuantStrategyScopeDecision.model_validate(
                    content["strategy_scope"]
                )
                if artifact_strategy_scope.model_dump(mode="json") != run.strategy_scope.model_dump(
                    mode="json"
                ):
                    raise ValueError(
                        "Persisted Quant Run and plan artifact strategy scopes do not match."
                    )
            else:
                # A pre-S0-lite retained plan legitimately has neither side of
                # the scope pin. Materialize an explicit supported legacy
                # decision; one-sided deletion remains rejected above.
                run.strategy_scope = _legacy_strategy_scope()
                content["strategy_scope"] = run.strategy_scope.model_dump(mode="json")
            run_presence = run_plan_field_presence[run.id]
            artifact_presence = frozenset(
                field
                for field in (
                    "candidate_families",
                    "selection_objective",
                    "completion_criteria",
                )
                if field in content
            )
            expected_artifact_presence = frozenset(
                {
                    "candidate_families" if "planned_candidate_families" in run_presence else "",
                    "selection_objective" if "selection_objective" in run_presence else "",
                    "completion_criteria" if "completion_criteria" in run_presence else "",
                }
            ) - {""}
            if artifact_presence != expected_artifact_presence:
                raise ValueError(
                    "Persisted Quant Run and plan artifact executable policy fields do not match."
                )
            artifact_objective = content.get("selection_objective", "risk_adjusted_return")
            if artifact_objective not in SUPPORTED_AGENT_SELECTION_OBJECTIVES:
                raise ValueError(
                    "Persisted Quant plan artifact has an invalid selection objective."
                )
            if (
                content.get("candidate_families", list(run.planned_candidate_families))
                != list(run.planned_candidate_families)
                or artifact_objective != run.selection_objective
                or content.get("completion_criteria", list(run.completion_criteria))
                != list(run.completion_criteria)
            ):
                raise ValueError(
                    "Persisted Quant Run and plan artifact executable policy do not match."
                )
            if legacy_repository and not run_presence and not artifact_presence:
                # A retained pre-P14/P16 repository legitimately has neither
                # side of the executable-plan pin. Materialize both defaults
                # into the current durable shape during the one externally
                # marked legacy migration. Partial or current-state deletion
                # remains rejected by the presence checks above.
                content["candidate_families"] = list(run.planned_candidate_families)
                content["selection_objective"] = run.selection_objective
                content["completion_criteria"] = list(run.completion_criteria)
            memory_artifact_presence = {
                field
                for field in (
                    "research_memory_contract_version",
                    "research_memory_digest",
                )
                if field in content
            }
            if run.research_memory_contract_version is None:
                if memory_artifact_presence:
                    raise ValueError(
                        "Persisted legacy Quant Run has an unexpected Research Memory pin."
                    )
            else:
                if memory_artifact_presence != {
                    "research_memory_contract_version",
                    "research_memory_digest",
                }:
                    raise ValueError(
                        "Persisted Quant Run plan artifact Research Memory pin is incomplete."
                    )
                assert run.research_memory is not None
                if (
                    content["research_memory_contract_version"]
                    != run.research_memory_contract_version
                    or content["research_memory_digest"] != run.research_memory.context_digest
                ):
                    raise ValueError(
                        "Persisted Quant Run and plan artifact Research Memory pins do not match."
                    )

        experiment_records: dict[str, QuantExperimentRecord] = {}
        for item in workspace_items("experiments"):
            record = QuantExperimentRecord(
                **cast(
                    Any,
                    {
                        **item,
                        "verdict": QuantExperimentVerdict(item["verdict"]),
                        "replan_decision": (
                            QuantEvidenceReplanDecision.model_validate(item["replan_decision"])
                            if item.get("replan_decision") is not None
                            else None
                        ),
                        "created_at": _datetime(item["created_at"]),
                        "data_authenticity": DataAuthenticity(item["data_authenticity"]),
                    },
                )
            )
            if record.run_id not in run_records:
                raise ValueError("Persisted Quant experiment references a missing run.")
            expected_candidate_key = self.canonical_candidate_key(
                record.template, record.parameters
            )
            if (
                record.template != "fixture" and record.candidate_key != expected_candidate_key
            ) or (
                record.template == "fixture"
                and record.candidate_key is not None
                and record.candidate_key != expected_candidate_key
            ):
                raise ValueError(
                    "Persisted Quant experiment canonical identity does not match its strategy."
                )
            add_unique(experiment_records, record.id, record, "experiments")

        for run in run_records.values():
            if run.strategy_scope.status == "unsupported" and any(
                experiment.run_id == run.id for experiment in experiment_records.values()
            ):
                raise ValueError("Persisted unsupported Quant scope contains experiments.")
            if (
                run.seed_candidate_id is not None
                and run.seed_candidate_id not in experiment_records
            ):
                raise ValueError("Persisted Quant run references a missing seed candidate.")
            if run.parent_run_id is not None:
                assert run.seed_candidate_id is not None
                seed = experiment_records[run.seed_candidate_id]
                if (
                    seed.workspace_id != run.workspace_id
                    or seed.run_id != run.parent_run_id
                    or seed.state != "completed"
                    or seed.template == "fixture"
                    or not seed.parameters
                ):
                    raise ValueError(
                        "Persisted Quant refinement seed does not belong to its "
                        "completed source Run."
                    )
                try:
                    self._strategy_spec(seed.template, seed.parameters)
                except (KeyError, OverflowError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "Persisted Quant refinement seed has invalid strategy parameters."
                    ) from exc
        for experiment in experiment_records.values():
            if (
                experiment.parent_experiment_id is not None
                and experiment.parent_experiment_id not in experiment_records
            ):
                raise ValueError(
                    "Persisted Quant experiment references a missing parent candidate."
                )
            if (
                experiment.feedback_artifact_id is not None
                and experiment.feedback_artifact_id not in artifact_records
            ):
                raise ValueError(
                    "Persisted Quant experiment references a missing feedback artifact."
                )
        for artifact in artifact_records.values():
            if (
                artifact.kind is QuantArtifactKind.VALIDATION_REPORT
                and artifact.content.get("evaluation_partition") == "train"
            ):
                self._validated_training_comparison(
                    artifact.content,
                    selection_objective=run_records[artifact.run_id].selection_objective,
                )
        for artifact in artifact_records.values():
            if artifact.kind is QuantArtifactKind.ITERATION_FEEDBACK:
                self._validate_iteration_feedback_artifact(
                    run=run_records[artifact.run_id],
                    artifact=artifact,
                    experiments=experiment_records,
                    artifacts=artifact_records,
                )
        for experiment in experiment_records.values():
            if experiment.feedback_artifact_id is None:
                if experiment.replan_decision is not None:
                    raise ValueError(
                        "Persisted Quant base candidate has an unexpected replan decision."
                    )
                continue
            feedback = artifact_records[experiment.feedback_artifact_id]
            if (
                feedback.kind is not QuantArtifactKind.ITERATION_FEEDBACK
                or feedback.run_id != experiment.run_id
                or feedback.workspace_id != experiment.workspace_id
            ):
                raise ValueError(
                    "Persisted Quant experiment feedback lineage is not run-scoped feedback."
                )
            strategy_artifact = artifact_records.get(
                str(
                    _uuid(
                        "agent-artifact",
                        experiment.run_id,
                        QuantArtifactKind.STRATEGY_SPEC,
                        experiment.id,
                    )
                )
            )
            if strategy_artifact is None:
                raise ValueError(
                    "Persisted Quant feedback candidate is missing its strategy artifact."
                )
            artifact_decision_payload = strategy_artifact.content.get("replan_decision")
            if (experiment.replan_decision is None) != (artifact_decision_payload is None):
                raise ValueError(
                    "Persisted Quant candidate replan decision is only partially retained."
                )
            if experiment.replan_decision is None:
                # Genuine pre-P18 feedback-linked candidates retain their
                # established lineage without synthesizing a new decision.
                continue
            artifact_decision = QuantEvidenceReplanDecision.model_validate(
                artifact_decision_payload
            )
            if artifact_decision != experiment.replan_decision:
                raise ValueError(
                    "Persisted Quant candidate and strategy artifact replan decisions differ."
                )
            try:
                self._validate_candidate_replan_decision(
                    run=run_records[experiment.run_id],
                    candidate_template=experiment.template,
                    candidate_parameters=experiment.parameters,
                    decision=experiment.replan_decision,
                    feedback_artifact=feedback,
                    experiments=experiment_records,
                    artifacts=artifact_records,
                )
            except ValueError as exc:
                raise ValueError("Persisted Quant candidate replan decision is invalid.") from exc

        for report_artifact in artifact_records.values():
            if report_artifact.kind is not QuantArtifactKind.RESEARCH_REPORT:
                continue
            run = run_records[report_artifact.run_id]
            completed = [
                experiment
                for experiment in experiment_records.values()
                if experiment.run_id == run.id and experiment.state == "completed"
            ]
            feedback_artifact = next(
                (
                    artifact
                    for artifact in artifact_records.values()
                    if artifact.run_id == run.id
                    and artifact.kind is QuantArtifactKind.ITERATION_FEEDBACK
                ),
                None,
            )
            feedback_children = [
                experiment
                for experiment in experiment_records.values()
                if experiment.run_id == run.id and experiment.feedback_artifact_id is not None
            ]
            is_a_b_terminal = (
                run.state is QuantRunState.COMPLETED
                and feedback_artifact is not None
                and len(completed) == 2
                and all(item.template != "fixture" for item in completed)
                and not feedback_children
            )
            decision_payload = report_artifact.content.get("replan_decision")
            if decision_payload is None:
                if p18_repository and is_a_b_terminal:
                    raise ValueError(
                        "Persisted Quant P18 A/B stop report is missing its replan decision."
                    )
                continue
            decision = QuantEvidenceReplanDecision.model_validate(decision_payload)
            error = self._stop_replan_finish_error(
                run=run,
                completed=completed,
                decision=decision,
                experiments=experiment_records,
                artifacts=artifact_records,
            )
            if error is not None:
                raise ValueError("Persisted Quant P18 stop decision is invalid.")
            latest_comparison = next(
                (
                    artifact
                    for artifact in sorted(
                        artifact_records.values(), key=lambda item: item.ordinal, reverse=True
                    )
                    if artifact.run_id == run.id
                    and artifact.kind is QuantArtifactKind.VALIDATION_REPORT
                    and artifact.content.get("evaluation_partition") == "train"
                ),
                None,
            )
            if latest_comparison is None:
                raise ValueError("Persisted Quant P18 stop comparison is missing.")
            candidate_ids, ranking = self._validated_training_comparison(
                latest_comparison.content,
                selection_objective=run.selection_objective,
            )
            selected_id = report_artifact.content.get("selected_candidate_id")
            research_decision_payload = report_artifact.content.get("research_decision")
            if (
                set(candidate_ids) != {item.id for item in completed}
                or not ranking
                or (
                    selected_id not in candidate_ids
                    if research_decision_payload is not None
                    else selected_id != ranking[0]
                )
            ):
                raise ValueError(
                    "Persisted Quant P18 stop report does not retain its validated selection."
                )

        if p18_repository:
            legacy_replan_candidate_ids = sorted(
                experiment.id
                for experiment in experiment_records.values()
                if experiment.feedback_artifact_id is not None
                and experiment.replan_decision is None
            )
            if repository_replan_contract_marker != _evidence_replan_repository_marker(
                legacy_replan_candidate_ids
            ):
                raise ValueError(
                    "Persisted Quant P18 replan state does not match its repository marker."
                )

        validated_research_decisions_by_run: dict[str, QuantResearchDecision] = {}
        research_decision_report_artifacts: list[QuantArtifactRecord] = []
        research_decision_report_identities: list[dict[str, Any]] = []
        for report_artifact in artifact_records.values():
            if report_artifact.kind is not QuantArtifactKind.RESEARCH_REPORT:
                continue
            research_decision_report_artifacts.append(report_artifact)
            research_decision_report_identities.append(
                _research_decision_report_identity(report_artifact)
            )
            decision_payload = report_artifact.content.get("research_decision")
            # Decision-exempt legacy reports can retain a stable artifact digest that was
            # not derived from their content. Their artifact/content pair is still sealed
            # by the P19 repository marker; decision-bearing reports additionally require
            # a canonical self-digest.
            if decision_payload is not None and report_artifact.digest != canonical_digest(
                report_artifact.content
            ):
                raise ValueError("Persisted Quant P19 report digest is invalid.")
            if decision_payload is None:
                continue
            try:
                research_decision = QuantResearchDecision.model_validate(decision_payload)
            except ValueError as exc:
                raise ValueError(
                    "Persisted Quant P19 research decision contract is invalid."
                ) from exc
            run = run_records[report_artifact.run_id]
            completed = [
                experiment
                for experiment in experiment_records.values()
                if experiment.run_id == run.id and experiment.state == "completed"
            ]
            selected_id = report_artifact.content.get("selected_candidate_id")
            selected = experiment_records.get(str(selected_id))
            latest_comparison_artifact = next(
                (
                    artifact
                    for artifact in sorted(
                        artifact_records.values(), key=lambda item: item.ordinal, reverse=True
                    )
                    if artifact.run_id == run.id
                    and artifact.kind is QuantArtifactKind.VALIDATION_REPORT
                    and artifact.content.get("evaluation_partition") == "train"
                ),
                None,
            )
            decision_error = self._validate_research_decision(
                run=run,
                selected=selected,
                completed=completed,
                comparison_artifact=latest_comparison_artifact,
                decision=research_decision,
            )
            if decision_error is not None:
                raise ValueError(
                    f"Persisted Quant P19 research decision is invalid: {decision_error}."
                )
            if run.id in validated_research_decisions_by_run:
                raise ValueError("Persisted Quant P19 run has multiple research decisions.")
            validated_research_decisions_by_run[run.id] = research_decision
            assert latest_comparison_artifact is not None
            comparison_rows = latest_comparison_artifact.content.get("candidates")
            selected_row = next(
                (
                    item
                    for item in (comparison_rows if isinstance(comparison_rows, list) else [])
                    if isinstance(item, dict) and item.get("candidate_id") == selected_id
                ),
                None,
            )
            generalization = report_artifact.content.get("generalization")
            if (
                selected_row is None
                or report_artifact.content.get("walk_forward") != selected_row.get("walk_forward")
                or not isinstance(generalization, dict)
                or generalization.get("selected_candidate_id") != selected_id
            ):
                raise ValueError(
                    "Persisted Quant P19 report evidence does not match its selected candidate."
                )
        research_decision_comparison_identities = _research_decision_comparison_identities(
            research_decision_report_artifacts,
            artifact_records,
        )
        if p19_repository and (
            repository_research_decision_contract_marker
            != _research_decision_repository_marker(
                research_decision_report_identities,
                research_decision_comparison_identities,
            )
        ):
            raise ValueError(
                "Persisted Quant P19 decision state does not match its repository marker."
            )
        if p19_repository and (
            embedded_research_decision_report_manifest
            != _research_decision_report_manifest_digest(research_decision_report_identities)
        ):
            raise ValueError("Persisted Quant P19 report manifest is invalid.")

        reports_by_run: dict[str, list[QuantArtifactRecord]] = {}
        robustness_by_run: dict[str, list[QuantArtifactRecord]] = {}
        for artifact in artifact_records.values():
            if artifact.kind is QuantArtifactKind.RESEARCH_REPORT:
                reports_by_run.setdefault(artifact.run_id, []).append(artifact)
            elif artifact.kind is QuantArtifactKind.ROBUSTNESS_SENSITIVITY:
                robustness_by_run.setdefault(artifact.run_id, []).append(artifact)

        w3_run_ids = set(robustness_by_run)
        for run_id, reports in reports_by_run.items():
            if any("robustness_sensitivity" in report.content for report in reports):
                w3_run_ids.add(run_id)
        for run_id in w3_run_ids:
            run = run_records.get(run_id)
            reports = reports_by_run.get(run_id, [])
            robustness_artifacts = robustness_by_run.get(run_id, [])
            if run is None or len(reports) != 1 or len(robustness_artifacts) != 1:
                raise ValueError(
                    "Persisted Quant W3 Run must retain exactly one linked robustness artifact."
                )
            report_artifact = reports[0]
            robustness_artifact = robustness_artifacts[0]
            selected_id = report_artifact.content.get("selected_candidate_id")
            selected = experiment_records.get(selected_id) if isinstance(selected_id, str) else None
            if selected is None:
                raise ValueError(
                    "Persisted Quant robustness sensitivity requires a selected candidate."
                )
            decision_payload = report_artifact.content.get("research_decision")
            source_comparison_id = (
                decision_payload.get("source_comparison_artifact_id")
                if isinstance(decision_payload, dict)
                else None
            )
            if source_comparison_id is None and decision_payload is None:
                try:
                    legacy_w3_contract = QuantRobustnessSensitivity.model_validate(
                        robustness_artifact.content
                    )
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "Persisted Quant robustness sensitivity contract is invalid."
                    ) from exc
                source_comparison_id = legacy_w3_contract.final_training_comparison.artifact_id
            comparison_artifact = (
                artifact_records.get(source_comparison_id)
                if isinstance(source_comparison_id, str)
                else None
            )
            if comparison_artifact is None:
                raise ValueError("Persisted Quant robustness sensitivity comparison is missing.")
            daily_record = daily_records.get((workspace_id, run.dataset_id))
            market_record = market_records.get((workspace_id, run.dataset_id))
            runtime = _restored_runtime_descriptor(
                run,
                daily_record=daily_record,
                market_record=market_record,
            )
            self._validate_robustness_sensitivity_artifact(
                run=run,
                selected=selected,
                comparison_artifact=comparison_artifact,
                robustness_artifact=robustness_artifact,
                report_artifact=report_artifact,
                runtime=runtime,
                runtime_split=_runtime_split(runtime),
            )

        if legacy_memory_run_ids:
            # Materialize the legacy rows once into the exact current contract.
            # Mark every legacy source current before composing so the result is
            # stable on the next strict reload and does not depend on the old
            # missing-event fallback.
            for run_id in legacy_memory_run_ids:
                run_records[
                    run_id
                ].research_memory_contract_version = RESEARCH_MEMORY_CONTRACT_VERSION

            non_retry_runs = sorted(
                (
                    run_records[run_id]
                    for run_id in legacy_memory_run_ids
                    if run_records[run_id].retry_of_run_id is None
                ),
                key=lambda item: (item.created_at, item.id),
            )
            for run in non_retry_runs:
                terminal_override = (
                    run.parent_run_id
                    if run.research_loop_policy is not None and run.research_series_version == 2
                    else None
                )
                run.research_memory = self._compose_research_memory_pin(
                    run,
                    runs=run_records,
                    experiments=experiment_records,
                    artifacts=artifact_records,
                    events=event_records,
                    daily_records=daily_records,
                    market_records=market_records,
                    terminal_source_override=terminal_override,
                )

            pending_retry_ids = {
                run_id
                for run_id in legacy_memory_run_ids
                if run_records[run_id].retry_of_run_id is not None
            }
            while pending_retry_ids:
                progressed = False
                for run_id in sorted(pending_retry_ids):
                    run = run_records[run_id]
                    assert run.retry_of_run_id is not None
                    retry_source = run_records.get(run.retry_of_run_id)
                    if retry_source is None or retry_source.research_memory is None:
                        continue
                    run.research_memory = retry_source.research_memory.model_copy(deep=True)
                    pending_retry_ids.remove(run_id)
                    progressed = True
                    break
                if not progressed:
                    raise ValueError(
                        "Persisted legacy Quant Retry Research Memory cannot be materialized."
                    )

            for run_id in legacy_memory_run_ids:
                run = run_records[run_id]
                assert run.research_memory is not None
                assert run.plan_artifact_id is not None
                plan_artifact = artifact_records[run.plan_artifact_id]
                plan_artifact.content["research_memory_contract_version"] = (
                    RESEARCH_MEMORY_CONTRACT_VERSION
                )
                plan_artifact.content["research_memory_digest"] = run.research_memory.context_digest

        for run in run_records.values():
            assert run.research_memory is not None
            self._validate_restored_research_memory(
                run=run,
                memory=run.research_memory,
                runs=run_records,
                experiments=experiment_records,
                artifacts=artifact_records,
                events=event_records,
                daily_records=daily_records,
                market_records=market_records,
            )
            self._validate_restored_repair_memory(
                run=run,
                runs=run_records,
                artifacts=artifact_records,
            )

        series_roots = [
            run
            for run in run_records.values()
            if run.research_loop_policy is not None
            and run.research_series_root_run_id == run.id
            and run.retry_of_run_id is None
        ]
        for root in series_roots:
            version_children = [
                run
                for run in run_records.values()
                if run.research_series_root_run_id == root.id
                and run.research_series_version == 2
                and run.retry_of_run_id is None
            ]
            if len(version_children) > 1:
                raise ValueError("Persisted Quant research series has multiple follow-up versions.")
            if root.research_series_child_run_id is None:
                if version_children:
                    raise ValueError("Persisted Quant research series has an orphan follow-up.")
                if (
                    root.research_series_decision is not None
                    and root.research_series_decision.action == "refine_selected"
                ):
                    raise ValueError("Persisted Quant refinement decision has no follow-up Run.")
                continue
            if (
                len(version_children) != 1
                or version_children[0].id != root.research_series_child_run_id
            ):
                raise ValueError("Persisted Quant research series child link is not unique.")
            child = version_children[0]
            assert child.parent_run_id is not None
            source = run_records[child.parent_run_id]
            decision = source.research_series_decision
            if decision is None or decision.action != "refine_selected":
                raise ValueError("Persisted Quant series child requires a refinement decision.")
            if decision.seed_candidate_id != child.seed_candidate_id:
                raise ValueError("Persisted Quant series child seed differs from its decision.")
            comparison = artifact_records.get(decision.source_comparison_artifact_id)
            if (
                comparison is None
                or comparison.run_id != source.id
                or comparison.kind is not QuantArtifactKind.VALIDATION_REPORT
                or comparison.content.get("evaluation_partition") != "train"
            ):
                raise ValueError("Persisted Quant series decision comparison is invalid.")
            latest_comparison = max(
                (
                    artifact
                    for artifact in artifact_records.values()
                    if artifact.run_id == source.id
                    and artifact.kind is QuantArtifactKind.VALIDATION_REPORT
                    and artifact.content.get("evaluation_partition") == "train"
                ),
                key=lambda artifact: artifact.ordinal,
                default=None,
            )
            ranking = comparison.content.get("ranking")
            candidate_rows = comparison.content.get("candidates")
            comparison_candidate_ids = (
                {
                    item.get("candidate_id")
                    for item in candidate_rows
                    if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
                }
                if isinstance(candidate_rows, list)
                else set()
            )
            completed_source_ids = {
                experiment.id
                for experiment in experiment_records.values()
                if experiment.run_id == source.id and experiment.state == "completed"
            }
            validated_source_decision = validated_research_decisions_by_run.get(source.id)
            expected_seed_candidate_id = (
                validated_source_decision.selected_candidate_id
                if validated_source_decision is not None
                else (ranking[0] if isinstance(ranking, list) and ranking else None)
            )
            latest_candidate_artifact_ordinal = max(
                (
                    artifact.ordinal
                    for artifact in artifact_records.values()
                    if artifact.run_id == source.id
                    and artifact.kind
                    in {
                        QuantArtifactKind.STRATEGY_SPEC,
                        QuantArtifactKind.BACKTEST_RESULT,
                    }
                ),
                default=0,
            )
            if (
                latest_comparison is None
                or latest_comparison.id != comparison.id
                or comparison.ordinal <= latest_candidate_artifact_ordinal
                or not isinstance(ranking, list)
                or not ranking
                or comparison_candidate_ids != completed_source_ids
                or len(ranking) != len(completed_source_ids)
                or set(ranking) != completed_source_ids
                or expected_seed_candidate_id != decision.seed_candidate_id
                or (
                    validated_source_decision is not None
                    and validated_source_decision.source_comparison_artifact_id != comparison.id
                )
                or decision.seed_candidate_id not in comparison_candidate_ids
            ):
                raise ValueError("Persisted Quant series decision is not the final selection.")
            exact_descriptor = (
                child.workspace_id,
                child.project_id,
                child.dataset_id,
                child.dataset_digest,
                child.research_start,
                child.research_end,
                child.research_start_utc,
                child.research_end_utc,
                child.runtime_interval,
                child.runtime_periods_per_year,
                child.runtime_descriptor_digest,
                child.runtime_split_digest,
                child.market_run_contract_version,
                child.provider,
                child.model,
                child.strategy_scope.model_dump(mode="json"),
            )
            source_descriptor = (
                source.workspace_id,
                source.project_id,
                source.dataset_id,
                source.dataset_digest,
                source.research_start,
                source.research_end,
                source.research_start_utc,
                source.research_end_utc,
                source.runtime_interval,
                source.runtime_periods_per_year,
                source.runtime_descriptor_digest,
                source.runtime_split_digest,
                source.market_run_contract_version,
                source.provider,
                source.model,
                source.strategy_scope.model_dump(mode="json"),
            )
            if exact_descriptor != source_descriptor:
                raise ValueError("Persisted Quant series descriptor policy is not exact.")
            version_one_keys = {
                experiment.candidate_key
                for experiment in experiment_records.values()
                if experiment.candidate_key is not None
                and run_records[experiment.run_id].research_series_root_run_id == root.id
                and run_records[experiment.run_id].research_series_version == 1
            }
            version_two_keys = {
                experiment.candidate_key
                for experiment in experiment_records.values()
                if experiment.candidate_key is not None
                and run_records[experiment.run_id].research_series_root_run_id == root.id
                and run_records[experiment.run_id].research_series_version == 2
            }
            if version_one_keys & version_two_keys:
                raise ValueError("Persisted Quant research series repeats an ancestor strategy.")

        def foreign_collision(existing: Any, record: Any) -> bool:
            return existing is not None and existing.workspace_id != workspace_id

        for record in project_records.values():
            if foreign_collision(self._projects.get(record.id), record):
                raise ValueError(
                    "Persisted Quant project identity collides with another workspace."
                )
        for record in run_records.values():
            if foreign_collision(self._runs.get(record.id), record):
                raise ValueError("Persisted Quant run identity collides with another workspace.")
        for record in artifact_records.values():
            if foreign_collision(self._artifacts.get(record.id), record):
                raise ValueError(
                    "Persisted Quant artifact identity collides with another workspace."
                )
        for record in experiment_records.values():
            if foreign_collision(self._experiments.get(record.id), record):
                raise ValueError(
                    "Persisted Quant experiment identity collides with another workspace."
                )
        if any(
            any(event.workspace_id != workspace_id for event in self._events[run_id])
            for run_id in event_records
            if run_id in self._events
        ):
            raise ValueError("Persisted Quant event run identity collides with another workspace.")

        # All parsing and relationship checks passed. Replace only this workspace.
        self._datasets = {
            **{key: record for key, record in self._datasets.items() if key[0] != workspace_id},
            **daily_records,
        }
        self._market_datasets_v2 = {
            **{
                key: record
                for key, record in self._market_datasets_v2.items()
                if key[0] != workspace_id
            },
            **market_records,
        }
        self._projects = {
            **{
                key: record
                for key, record in self._projects.items()
                if record.workspace_id != workspace_id
            },
            **project_records,
        }
        self._runs = {
            **{
                key: record
                for key, record in self._runs.items()
                if record.workspace_id != workspace_id
            },
            **run_records,
        }
        self._artifacts = {
            **{
                key: record
                for key, record in self._artifacts.items()
                if record.workspace_id != workspace_id
            },
            **artifact_records,
        }
        self._experiments = {
            **{
                key: record
                for key, record in self._experiments.items()
                if record.workspace_id != workspace_id
            },
            **experiment_records,
        }
        retained_events = {
            run_id: [event for event in events if event.workspace_id != workspace_id]
            for run_id, events in self._events.items()
        }
        self._events = {
            **{run_id: events for run_id, events in retained_events.items() if events},
            **event_records,
        }

    def _workspace_state(self, workspace_id: str) -> dict[str, Any]:
        report_artifacts = [
            artifact
            for artifact in self._artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.kind is QuantArtifactKind.RESEARCH_REPORT
        ]
        report_identities = [
            _research_decision_report_identity(artifact) for artifact in report_artifacts
        ]
        comparison_identities = _research_decision_comparison_identities(
            report_artifacts,
            self._artifacts,
        )
        learning_policy_pins = {
            row.id: {
                "schema_version": row.repair_memory.schema_version,
                "context_digest": row.repair_memory.context_digest,
            }
            for row in sorted(self._runs.values(), key=lambda item: item.id)
            if row.workspace_id == workspace_id and row.repair_memory is not None
        }
        learning_policy_payload = {
            "schema_version": VERIFIED_LEARNING_POLICY_VERSION,
            "pins": learning_policy_pins,
        }
        return _json_value(
            {
                **(
                    {
                        "verified_learning_policy": {
                            **learning_policy_payload,
                            "policy_digest": canonical_digest(learning_policy_payload),
                        }
                    }
                    if learning_policy_pins
                    else {}
                ),
                "research_decision_contract_marker": _research_decision_repository_marker(
                    report_identities,
                    comparison_identities,
                ),
                "research_decision_report_manifest_digest": (
                    _research_decision_report_manifest_digest(report_identities)
                ),
                "datasets": [
                    {
                        **asdict(row),
                        "dataset": row.dataset.model_dump(mode="json"),
                    }
                    for row in self._datasets.values()
                    if row.workspace_id == workspace_id
                ],
                "market_datasets_v2": [
                    {
                        "id": row.id,
                        "workspace_id": row.workspace_id,
                        "name": row.name,
                        "dataset": row.dataset.model_dump(mode="json"),
                        "evidence": row.evidence.model_dump(mode="json"),
                        "quality": row.quality.model_dump(mode="json"),
                        "record_digest": row.record_digest,
                        "created_at": row.created_at,
                        "data_authenticity": row.data_authenticity,
                    }
                    for row in self._market_datasets_v2.values()
                    if row.workspace_id == workspace_id
                ],
                "projects": [
                    asdict(row)
                    for row in self._projects.values()
                    if row.workspace_id == workspace_id
                ],
                "runs": [
                    {
                        key: value
                        for key, value in asdict(row).items()
                        if (
                            value is not None
                            or key
                            not in {
                                "research_start_utc",
                                "research_end_utc",
                                "runtime_interval",
                                "runtime_periods_per_year",
                                "runtime_descriptor_digest",
                                "runtime_split_digest",
                                "market_run_contract_version",
                            }
                        )
                        and not (
                            row.research_memory_contract_version is None
                            and key
                            in {
                                "research_memory_contract_version",
                                "research_memory",
                            }
                        )
                        and not (row.repair_memory is None and key == "repair_memory")
                    }
                    for row in self._runs.values()
                    if row.workspace_id == workspace_id
                ],
                "events": [
                    asdict(row)
                    for rows in self._events.values()
                    for row in rows
                    if row.workspace_id == workspace_id
                ],
                "artifacts": [
                    asdict(row)
                    for row in self._artifacts.values()
                    if row.workspace_id == workspace_id
                ],
                "experiments": [
                    asdict(row)
                    for row in self._experiments.values()
                    if row.workspace_id == workspace_id
                ],
                "research_memory_manifest": {
                    row.id: {
                        "contract_version": row.research_memory_contract_version,
                        "context_digest": row.research_memory.context_digest,
                    }
                    for row in sorted(self._runs.values(), key=lambda item: item.id)
                    if row.workspace_id == workspace_id
                    and row.research_memory_contract_version is not None
                    and row.research_memory is not None
                },
            }
        )

    def _workspace_mutation_baseline(self, workspace_id: str) -> _WorkspaceMutationBaseline:
        return _WorkspaceMutationBaseline(
            state=self._workspace_state(workspace_id),
            storage_version=self._storage_versions.get(workspace_id),
            loaded=workspace_id in self._loaded_workspaces,
            project_references={
                record.id: record
                for record in self._projects.values()
                if record.workspace_id == workspace_id
            },
            run_references={
                record.id: record
                for record in self._runs.values()
                if record.workspace_id == workspace_id
            },
        )

    def _durable_workspace_truth(self, workspace_id: str) -> _DurableWorkspaceTruth:
        """Read the committed repository row through an independent session."""

        with self._session_factory() as db:
            set_rls_context(db, workspace_id, "quant-durable-reconciliation")
            row = db.get(QuantRepositoryState, workspace_id)
            if row is None:
                return _DurableWorkspaceTruth(
                    state={},
                    storage_version=0,
                    research_memory_contract_version=None,
                    evidence_replan_contract_marker=None,
                    research_decision_contract_marker=None,
                    worker_lease_token=None,
                    worker_lease_expires_at=None,
                    worker_lease_run_id=None,
                    worker_lease_worker_id=None,
                    worker_lease_attempt_number=None,
                    worker_fencing_version=0,
                )
            return _DurableWorkspaceTruth(
                state=_json_value(row.state_json or {}),
                storage_version=row.row_version,
                research_memory_contract_version=row.research_memory_contract_version,
                evidence_replan_contract_marker=row.evidence_replan_contract_marker,
                research_decision_contract_marker=row.research_decision_contract_marker,
                worker_lease_token=row.worker_lease_token,
                worker_lease_expires_at=row.worker_lease_expires_at,
                worker_lease_run_id=row.worker_lease_run_id,
                worker_lease_worker_id=row.worker_lease_worker_id,
                worker_lease_attempt_number=row.worker_lease_attempt_number,
                worker_fencing_version=row.worker_fencing_version,
            )

    @staticmethod
    def _copy_record_fields(source: Any, target: Any) -> None:
        for item in dataclass_fields(source):
            setattr(target, item.name, getattr(source, item.name))

    def _restore_mutation_baseline(
        self, workspace_id: str, baseline: _WorkspaceMutationBaseline
    ) -> None:
        """Restore persisted values while preserving exposed project/run identities."""

        self._restore_workspace_preserving_references(
            workspace_id,
            baseline.state,
            baseline,
            repository_memory_contract_version=_repository_memory_marker_for_state(baseline.state),
        )
        if baseline.storage_version is None:
            self._storage_versions.pop(workspace_id, None)
        else:
            self._storage_versions[workspace_id] = baseline.storage_version
        if baseline.loaded:
            self._loaded_workspaces.add(workspace_id)
        else:
            self._loaded_workspaces.discard(workspace_id)

    def _restore_workspace_preserving_references(
        self,
        workspace_id: str,
        state: dict[str, Any],
        baseline: _WorkspaceMutationBaseline,
        *,
        repository_memory_contract_version: str | object = (
            _UNSET_VERIFIED_LEARNING_REPOSITORY_MARKER
        ),
        repository_replan_contract_marker: str = LEGACY_EVIDENCE_REPLAN_REPOSITORY_MARKER,
        repository_research_decision_contract_marker: str | None | object = (
            _UNSET_RESEARCH_DECISION_REPOSITORY_MARKER
        ),
    ) -> None:
        """Install validated state without leaving previously returned records stale."""

        self._restore_workspace(
            workspace_id,
            state,
            repository_memory_contract_version=repository_memory_contract_version,
            repository_replan_contract_marker=repository_replan_contract_marker,
            repository_research_decision_contract_marker=(
                repository_research_decision_contract_marker
            ),
        )
        for record_id, original in baseline.project_references.items():
            restored = self._projects.get(record_id)
            if restored is None:
                continue
            self._copy_record_fields(restored, original)
            self._projects[record_id] = original
        for record_id, original in baseline.run_references.items():
            restored = self._runs.get(record_id)
            if restored is None:
                continue
            self._copy_record_fields(restored, original)
            self._runs[record_id] = original

    def _persist_workspace_or_restore(
        self,
        workspace_id: str,
        baseline: _WorkspaceMutationBaseline,
    ) -> None:
        """Resolve a write exception against committed payload identity."""

        attempted_state = self._workspace_state(workspace_id)
        try:
            self._persist_workspace(workspace_id)
        except Exception as exc:
            durable = self._durable_workspace_truth(workspace_id)
            durable_digest = canonical_digest(durable.state)
            attempted_digest = canonical_digest(attempted_state)
            baseline_digest = canonical_digest(baseline.state)
            attempted_repository_marker = _repository_memory_marker_for_state(attempted_state)
            baseline_repository_marker = _repository_memory_marker_for_state(baseline.state)
            if (
                durable_digest == attempted_digest
                and durable.research_memory_contract_version == attempted_repository_marker
            ):
                self._storage_versions[workspace_id] = durable.storage_version
                self._loaded_workspaces.add(workspace_id)
                return
            if (
                durable_digest == baseline_digest
                and durable.research_memory_contract_version == baseline_repository_marker
            ):
                self._restore_mutation_baseline(workspace_id, baseline)
                self._storage_versions[workspace_id] = durable.storage_version
                raise
            self._restore_workspace_preserving_references(
                workspace_id,
                durable.state,
                baseline,
                repository_memory_contract_version=(
                    durable.research_memory_contract_version or RESEARCH_MEMORY_CONTRACT_VERSION
                ),
                repository_replan_contract_marker=(
                    durable.evidence_replan_contract_marker
                    or LEGACY_EVIDENCE_REPLAN_REPOSITORY_MARKER
                ),
                repository_research_decision_contract_marker=(
                    durable.research_decision_contract_marker
                    or LEGACY_RESEARCH_DECISION_REPOSITORY_MARKER
                ),
            )
            self._storage_versions[workspace_id] = durable.storage_version
            self._loaded_workspaces.add(workspace_id)
            raise RuntimeError(
                "Quant workspace persistence diverged from both the baseline and attempted state."
            ) from exc

    def _persist_workspace(self, workspace_id: str) -> None:
        expected = self._storage_versions.get(workspace_id, 0)
        legacy_replan_candidate_ids = sorted(
            experiment.id
            for experiment in self._experiments.values()
            if experiment.workspace_id == workspace_id
            and experiment.feedback_artifact_id is not None
            and experiment.replan_decision is None
        )
        replan_repository_marker = _evidence_replan_repository_marker(legacy_replan_candidate_ids)
        research_decision_report_identities = [
            _research_decision_report_identity(artifact)
            for artifact in self._artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.kind is QuantArtifactKind.RESEARCH_REPORT
        ]
        research_decision_report_artifacts = [
            artifact
            for artifact in self._artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.kind is QuantArtifactKind.RESEARCH_REPORT
        ]
        research_decision_comparison_identities = _research_decision_comparison_identities(
            research_decision_report_artifacts,
            self._artifacts,
        )
        research_decision_repository_marker = _research_decision_repository_marker(
            research_decision_report_identities,
            research_decision_comparison_identities,
        )
        workspace_state = self._workspace_state(workspace_id)
        repository_memory_contract_version = _repository_memory_marker_for_state(workspace_state)
        with self._session_factory() as db:
            set_rls_context(db, workspace_id, "quant-repository")
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == workspace_id)
                .with_for_update()
            )
            if row is None:
                if expected != 0:
                    raise version_conflict(workspace_id, expected)
                row = QuantRepositoryState(
                    workspace_id=workspace_id,
                    state_json={},
                    research_memory_contract_version=repository_memory_contract_version,
                    evidence_replan_contract_marker=replan_repository_marker,
                    research_decision_contract_marker=research_decision_repository_marker,
                    fixture_row_version=8,
                    data_authenticity=DataAuthenticity.GENERATED.value,
                )
                db.add(row)
            elif row.row_version != expected:
                raise version_conflict(workspace_id, row.row_version)
            elif (
                row.evidence_replan_contract_marker.startswith(EVIDENCE_REPLAN_REPOSITORY_PREFIX)
                and row.evidence_replan_contract_marker != replan_repository_marker
            ):
                raise invalid_state(
                    "The P18 replan legacy boundary cannot change after repository migration."
                )
            elif row.research_decision_contract_marker.startswith(
                RESEARCH_DECISION_REPOSITORY_PREFIX
            ) and row.research_decision_contract_marker != (row.state_json or {}).get(
                "research_decision_contract_marker"
            ):
                raise invalid_state(
                    "The P19 research-decision manifest does not match durable workspace state."
                )
            elif row.research_memory_contract_version.startswith(
                VERIFIED_LEARNING_REPOSITORY_CONTRACT_VERSION
            ):
                durable_memory_marker = _repository_memory_marker_for_state(
                    _json_value(row.state_json or {})
                )
                if row.research_memory_contract_version != durable_memory_marker:
                    raise invalid_state(
                        "The verified-learning repository marker does not match durable state."
                    )
                if not repository_memory_contract_version.startswith(
                    VERIFIED_LEARNING_REPOSITORY_CONTRACT_VERSION
                ):
                    raise invalid_state(
                        "The verified-learning repository boundary cannot be downgraded."
                    )
            elif row.research_memory_contract_version not in {
                None,
                RESEARCH_MEMORY_CONTRACT_VERSION,
                LEGACY_RESEARCH_MEMORY_CONTRACT_VERSION,
            }:
                raise invalid_state(
                    "The persisted verified-learning repository marker is unsupported."
                )
            row.state_json = workspace_state
            row.research_memory_contract_version = repository_memory_contract_version
            row.evidence_replan_contract_marker = replan_repository_marker
            row.research_decision_contract_marker = research_decision_repository_marker
            row.row_version = expected + 1
            row.updated_at = _utcnow()
            db.commit()
            self._storage_versions[workspace_id] = row.row_version

    @staticmethod
    def _worker_lease_targets_run(
        *,
        workspace_id: str,
        target_run_id: str,
        target_attempt_number: int,
        token: str | None,
        fencing_version: int,
        lease_run_id: str | None,
        lease_attempt_number: int | None,
    ) -> bool:
        if token is None:
            return False
        if lease_run_id is not None:
            return lease_run_id == target_run_id and lease_attempt_number == target_attempt_number
        # Compatibility for a lease acquired before the explicit ownership
        # columns existed. The historical token was already deterministic for
        # workspace, run and fence, so only that exact target may clear it.
        return token == str(_uuid("worker-lease", workspace_id, target_run_id, fencing_version))

    @staticmethod
    def _worker_lease_matches_claim(row: QuantRepositoryState, lease: QuantFixtureLease) -> bool:
        return bool(
            row.worker_lease_token == lease.token
            and row.worker_fencing_version == lease.fencing_version
            and row.worker_lease_run_id == lease.run_id
            and row.worker_lease_worker_id == lease.worker_id
            and row.worker_lease_attempt_number == lease.attempt_number
        )

    def _invalidate_worker_lease(self, run: QuantRunRecord) -> None:
        workspace_id = run.workspace_id
        expected = self._storage_versions[workspace_id]
        with self._session_factory() as db:
            set_rls_context(db, workspace_id, "quant-api-cancel")
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == workspace_id)
                .with_for_update()
            )
            if row is None or row.row_version != expected:
                raise version_conflict(workspace_id, row.row_version if row else expected)
            if row.worker_lease_token is None and row.worker_lease_expires_at is None:
                self._storage_versions[workspace_id] = row.row_version
                return
            if not self._worker_lease_targets_run(
                workspace_id=workspace_id,
                target_run_id=run.id,
                target_attempt_number=run.attempt_number,
                token=row.worker_lease_token,
                fencing_version=row.worker_fencing_version,
                lease_run_id=row.worker_lease_run_id,
                lease_attempt_number=row.worker_lease_attempt_number,
            ):
                self._storage_versions[workspace_id] = row.row_version
                return
            row.worker_lease_token = None
            row.worker_lease_expires_at = None
            row.worker_lease_run_id = None
            row.worker_lease_worker_id = None
            row.worker_lease_attempt_number = None
            row.worker_heartbeat_at = None
            row.worker_fencing_version += 1
            row.row_version += 1
            db.commit()
            self._storage_versions[workspace_id] = row.row_version

    def _ensure_worker_lease_invalidated(self, run: QuantRunRecord) -> None:
        try:
            self._invalidate_worker_lease(run)
        except Exception:
            durable = self._durable_workspace_truth(run.workspace_id)
            self._storage_versions[run.workspace_id] = durable.storage_version
            if (
                durable.worker_lease_token is None and durable.worker_lease_expires_at is None
            ) or not self._worker_lease_targets_run(
                workspace_id=run.workspace_id,
                target_run_id=run.id,
                target_attempt_number=run.attempt_number,
                token=durable.worker_lease_token,
                fencing_version=durable.worker_fencing_version,
                lease_run_id=durable.worker_lease_run_id,
                lease_attempt_number=durable.worker_lease_attempt_number,
            ):
                return
            raise

    def claim_fixture_run(
        self,
        *,
        workspace_id: str,
        worker_id: str,
        lease_for: timedelta = timedelta(seconds=120),
    ) -> QuantFixtureLease | None:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            running = sorted(
                (
                    run
                    for run in self._runs.values()
                    if run.workspace_id == workspace_id
                    and run.state is QuantRunState.RUNNING_EXPERIMENTS
                ),
                key=lambda item: item.created_at,
            )
            if not running:
                return None
            now = _utcnow()
            with self._session_factory() as db:
                set_rls_context(db, workspace_id, worker_id)
                row = db.scalar(
                    select(QuantRepositoryState)
                    .where(QuantRepositoryState.workspace_id == workspace_id)
                    .with_for_update()
                )
                expected = self._storage_versions[workspace_id]
                if row is None or row.row_version != expected:
                    return None
                if row.worker_lease_expires_at is not None and row.worker_lease_expires_at > now:
                    return None
                row.worker_fencing_version += 1
                claimed_run = running[0]
                token = str(
                    _uuid(
                        "worker-lease",
                        workspace_id,
                        claimed_run.id,
                        claimed_run.attempt_number,
                        worker_id,
                        row.worker_fencing_version,
                    )
                )
                row.worker_lease_token = token
                row.worker_lease_run_id = claimed_run.id
                row.worker_lease_worker_id = worker_id
                row.worker_lease_attempt_number = claimed_run.attempt_number
                expires_at = now + lease_for
                row.worker_lease_expires_at = expires_at
                row.worker_heartbeat_at = now
                row.row_version += 1
                db.commit()
                self._storage_versions[workspace_id] = row.row_version
                return QuantFixtureLease(
                    workspace_id=workspace_id,
                    run_id=claimed_run.id,
                    token=token,
                    fencing_version=row.worker_fencing_version,
                    expires_at=expires_at,
                    worker_id=worker_id,
                    attempt_number=claimed_run.attempt_number,
                )

    def heartbeat_fixture_run(
        self, lease: QuantFixtureLease, lease_for: timedelta = timedelta(seconds=120)
    ) -> bool:
        now = _utcnow()
        with self._session_factory() as db:
            set_rls_context(db, lease.workspace_id, lease.token)
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == lease.workspace_id)
                .with_for_update()
            )
            if (
                row is None
                or not self._worker_lease_matches_claim(row, lease)
                or row.worker_lease_expires_at is None
                or row.worker_lease_expires_at <= now
            ):
                return False
            row.worker_heartbeat_at = now
            row.worker_lease_expires_at = now + lease_for
            db.commit()
            return True

    def execute_fixture_claim(self, lease: QuantFixtureLease, *, fixture_state: str) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if run is None or run.state is not QuantRunState.RUNNING_EXPERIMENTS:
                return False
            if not self._fixture_lease_is_current(lease):
                return False
            self._finish_run(run, fixture_state)
            # The script is built in memory and committed atomically. Recheck
            # the lease/fence/version immediately before that single durable
            # emission so cancellation or expiry cannot allow a late write.
            if not self._fixture_lease_is_current(lease, synchronize_if_stale=False):
                return False
            self._persist_workspace(lease.workspace_id)
        with self._session_factory() as db:
            set_rls_context(db, lease.workspace_id, lease.token)
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == lease.workspace_id)
                .with_for_update()
            )
            if row is not None and self._worker_lease_matches_claim(row, lease):
                row.worker_lease_token = None
                row.worker_lease_expires_at = None
                row.worker_lease_run_id = None
                row.worker_lease_worker_id = None
                row.worker_lease_attempt_number = None
                row.worker_heartbeat_at = None
                row.row_version += 1
                db.commit()
                self._storage_versions[lease.workspace_id] = row.row_version
        return True

    def _fixture_lease_is_current(
        self,
        lease: QuantFixtureLease,
        *,
        synchronize_if_stale: bool = True,
    ) -> bool:
        with self._lock, self._session_factory() as db:
            set_rls_context(db, lease.workspace_id, lease.token)
            row = db.get(QuantRepositoryState, lease.workspace_id)
            if row is None or not self._worker_lease_matches_claim(row, lease):
                return False
            cached_version = self._storage_versions.get(lease.workspace_id)
            if row.row_version != cached_version:
                if not synchronize_if_stale:
                    return False
                baseline = self._workspace_mutation_baseline(lease.workspace_id)
                self._restore_workspace_preserving_references(
                    lease.workspace_id,
                    _json_value(row.state_json or {}),
                    baseline,
                    repository_memory_contract_version=row.research_memory_contract_version,
                    repository_replan_contract_marker=row.evidence_replan_contract_marker,
                    repository_research_decision_contract_marker=(
                        row.research_decision_contract_marker
                    ),
                )
                self._storage_versions[lease.workspace_id] = row.row_version
                self._loaded_workspaces.add(lease.workspace_id)
            return bool(
                row.worker_lease_expires_at is not None and row.worker_lease_expires_at > _utcnow()
            )

    # Incremental autonomous Agent execution. The existing workspace lease is
    # deliberately reused: there is one fenced writer regardless of worker kind.
    def claim_agent_run(
        self,
        *,
        workspace_id: str,
        worker_id: str,
        lease_for: timedelta = timedelta(seconds=120),
    ) -> QuantFixtureLease | None:
        return self.claim_fixture_run(
            workspace_id=workspace_id,
            worker_id=worker_id,
            lease_for=lease_for,
        )

    @staticmethod
    def _learning_event_digest(event: QuantEventRecord) -> str:
        return canonical_digest(
            {
                "event_id": event.id,
                "workspace_id": event.workspace_id,
                "run_id": event.run_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "payload_digest": canonical_digest(_json_value(event.payload)),
                "trace_id": event.trace_id,
                "occurred_at": event.occurred_at,
            }
        )

    @classmethod
    def _learning_event_ref(cls, event: QuantEventRecord) -> QuantLearningEventRef:
        return QuantLearningEventRef(
            event_id=UUID(event.id),
            sequence=event.sequence,
            event_digest=cls._learning_event_digest(event),
        )

    @staticmethod
    def _learning_argument_at_path(
        arguments: dict[str, Any],
        path: str,
    ) -> tuple[bool, object]:
        if path == "$":
            return True, arguments
        current: object = arguments
        for segment in path.split("."):
            if not isinstance(current, dict) or segment not in current:
                return False, None
            current = current[segment]
        return True, current

    @classmethod
    def _learning_delta(
        cls,
        repair: QuantToolRepair,
        *,
        rejected_arguments: dict[str, Any],
        corrected_arguments: dict[str, Any],
    ) -> list[QuantLearningFieldDelta]:
        delta: list[QuantLearningFieldDelta] = []
        for violation in repair.violations:
            before_present, before = cls._learning_argument_at_path(
                rejected_arguments, violation.path
            )
            after_present, after = cls._learning_argument_at_path(
                corrected_arguments, violation.path
            )
            if violation.required_change == "remove":
                if not before_present or after_present:
                    raise ValueError("The corrected call did not apply its remove repair.")
                delta.append(
                    QuantLearningFieldDelta(
                        path=violation.path,
                        change="remove",
                        before_digest=canonical_digest(before),
                    )
                )
            elif violation.required_change == "supply":
                if before_present or not after_present:
                    raise ValueError("The corrected call did not apply its supply repair.")
                delta.append(
                    QuantLearningFieldDelta(
                        path=violation.path,
                        change="supply",
                        after_digest=canonical_digest(after),
                    )
                )
            else:
                if (
                    not before_present
                    or not after_present
                    or canonical_digest(before) == canonical_digest(after)
                ):
                    raise ValueError("The corrected call did not apply its replace repair.")
                delta.append(
                    QuantLearningFieldDelta(
                        path=violation.path,
                        change="replace",
                        before_digest=canonical_digest(before),
                        after_digest=canonical_digest(after),
                    )
                )
        return delta

    @staticmethod
    def _learning_context_identity(run: QuantRunRecord) -> str:
        return canonical_digest(
            {
                "workspace_id": run.workspace_id,
                "run_id": run.id,
                "attempt_number": run.attempt_number,
                "provider": run.provider,
                "model": run.model,
                "selection_objective": run.selection_objective,
                "plan_revision": run.plan_revision,
                "dataset_digest": run.dataset_digest,
                "runtime_descriptor_digest": run.runtime_descriptor_digest,
            }
        )

    def _learning_trace_for_failed_event(
        self,
        failed_event_id: str,
    ) -> QuantArtifactRecord | None:
        return next(
            (
                artifact
                for artifact in self._artifacts.values()
                if artifact.kind is QuantArtifactKind.LEARNING_TRACE
                and artifact.content.get("failed_event", {}).get("event_id") == failed_event_id
            ),
            None,
        )

    @staticmethod
    def _correction_start_matches_outcome(
        *,
        events: list[QuantEventRecord],
        correction_started: QuantEventRecord,
        outcome_event: QuantEventRecord,
        action: QuantAgentAction,
    ) -> bool:
        """Bind one tool outcome to its nearest start without crossing another tool call."""

        correction_index = next(
            (index for index, event in enumerate(events) if event.id == correction_started.id),
            -1,
        )
        outcome_index = next(
            (index for index, event in enumerate(events) if event.id == outcome_event.id),
            -1,
        )
        if (
            correction_index < 0
            or outcome_index <= correction_index
            or correction_started.event_type != "tool.started"
            or correction_started.payload.get("action") != action.value
            or outcome_event.event_type not in {"tool.completed", "tool.failed"}
            or outcome_event.payload.get("action") != action.value
        ):
            return False
        return not any(
            event.event_type in {"tool.started", "tool.completed", "tool.failed"}
            for event in events[correction_index + 1 : outcome_index]
        )

    @classmethod
    def _correction_start_for_outcome(
        cls,
        *,
        events: list[QuantEventRecord],
        outcome_event: QuantEventRecord,
        action: QuantAgentAction,
    ) -> QuantEventRecord | None:
        outcome_index = next(
            (index for index, event in enumerate(events) if event.id == outcome_event.id),
            -1,
        )
        if outcome_index <= 0:
            return None
        correction_started = next(
            (
                event
                for event in reversed(events[:outcome_index])
                if event.event_type == "tool.started"
            ),
            None,
        )
        if correction_started is None or not cls._correction_start_matches_outcome(
            events=events,
            correction_started=correction_started,
            outcome_event=outcome_event,
            action=action,
        ):
            return None
        return correction_started

    def _latest_untraced_invalid_failure(
        self,
        run: QuantRunRecord,
        *,
        before_sequence: int,
        failed_call_fingerprint: str | None = None,
        action: QuantAgentAction | None = None,
    ) -> QuantEventRecord | None:
        for event in reversed(
            self._untraced_invalid_failures(
                run,
                before_sequence=before_sequence,
                action=action,
            )
        ):
            if (
                failed_call_fingerprint is not None
                and event.payload.get("call_fingerprint") != failed_call_fingerprint
            ):
                continue
            return event
        return None

    def _untraced_invalid_failures(
        self,
        run: QuantRunRecord,
        *,
        before_sequence: int,
        action: QuantAgentAction | None = None,
    ) -> list[QuantEventRecord]:
        failures: list[QuantEventRecord] = []
        for event in self._events.get(run.id, []):
            if event.sequence >= before_sequence:
                continue
            if (
                event.event_type != "tool.failed"
                or event.payload.get("error_code") != "INVALID_ARGUMENTS"
                or not isinstance(event.payload.get("tool_repair"), dict)
            ):
                continue
            if action is not None and event.payload.get("action") != action.value:
                continue
            if self._learning_trace_for_failed_event(event.id) is None:
                failures.append(event)
        return failures

    def _publish_learning_trace(
        self,
        *,
        run: QuantRunRecord,
        failed_event: QuantEventRecord,
        outcome: Literal["resolved", "stopped", "failed"],
        outcome_event: QuantEventRecord,
        correction_started_event: QuantEventRecord | None = None,
        supporting_events: list[QuantEventRecord] | None = None,
    ) -> QuantArtifactRecord:
        existing = self._learning_trace_for_failed_event(failed_event.id)
        if existing is not None:
            return existing
        repair = QuantToolRepair.model_validate(failed_event.payload["tool_repair"])
        failed_events = self._events.get(run.id, [])
        failed_index = next(
            index for index, event in enumerate(failed_events) if event.id == failed_event.id
        )
        if failed_index == 0:
            raise ValueError("The failed repair episode is missing its rejected tool start.")
        rejected_started = failed_events[failed_index - 1]
        rejected_arguments = rejected_started.payload.get("arguments")
        if (
            rejected_started.event_type != "tool.started"
            or rejected_started.payload.get("action") != repair.action.value
            or not isinstance(rejected_arguments, dict)
        ):
            raise ValueError("The failed repair episode rejected-call identity is invalid.")
        correction_delta: list[QuantLearningFieldDelta] = []
        corrected_call_fingerprint: str | None = None
        if correction_started_event is not None:
            corrected_arguments = correction_started_event.payload.get("arguments")
            if not self._correction_start_matches_outcome(
                events=failed_events,
                correction_started=correction_started_event,
                outcome_event=outcome_event,
                action=repair.action,
            ) or not isinstance(corrected_arguments, dict):
                raise ValueError("The corrected repair episode tool start is invalid.")
            correction_delta = self._learning_delta(
                repair,
                rejected_arguments=rejected_arguments,
                corrected_arguments=corrected_arguments,
            )
            corrected_call_fingerprint = canonical_digest(
                {
                    "action": repair.action.value,
                    "arguments": corrected_arguments,
                }
            )
            continued_invalid = (
                outcome == "failed"
                and outcome_event.event_type == "tool.failed"
                and outcome_event.payload.get("error_code") == "INVALID_ARGUMENTS"
            )
            if continued_invalid:
                next_repair_payload = outcome_event.payload.get("tool_repair")
                if not isinstance(next_repair_payload, dict):
                    raise ValueError(
                        "The continued invalid repair episode is missing its next repair."
                    )
                next_repair = QuantToolRepair.model_validate(next_repair_payload)
                if (
                    outcome_event.payload.get("success") is not False
                    or outcome_event.payload.get("action") != repair.action.value
                    or outcome_event.payload.get("call_fingerprint") != corrected_call_fingerprint
                    or next_repair.action != repair.action
                    or next_repair.call_fingerprint != corrected_call_fingerprint
                    or next_repair.call_fingerprint == repair.call_fingerprint
                    or next_repair == repair
                ):
                    raise ValueError("The continued invalid repair episode identity is invalid.")
            else:
                validate_quant_tool_arguments(repair.action, corrected_arguments)
        violations = [
            QuantLearningViolation(
                path=item.path,
                code=item.code,
                required_change=item.required_change,
                allowed_values_digest=(
                    canonical_digest(item.allowed_values) if item.allowed_values else None
                ),
                rejected_value_fingerprint=item.rejected_value_fingerprint,
            )
            for item in repair.violations
        ]
        trace_id = _uuid("quant-learning-trace-v1", run.id, failed_event.id)
        trace = QuantLearningTrace(
            trace_id=trace_id,
            workspace_id=run.workspace_id,
            run_id=UUID(run.id),
            attempt_number=run.attempt_number,
            provider=run.provider,
            model=run.model,
            selection_objective=cast(Any, run.selection_objective),
            context_identity_digest=self._learning_context_identity(run),
            tool=quant_tool_identity(repair.action),
            failed_event=self._learning_event_ref(failed_event),
            failed_call_fingerprint=repair.call_fingerprint,
            violations=violations,
            correction_delta=correction_delta,
            correction_started_event=(
                self._learning_event_ref(correction_started_event)
                if correction_started_event is not None
                else None
            ),
            corrected_call_fingerprint=corrected_call_fingerprint,
            outcome=outcome,
            outcome_event=self._learning_event_ref(outcome_event),
            supporting_events=[
                self._learning_event_ref(event) for event in (supporting_events or [])
            ],
            closed_at=outcome_event.occurred_at,
        )
        artifact = self._new_agent_artifact(
            run,
            QuantArtifactKind.LEARNING_TRACE,
            "Verified tool-contract repair outcome",
            trace.model_dump(mode="json"),
            key=failed_event.id,
        )
        self._append_artifact_event(run, artifact)
        return artifact

    @classmethod
    def _validate_learning_trace_artifact(
        cls,
        *,
        artifact: QuantArtifactRecord,
        run: QuantRunRecord,
        events: list[QuantEventRecord],
    ) -> QuantLearningTrace:
        if artifact.digest != canonical_digest(artifact.content):
            raise ValueError("Persisted Quant learning trace digest is invalid.")
        try:
            trace = QuantLearningTrace.model_validate(artifact.content)
        except (TypeError, ValueError) as exc:
            raise ValueError("Persisted Quant learning trace contract is invalid.") from exc
        event_by_id = {event.id: event for event in events}

        def referenced_event(reference: QuantLearningEventRef) -> QuantEventRecord:
            event = event_by_id.get(str(reference.event_id))
            if (
                event is None
                or event.sequence != reference.sequence
                or cls._learning_event_digest(event) != reference.event_digest
            ):
                raise ValueError("Persisted Quant learning trace event reference is invalid.")
            return event

        failed_event = referenced_event(trace.failed_event)
        outcome_event = referenced_event(trace.outcome_event)
        if (
            artifact.id
            != str(
                _uuid(
                    "agent-artifact",
                    run.id,
                    QuantArtifactKind.LEARNING_TRACE.value,
                    failed_event.id,
                )
            )
            or trace.trace_id != _uuid("quant-learning-trace-v1", run.id, failed_event.id)
            or str(trace.run_id) != run.id
            or trace.workspace_id != run.workspace_id
            or trace.attempt_number != run.attempt_number
            or trace.provider != run.provider
            or trace.model != run.model
            or trace.selection_objective != run.selection_objective
            or trace.context_identity_digest != cls._learning_context_identity(run)
            or trace.tool != quant_tool_identity(trace.tool.action)
            or trace.closed_at != outcome_event.occurred_at
            or artifact.created_at < outcome_event.occurred_at
        ):
            raise ValueError("Persisted Quant learning trace identity is invalid.")
        if (
            failed_event.event_type != "tool.failed"
            or failed_event.payload.get("error_code") != "INVALID_ARGUMENTS"
            or failed_event.payload.get("call_fingerprint") != trace.failed_call_fingerprint
            or failed_event.payload.get("action") != trace.tool.action.value
            or not isinstance(failed_event.payload.get("tool_repair"), dict)
        ):
            raise ValueError("Persisted Quant learning trace failed event is invalid.")
        repair = QuantToolRepair.model_validate(failed_event.payload["tool_repair"])
        expected_violations = [
            QuantLearningViolation(
                path=item.path,
                code=item.code,
                required_change=item.required_change,
                allowed_values_digest=(
                    canonical_digest(item.allowed_values) if item.allowed_values else None
                ),
                rejected_value_fingerprint=item.rejected_value_fingerprint,
            )
            for item in repair.violations
        ]
        if trace.violations != expected_violations:
            raise ValueError("Persisted Quant learning trace violations do not match R0.")
        ordered = sorted(events, key=lambda item: item.sequence)
        failed_index = next(
            (index for index, event in enumerate(ordered) if event.id == failed_event.id),
            -1,
        )
        if failed_index <= 0:
            raise ValueError("Persisted Quant learning trace rejected call is missing.")
        rejected_started = ordered[failed_index - 1]
        rejected_arguments = rejected_started.payload.get("arguments")
        if (
            rejected_started.event_type != "tool.started"
            or rejected_started.payload.get("action") != repair.action.value
            or not isinstance(rejected_arguments, dict)
            or canonical_digest(
                {
                    "action": repair.action.value,
                    "arguments": rejected_arguments,
                }
            )
            != repair.call_fingerprint
        ):
            raise ValueError("Persisted Quant learning trace rejected call is invalid.")
        if trace.outcome == "stopped":
            if (
                outcome_event.event_type != "agent.decision_failed"
                or outcome_event.payload.get("reason_code") != "agent_contract_repair_exhausted"
                or outcome_event.payload.get("rejected_action") != repair.action.value
                or outcome_event.payload.get("rejected_call_fingerprint") != repair.call_fingerprint
            ):
                raise ValueError("Persisted Quant stopped learning trace outcome is invalid.")
            if len(trace.supporting_events) != 1:
                raise ValueError("Persisted Quant stopped learning trace is incomplete.")
            stopped_run_event = referenced_event(trace.supporting_events[0])
            if (
                stopped_run_event.event_type != "run.failed"
                or stopped_run_event.payload.get("reason_code") != "agent_contract_repair_exhausted"
                or stopped_run_event.payload.get("rejected_action") != repair.action.value
                or stopped_run_event.payload.get("rejected_call_fingerprint")
                != repair.call_fingerprint
            ):
                raise ValueError(
                    "Persisted Quant stopped learning trace terminal event is invalid."
                )
        else:
            if trace.supporting_events:
                raise ValueError(
                    "Persisted Quant corrected learning trace has unexpected supporting events."
                )
            next_tool_outcome = next(
                (
                    event
                    for event in ordered[failed_index + 1 :]
                    if event.event_type in {"tool.completed", "tool.failed"}
                ),
                None,
            )
            if next_tool_outcome is None or next_tool_outcome.id != outcome_event.id:
                raise ValueError(
                    "Persisted Quant learning trace does not bind the next tool outcome."
                )
            assert trace.correction_started_event is not None
            correction_started = referenced_event(trace.correction_started_event)
            corrected_arguments = correction_started.payload.get("arguments")
            if not cls._correction_start_matches_outcome(
                events=ordered,
                correction_started=correction_started,
                outcome_event=outcome_event,
                action=repair.action,
            ) or not isinstance(corrected_arguments, dict):
                raise ValueError("Persisted Quant learning trace correction is invalid.")
            corrected_fingerprint = canonical_digest(
                {
                    "action": repair.action.value,
                    "arguments": corrected_arguments,
                }
            )
            continued_invalid = (
                trace.outcome == "failed"
                and outcome_event.event_type == "tool.failed"
                and outcome_event.payload.get("error_code") == "INVALID_ARGUMENTS"
            )
            if continued_invalid:
                next_repair_payload = outcome_event.payload.get("tool_repair")
                if not isinstance(next_repair_payload, dict):
                    raise ValueError(
                        "Persisted Quant continued invalid learning trace is incomplete."
                    )
                next_repair = QuantToolRepair.model_validate(next_repair_payload)
                if (
                    outcome_event.payload.get("success") is not False
                    or outcome_event.payload.get("action") != repair.action.value
                    or outcome_event.payload.get("call_fingerprint") != corrected_fingerprint
                    or next_repair.action != repair.action
                    or next_repair.call_fingerprint != corrected_fingerprint
                    or next_repair.call_fingerprint == repair.call_fingerprint
                    or next_repair == repair
                ):
                    raise ValueError(
                        "Persisted Quant continued invalid learning trace identity is invalid."
                    )
            else:
                validate_quant_tool_arguments(repair.action, corrected_arguments)
            if (
                trace.corrected_call_fingerprint != corrected_fingerprint
                or trace.correction_delta
                != cls._learning_delta(
                    repair,
                    rejected_arguments=rejected_arguments,
                    corrected_arguments=corrected_arguments,
                )
                or outcome_event.payload.get("action") != repair.action.value
            ):
                raise ValueError("Persisted Quant learning trace correction delta is invalid.")
            if trace.outcome == "resolved":
                if (
                    outcome_event.event_type != "tool.completed"
                    or outcome_event.payload.get("success") is not True
                ):
                    raise ValueError("Persisted Quant resolved learning trace outcome is invalid.")
            elif (
                outcome_event.event_type != "tool.failed"
                or outcome_event.payload.get("success") is not False
            ):
                raise ValueError("Persisted Quant failed learning trace outcome is invalid.")
        published = [
            event
            for event in events
            if event.event_type == "artifact.published"
            and event.payload.get("artifact_id") == artifact.id
        ]
        if (
            len(published) != 1
            or published[0].sequence <= outcome_event.sequence
            or published[0].payload.get("artifact_kind") != QuantArtifactKind.LEARNING_TRACE.value
        ):
            raise ValueError("Persisted Quant learning trace publication order is invalid.")
        for reference in trace.supporting_events:
            supporting = referenced_event(reference)
            if not (failed_event.sequence < supporting.sequence < published[0].sequence):
                raise ValueError(
                    "Persisted Quant learning trace supporting event order is invalid."
                )
        return trace

    def record_agent_decision(
        self,
        lease: QuantFixtureLease,
        decision: QuantAgentDecision,
        *,
        reuse_receipt: QuantRepairMemoryReuseReceipt | None = None,
    ) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return False
            assert run is not None
            if reuse_receipt is not None and reuse_receipt.action != decision.action:
                raise ValueError("The repair reuse receipt does not match the decision.")
            baseline = self._workspace_mutation_baseline(lease.workspace_id)
            run.agent_status = "executing_tool"
            run.last_action = decision.action.value
            self._append_event(
                run,
                "agent.action_selected",
                {
                    "action": decision.action.value,
                    "arguments": _json_value(decision.arguments),
                    "decision_summary": decision.decision_summary,
                    "expected_result": decision.expected_result,
                    "iteration": run.agent_iteration + 1,
                    "safe_summary": decision.decision_summary,
                },
            )
            if reuse_receipt is not None:
                self._append_event(
                    run,
                    "agent.repair_memory_reused",
                    {
                        "repair_memory_reuse": reuse_receipt.model_dump(mode="json"),
                        "safe_summary": (
                            f"A verified argument repair was reused for {decision.action.value}."
                        ),
                    },
                )
            self._append_event(
                run,
                "tool.started",
                {
                    "action": decision.action.value,
                    "arguments": _json_value(decision.arguments),
                    "safe_summary": f"Tool {decision.action.value} started.",
                },
            )
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace_or_restore(lease.workspace_id, baseline)
            return True

    def complete_agent_step(
        self, lease: QuantFixtureLease, observation: QuantToolObservation
    ) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if run is None or run.workspace_id != lease.workspace_id:
                return False
            if not self._fixture_lease_is_current(lease):
                return False
            baseline = self._workspace_mutation_baseline(lease.workspace_id)
            event_type = "tool.completed" if observation.success else "tool.failed"
            outcome_event = self._append_event(
                run,
                event_type,
                {
                    "action": observation.action.value,
                    "success": observation.success,
                    "candidate_id": observation.candidate_id,
                    "artifact_ids": observation.artifact_ids,
                    "metrics_summary": observation.data.get("metrics"),
                    "error_code": observation.error_code,
                    "retryable": observation.retryable,
                    "call_fingerprint": observation.call_fingerprint,
                    "tool_repair": (
                        observation.repair.model_dump(mode="json")
                        if observation.repair is not None
                        else None
                    ),
                    "safe_summary": observation.safe_summary,
                },
            )
            run.agent_iteration += 1
            run.last_observation = observation.safe_summary
            run.consecutive_provider_failures = 0
            strict_iteration_exhausted = (
                not observation.success
                and observation.action.value == "finish_research"
                and observation.error_code in _STRICT_ITERATION_FINISH_ERRORS
                and (
                    run.used_experiments >= run.max_experiments
                    or run.agent_iteration >= run.max_agent_iterations
                )
            )
            if strict_iteration_exhausted:
                run.state = QuantRunState.FAILED
                run.agent_status = "failed"
                run.failure_reason = (
                    "The bounded research budget ended before the required 2+1 "
                    "candidate sequence completed."
                )
                self._append_event(
                    run,
                    "run.failed",
                    {
                        "state": QuantRunState.FAILED,
                        "reason_code": "strict_iteration_sequence_incomplete",
                        "safe_summary": run.failure_reason,
                    },
                )
            elif observation.terminal:
                run.agent_status = "completed"
            elif run.agent_iteration >= run.max_agent_iterations:
                run.state = QuantRunState.FAILED
                run.agent_status = "failed"
                run.failure_reason = (
                    "The Agent reached its bounded action budget before producing "
                    "a terminal research decision."
                )
                self._append_event(
                    run,
                    "run.failed",
                    {
                        "state": QuantRunState.FAILED,
                        "reason_code": "agent_iteration_budget_exhausted",
                        "safe_summary": run.failure_reason,
                    },
                )
            elif run.state not in {
                QuantRunState.COMPLETED,
                QuantRunState.FAILED,
                QuantRunState.CANCELLED,
            }:
                run.state = QuantRunState.RUNNING_EXPERIMENTS
                run.agent_status = "waiting_next_step"
            failed_event = self._latest_untraced_invalid_failure(
                run,
                before_sequence=outcome_event.sequence,
                action=observation.action,
            )
            events = self._events.get(run.id, [])
            correction_started = self._correction_start_for_outcome(
                events=events,
                outcome_event=outcome_event,
                action=observation.action,
            )
            if failed_event is not None and correction_started is not None:
                try:
                    self._publish_learning_trace(
                        run=run,
                        failed_event=failed_event,
                        outcome="resolved" if observation.success else "failed",
                        outcome_event=outcome_event,
                        correction_started_event=correction_started,
                    )
                except Exception:
                    self._restore_mutation_baseline(lease.workspace_id, baseline)
                    raise
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace_or_restore(lease.workspace_id, baseline)
        self.release_agent_claim(lease)
        return True

    def latest_invalid_tool_repair(
        self, *, workspace_id: str, run_id: str
    ) -> QuantToolRepair | None:
        """Return the latest tool observation's pending repair, across non-tool events."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self._runs.get(run_id)
            if run is None or run.workspace_id != workspace_id:
                return None
            if run.state in {
                QuantRunState.COMPLETED,
                QuantRunState.FAILED,
                QuantRunState.CANCELLED,
            }:
                return None
            events = self._events.get(run_id, [])
            for event in reversed(events):
                if event.event_type in {"run.completed", "run.failed", "run.cancelled"}:
                    return None
                if event.event_type not in {"tool.completed", "tool.failed"}:
                    continue
                if event.event_type != "tool.failed":
                    return None
                payload = event.payload
                if payload.get("error_code") != "INVALID_ARGUMENTS":
                    return None
                repair_payload = payload.get("tool_repair")
                if not isinstance(repair_payload, dict):
                    return None
                try:
                    repair = QuantToolRepair.model_validate(repair_payload)
                except (TypeError, ValueError):
                    return None
                if repair.call_fingerprint != payload.get("call_fingerprint"):
                    return None
                return repair
            return None

    def rejected_arguments_for_repair(
        self, *, workspace_id: str, run_id: str, call_fingerprint: str
    ) -> dict[str, Any] | None:
        """Return the arguments of the tool.started event that produced call_fingerprint."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self._runs.get(run_id)
            if run is None or run.workspace_id != workspace_id:
                return None
            events = self._events.get(run_id, [])
            for index, event in enumerate(events):
                if (
                    event.event_type == "tool.failed"
                    and event.payload.get("error_code") == "INVALID_ARGUMENTS"
                    and event.payload.get("call_fingerprint") == call_fingerprint
                ):
                    if index == 0:
                        return None
                    started = events[index - 1]
                    if started.event_type != "tool.started":
                        return None
                    failed_action = event.payload.get("action")
                    repair_payload = event.payload.get("tool_repair")
                    arguments = started.payload.get("arguments")
                    if (
                        not isinstance(failed_action, str)
                        or started.payload.get("action") != failed_action
                        or not isinstance(repair_payload, dict)
                        or not isinstance(arguments, dict)
                    ):
                        return None
                    try:
                        repair = QuantToolRepair.model_validate(repair_payload)
                    except (TypeError, ValueError):
                        return None
                    if (
                        repair.action.value != failed_action
                        or repair.call_fingerprint != call_fingerprint
                        or canonical_digest(
                            {
                                "action": failed_action,
                                "arguments": arguments,
                            }
                        )
                        != call_fingerprint
                    ):
                        return None
                    return arguments
            return None

    def record_agent_contract_repair_exhausted(
        self,
        lease: QuantFixtureLease,
        *,
        rejected_action: str,
        attempted_action: str,
        rejected_call_fingerprint: str,
        attempted_call_fingerprint: str,
    ) -> bool:
        """Fail honestly when the next model decision ignores a typed tool repair."""

        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return False
            assert run is not None
            baseline = self._workspace_mutation_baseline(lease.workspace_id)
            run.agent_iteration = min(
                run.max_agent_iterations,
                run.agent_iteration + 1,
            )
            run.state = QuantRunState.FAILED
            run.agent_status = "failed"
            run.failure_reason = (
                "The Agent did not apply the required contract repair before its next action."
            )
            run.last_observation = run.failure_reason
            stopped_event = self._append_event(
                run,
                "agent.decision_failed",
                {
                    "iteration": run.agent_iteration,
                    "reason_code": "agent_contract_repair_exhausted",
                    "rejected_action": rejected_action,
                    "attempted_action": attempted_action,
                    "rejected_call_fingerprint": rejected_call_fingerprint,
                    "attempted_call_fingerprint": attempted_call_fingerprint,
                    "safe_summary": run.failure_reason,
                },
            )
            run_failed_event = self._append_event(
                run,
                "run.failed",
                {
                    "state": QuantRunState.FAILED,
                    "reason_code": "agent_contract_repair_exhausted",
                    "rejected_action": rejected_action,
                    "attempted_action": attempted_action,
                    "rejected_call_fingerprint": rejected_call_fingerprint,
                    "attempted_call_fingerprint": attempted_call_fingerprint,
                    "safe_summary": run.failure_reason,
                },
            )
            failed_event = self._latest_untraced_invalid_failure(
                run,
                before_sequence=stopped_event.sequence,
                failed_call_fingerprint=rejected_call_fingerprint,
            )
            if failed_event is None:
                self._restore_mutation_baseline(lease.workspace_id, baseline)
                raise ValueError("The stopped repair episode source event is missing.")
            repair = QuantToolRepair.model_validate(failed_event.payload["tool_repair"])
            if rejected_action != repair.action.value:
                self._restore_mutation_baseline(lease.workspace_id, baseline)
                raise ValueError("The stopped repair episode action does not match its repair.")
            try:
                self._publish_learning_trace(
                    run=run,
                    failed_event=failed_event,
                    outcome="stopped",
                    outcome_event=stopped_event,
                    supporting_events=[run_failed_event],
                )
            except Exception:
                self._restore_mutation_baseline(lease.workspace_id, baseline)
                raise
            run.row_version += 1
            run.updated_at = _utcnow()
            try:
                self._persist_workspace_or_restore(lease.workspace_id, baseline)
            except Exception:
                self.release_agent_claim(lease)
                raise
        self.release_agent_claim(lease)
        return True

    def record_agent_provider_failure(
        self,
        lease: QuantFixtureLease,
        safe_summary: str,
        *,
        allow_mock_fallback: bool,
    ) -> int:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return 0
            assert run is not None
            run.agent_iteration += 1
            run.consecutive_provider_failures += 1
            run.agent_status = "waiting_next_step"
            run.last_observation = safe_summary
            self._append_event(
                run,
                "agent.decision_failed",
                {
                    "iteration": run.agent_iteration,
                    "reason_code": "provider_decision_failed",
                    "safe_summary": safe_summary,
                },
            )
            if run.agent_iteration >= run.max_agent_iterations:
                run.state = QuantRunState.FAILED
                run.agent_status = "failed"
                run.failure_reason = (
                    "The Agent reached its bounded action budget before producing "
                    "a terminal research decision."
                )
                self._append_event(
                    run,
                    "run.failed",
                    {
                        "state": QuantRunState.FAILED,
                        "reason_code": "agent_iteration_budget_exhausted",
                        "safe_summary": run.failure_reason,
                    },
                )
            elif run.consecutive_provider_failures >= MAX_CONSECUTIVE_AGENT_PROVIDER_FAILURES:
                if allow_mock_fallback:
                    run.provider = "mock"
                    run.model = None
                    self._append_event(
                        run,
                        "agent.provider_fallback",
                        {
                            "safe_summary": (
                                "The Agent switched to the deterministic Mock provider."
                            )
                        },
                    )
                else:
                    run.state = QuantRunState.FAILED
                    run.agent_status = "failed"
                    run.failure_reason = "The configured model provider remained unavailable."
                    self._append_event(
                        run,
                        "run.failed",
                        {
                            "state": QuantRunState.FAILED,
                            "reason_code": "agent_provider_unavailable",
                            "safe_summary": run.failure_reason,
                        },
                    )
            run.row_version += 1
            run.updated_at = _utcnow()
            failures = run.consecutive_provider_failures
            self._persist_workspace(lease.workspace_id)
        self.release_agent_claim(lease)
        return failures

    def mark_provider_fallback(self, lease: QuantFixtureLease) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return False
            assert run is not None
            run.provider = "mock"
            run.model = None
            self._append_event(
                run,
                "agent.provider_fallback",
                {"safe_summary": "The Agent switched to the deterministic Mock provider."},
            )
            run.row_version += 1
            self._persist_workspace(lease.workspace_id)
            return True

    def release_agent_claim(self, lease: QuantFixtureLease) -> None:
        with self._session_factory() as db:
            set_rls_context(db, lease.workspace_id, lease.token)
            row = db.scalar(
                select(QuantRepositoryState)
                .where(QuantRepositoryState.workspace_id == lease.workspace_id)
                .with_for_update()
            )
            if row is not None and self._worker_lease_matches_claim(row, lease):
                row.worker_lease_token = None
                row.worker_lease_expires_at = None
                row.worker_lease_run_id = None
                row.worker_lease_worker_id = None
                row.worker_lease_attempt_number = None
                row.worker_heartbeat_at = None
                row.row_version += 1
                db.commit()
                self._storage_versions[lease.workspace_id] = row.row_version

    def _agent_claim_is_writable(
        self, run: QuantRunRecord | None, lease: QuantFixtureLease
    ) -> bool:
        return bool(
            run is not None
            and run.state is QuantRunState.RUNNING_EXPERIMENTS
            and run.agent_status != "cancelled"
            and self._fixture_lease_is_current(lease)
        )

    def create_agent_candidate(
        self,
        lease: QuantFixtureLease,
        *,
        name: str,
        template: str,
        hypothesis: str,
        parameters: dict[str, int | float],
        change_rationale: str | None = None,
        replan_decision: QuantEvidenceReplanDecision | None = None,
    ) -> tuple[QuantExperimentRecord | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            if run.used_experiments >= run.max_experiments:
                return None, [], "EXPERIMENT_BUDGET_EXHAUSTED"
            if template not in run.planned_candidate_families:
                return None, [], "CANDIDATE_OUTSIDE_APPROVED_PLAN"
            normalized = _json_value(parameters)
            candidate_key = self.canonical_candidate_key(template, normalized)
            memory = self._validated_research_memory_pin(run.research_memory)
            if candidate_key in memory.tested_candidate_keys:
                return None, [], "RESEARCH_MEMORY_EXACT_DUPLICATE"
            real_completed = self._real_completed_candidates(run)
            feedback = self._iteration_feedback_artifact(run)
            feedback_artifact_id: str | None = None
            normalized_rationale = change_rationale.strip() if change_rationale else None
            if len(real_completed) >= 2:
                if feedback is None:
                    return None, [], "ITERATION_FEEDBACK_REQUIRED"
                if not normalized_rationale:
                    return None, [], "ITERATION_CHANGE_RATIONALE_REQUIRED"
                if replan_decision is None:
                    return None, [], "ITERATION_REPLAN_DECISION_REQUIRED"
                if any(
                    item.run_id == run.id and item.feedback_artifact_id == feedback.id
                    for item in self._experiments.values()
                ):
                    return None, [], "ITERATION_FEEDBACK_ALREADY_CONSUMED"
                try:
                    self._validate_candidate_replan_decision(
                        run=run,
                        candidate_template=template,
                        candidate_parameters=normalized,
                        decision=replan_decision,
                        feedback_artifact=feedback,
                        experiments=self._experiments,
                        artifacts=self._artifacts,
                    )
                except ValueError as exc:
                    return None, [], str(exc)
                feedback_artifact_id = feedback.id
            elif replan_decision is not None:
                return None, [], "UNEXPECTED_ITERATION_REPLAN_DECISION"
            duplicate = next(
                (
                    item
                    for item in self._experiments.values()
                    if item.run_id == run.id
                    and item.template == template
                    and item.parameters == normalized
                ),
                None,
            )
            if duplicate is not None:
                return None, [], "DUPLICATE_CANDIDATE"
            candidate_id = str(
                _uuid("agent-candidate", run.id, template, canonical_digest(normalized))
            )
            candidate = QuantExperimentRecord(
                id=candidate_id,
                workspace_id=run.workspace_id,
                run_id=run.id,
                ordinal=1 + sum(item.run_id == run.id for item in self._experiments.values()),
                name=name,
                hypothesis=hypothesis,
                verdict=QuantExperimentVerdict.NOT_VIABLE,
                summary="Candidate created and ready for local backtesting.",
                template=template,
                parameters=normalized,
                state="created",
                candidate_key=candidate_key,
                feedback_artifact_id=feedback_artifact_id,
                change_rationale=normalized_rationale,
                replan_decision=replan_decision,
                data_authenticity=run.data_authenticity,
            )
            self._experiments[candidate.id] = candidate
            artifact = self._new_agent_artifact(
                run,
                QuantArtifactKind.STRATEGY_SPEC,
                f"Strategy specification: {name}",
                {
                    "template": template,
                    "parameters": normalized,
                    "hypothesis": hypothesis,
                    "feedback_artifact_id": feedback_artifact_id,
                    "change_rationale": normalized_rationale,
                    "replan_decision": (
                        replan_decision.model_dump(mode="json")
                        if replan_decision is not None
                        else None
                    ),
                },
                key=candidate.id,
            )
            run.used_experiments += 1
            run.state = QuantRunState.GENERATING_CANDIDATES
            self._append_event(
                run,
                "candidate.generated",
                {
                    "candidate_id": candidate.id,
                    "experiment_id": candidate.id,
                    "experiment_name": candidate.name,
                    "safe_summary": f"Candidate {candidate.name} was created.",
                },
            )
            self._append_artifact_event(run, artifact)
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace(run.workspace_id)
            return candidate, [artifact.id], None

    def run_agent_backtest(
        self, lease: QuantFixtureLease, *, candidate_id: str
    ) -> tuple[QuantExperimentRecord | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            candidate = self._experiments.get(candidate_id)
            if candidate is None or candidate.run_id != run.id:
                return None, [], "UNKNOWN_CANDIDATE"
            if candidate.state == "completed":
                return None, [], "CANDIDATE_ALREADY_BACKTESTED"
            run.state = QuantRunState.RUNNING_EXPERIMENTS
            candidate.state = "running"
            self._append_event(
                run,
                "backtest.started",
                {
                    "candidate_id": candidate.id,
                    "experiment_id": candidate.id,
                    "safe_summary": f"Local training backtest started for {candidate.name}.",
                },
            )
            try:
                runtime = self._runtime_descriptor(run)
                runtime_split = _runtime_split(runtime)
                training_bars = runtime_split.training_bars
                split = runtime_split.metadata
                result = run_backtest(
                    training_bars,
                    self._strategy_spec(candidate.template, candidate.parameters),
                    BASELINE_EXECUTION,
                    cadence=runtime.cadence,
                )
            except ValueError:
                candidate.state = "failed"
                candidate.latest_observation = "The local kernel rejected the candidate parameters."
                self._append_event(
                    run,
                    "backtest.failed",
                    {
                        "candidate_id": candidate.id,
                        "experiment_id": candidate.id,
                        "reason_code": "invalid_strategy_parameters",
                        "safe_summary": candidate.latest_observation,
                    },
                )
                self._persist_workspace(run.workspace_id)
                return candidate, [], "INVALID_STRATEGY_PARAMETERS"
            metrics = self._metrics_projection(result.metrics)
            benchmark = backtest_buy_and_hold(
                training_bars,
                BASELINE_EXECUTION,
                cadence=runtime.cadence,
            )
            candidate.metrics = metrics
            candidate.state = "completed"
            candidate.verdict = (
                QuantExperimentVerdict.VIABLE
                if result.metrics.max_drawdown > benchmark.metrics.max_drawdown
                else QuantExperimentVerdict.NOT_VIABLE
            )
            candidate.summary = (
                f"Training kernel result: {metrics['trade_count']} trades, "
                f"maximum drawdown {metrics['maximum_drawdown_pct']}%."
            )
            candidate.latest_observation = candidate.summary
            artifacts = [
                self._new_agent_artifact(
                    run,
                    QuantArtifactKind.BACKTEST_RESULT,
                    f"Training backtest metrics: {candidate.name}",
                    {
                        "candidate_id": candidate.id,
                        "evaluation_partition": "train",
                        "split": split,
                        "metrics": metrics,
                    },
                    key=f"{candidate.id}:metrics",
                ),
                self._new_agent_artifact(
                    run,
                    QuantArtifactKind.EQUITY_CURVE,
                    f"Equity curve: {candidate.name}",
                    {
                        "candidate_id": candidate.id,
                        "points": [
                            {
                                "date": (
                                    point.timestamp.isoformat()
                                    if point.timestamp is not None
                                    else point.date.isoformat()
                                ),
                                "equity": round(point.equity, 4),
                            }
                            for point in result.equity_curve[
                                :: max(1, len(result.equity_curve) // 100)
                            ]
                        ],
                    },
                    key=f"{candidate.id}:equity",
                ),
                self._new_agent_artifact(
                    run,
                    QuantArtifactKind.TRADE_LOG,
                    f"Trade log: {candidate.name}",
                    {
                        "candidate_id": candidate.id,
                        "trades": [
                            {
                                "entry_date": trade.entry_date.isoformat(),
                                "exit_date": trade.exit_date.isoformat(),
                                "return_pct": round(trade.return_pct * 100, 4),
                                **(
                                    {
                                        "entry_timestamp": trade.entry_timestamp.isoformat(),
                                        "exit_timestamp": trade.exit_timestamp.isoformat(),
                                        "holding_bars": trade.holding_bars,
                                        "holding_elapsed_seconds": trade.holding_elapsed_seconds,
                                    }
                                    if trade.entry_timestamp is not None
                                    and trade.exit_timestamp is not None
                                    and trade.holding_bars is not None
                                    and trade.holding_elapsed_seconds is not None
                                    else {}
                                ),
                            }
                            for trade in result.trades
                        ],
                    },
                    key=f"{candidate.id}:trades",
                ),
            ]
            self._append_event(
                run,
                "backtest.completed",
                {
                    "candidate_id": candidate.id,
                    "experiment_id": candidate.id,
                    "safe_summary": candidate.summary,
                },
            )
            for artifact in artifacts:
                self._append_artifact_event(run, artifact)
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace(run.workspace_id)
            return candidate, [artifact.id for artifact in artifacts], None

    def revise_agent_candidate(
        self,
        lease: QuantFixtureLease,
        *,
        candidate_id: str,
        reason: str,
        parameter_patch: dict[str, int | float],
    ) -> tuple[QuantExperimentRecord | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            original = self._experiments.get(candidate_id)
            if original is None or original.run_id != run.id:
                return None, [], "UNKNOWN_CANDIDATE"
            if run.used_repairs >= run.max_repairs:
                return None, [], "REPAIR_BUDGET_EXHAUSTED"
            parameters = {**original.parameters, **_json_value(parameter_patch)}
            try:
                self._strategy_spec(original.template, parameters)
            except (KeyError, TypeError, ValueError):
                return None, [], "INVALID_STRATEGY_PARAMETERS"
            candidate_key = self.canonical_candidate_key(original.template, parameters)
            memory = self._validated_research_memory_pin(run.research_memory)
            if candidate_key in memory.tested_candidate_keys:
                return None, [], "RESEARCH_MEMORY_EXACT_DUPLICATE"
            duplicate = next(
                (
                    item
                    for item in self._experiments.values()
                    if item.run_id == run.id
                    and item.template == original.template
                    and item.parameters == parameters
                ),
                None,
            )
            if duplicate is not None:
                return None, [], "DUPLICATE_CANDIDATE"
            revised_id = str(
                _uuid(
                    "agent-revision",
                    original.id,
                    canonical_digest(parameters),
                    run.used_repairs + 1,
                )
            )
            revised = QuantExperimentRecord(
                id=revised_id,
                workspace_id=run.workspace_id,
                run_id=run.id,
                ordinal=1 + sum(item.run_id == run.id for item in self._experiments.values()),
                name=f"{original.name} revision {original.repair_count + 1}",
                hypothesis=original.hypothesis,
                verdict=QuantExperimentVerdict.NOT_VIABLE,
                summary=f"Revised because: {reason}",
                template=original.template,
                parameters=parameters,
                state="created",
                repair_count=original.repair_count + 1,
                candidate_key=candidate_key,
                parent_experiment_id=original.id,
            )
            original.state = "revised"
            self._experiments[revised.id] = revised
            artifact = self._new_agent_artifact(
                run,
                QuantArtifactKind.STRATEGY_SPEC,
                f"Revised strategy specification: {revised.name}",
                {"template": revised.template, "parameters": parameters, "reason": reason},
                key=revised.id,
            )
            run.used_repairs += 1
            run.state = QuantRunState.REPAIRING
            self._append_event(
                run,
                "repair.started",
                {
                    "candidate_id": original.id,
                    "safe_summary": f"Revision started for {original.name}.",
                },
            )
            self._append_event(
                run,
                "candidate.revised",
                {
                    "candidate_id": revised.id,
                    "experiment_id": revised.id,
                    "repair_count": revised.repair_count,
                    "safe_summary": f"Candidate revised as {revised.name}.",
                },
            )
            self._append_event(
                run,
                "repair.completed",
                {
                    "candidate_id": revised.id,
                    "repair_count": revised.repair_count,
                    "safe_summary": "Candidate revision completed.",
                },
            )
            self._append_artifact_event(run, artifact)
            run.row_version += 1
            self._persist_workspace(run.workspace_id)
            return revised, [artifact.id], None

    def compare_agent_candidates(
        self, lease: QuantFixtureLease
    ) -> tuple[dict[str, Any] | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            completed = sorted(
                (
                    item
                    for item in self._experiments.values()
                    if item.run_id == run.id and item.state == "completed"
                ),
                key=lambda item: item.ordinal,
            )
            if not completed:
                return None, [], "NO_COMPLETED_CANDIDATES"
            runtime = self._runtime_descriptor(run)
            runtime_split = _runtime_split(runtime)
            benchmark_result = backtest_buy_and_hold(
                runtime_split.training_bars,
                BASELINE_EXECUTION,
                cadence=runtime.cadence,
            )
            benchmark = self._metrics_projection(benchmark_result.metrics)
            rows = [
                {
                    "candidate_id": item.id,
                    "name": item.name,
                    **item.metrics,
                    "drawdown_improvement_pct": round(
                        item.metrics["maximum_drawdown_pct"] - benchmark["maximum_drawdown_pct"],
                        4,
                    ),
                    "return_difference": round(
                        item.metrics["total_return_pct"] - benchmark["total_return_pct"], 4
                    ),
                    "drawdown_difference": round(
                        item.metrics["maximum_drawdown_pct"] - benchmark["maximum_drawdown_pct"], 4
                    ),
                    "sharpe_difference": round(
                        item.metrics["sharpe_ratio"] - benchmark["sharpe_ratio"], 4
                    ),
                    "trade_count_difference": item.metrics["trade_count"]
                    - benchmark["trade_count"],
                    "walk_forward": self._walk_forward_candidate(
                        runtime_split.training_bars,
                        self._strategy_spec(item.template, item.parameters),
                        BASELINE_EXECUTION,
                        runtime.cadence,
                    ),
                }
                for item in completed
            ]
            ranking = [
                row["candidate_id"]
                for row in sorted(
                    rows,
                    key=lambda row: self._comparison_ranking_key(row, run.selection_objective),
                    reverse=True,
                )
            ]
            comparison = {
                "evaluation_partition": "train",
                "split": runtime_split.metadata,
                "selection_objective": run.selection_objective,
                "benchmark": benchmark,
                "candidates": rows,
                "ranking": ranking,
            }
            artifact = self._new_agent_artifact(
                run,
                QuantArtifactKind.VALIDATION_REPORT,
                "Training candidate comparison",
                comparison,
                key=f"comparison:{canonical_digest([item.id for item in completed])}",
            )
            self._append_event(
                run,
                "comparison.generated",
                {
                    "artifact_id": artifact.id,
                    "safe_summary": (
                        f"{len(completed)} completed candidates were compared with buy and hold "
                        "on the chronological training partition."
                    ),
                },
            )
            self._append_artifact_event(run, artifact)
            feedback_artifact = self._persist_iteration_feedback_if_eligible(
                run=run,
                completed=completed,
                comparison=comparison,
                comparison_artifact_id=artifact.id,
            )
            self._persist_workspace(run.workspace_id)
            return (
                comparison,
                [artifact.id, *([feedback_artifact.id] if feedback_artifact else [])],
                None,
            )

    @staticmethod
    def _comparison_ranking_key(row: dict[str, Any], objective: str) -> tuple[Any, ...]:
        candidate_id = str(row["candidate_id"])
        if objective == "total_return":
            return (
                float(row["total_return_pct"]),
                float(row["sharpe_ratio"]),
                float(row["maximum_drawdown_pct"]),
                candidate_id,
            )
        if objective == "drawdown_control":
            return (
                int(row["trade_count"]) > 0,
                float(row["maximum_drawdown_pct"]),
                float(row["sharpe_ratio"]),
                float(row["total_return_pct"]),
                candidate_id,
            )
        if objective != "risk_adjusted_return":
            raise ValueError("Unsupported Agent selection objective.")
        return (
            float(row["sharpe_ratio"]),
            float(row["total_return_pct"]),
            float(row["maximum_drawdown_pct"]),
            candidate_id,
        )

    @classmethod
    def _validated_training_comparison(
        cls,
        content: dict[str, Any],
        *,
        selection_objective: str,
    ) -> tuple[list[str], list[str]]:
        """Validate one authoritative train-only ranking against its approved objective."""

        comparison_objective = content.get("selection_objective", "risk_adjusted_return")
        if (
            comparison_objective not in SUPPORTED_AGENT_SELECTION_OBJECTIVES
            or comparison_objective != selection_objective
        ):
            raise ValueError(
                "Quant training comparison objective does not match its approved Run plan."
            )
        candidates = content.get("candidates")
        ranking = content.get("ranking")
        if not isinstance(candidates, list) or not isinstance(ranking, list):
            raise ValueError("Quant training comparison ranking is invalid.")
        candidate_rows: list[dict[str, Any]] = []
        candidate_ids: list[str] = []
        for item in candidates:
            if not isinstance(item, dict) or not isinstance(item.get("candidate_id"), str):
                raise ValueError("Quant training comparison candidate identity is invalid.")
            candidate_rows.append(cast(dict[str, Any], item))
            candidate_ids.append(cast(str, item["candidate_id"]))
        ranking_ids: list[str] = []
        for item in ranking:
            if not isinstance(item, str):
                raise ValueError("Quant training comparison ranking identity is invalid.")
            ranking_ids.append(item)
        if (
            len(set(candidate_ids)) != len(candidate_ids)
            or len(set(ranking_ids)) != len(ranking_ids)
            or set(ranking_ids) != set(candidate_ids)
        ):
            raise ValueError("Quant training comparison candidates and ranking do not match.")
        try:
            expected_ranking = [
                str(row["candidate_id"])
                for row in sorted(
                    candidate_rows,
                    key=lambda row: cls._comparison_ranking_key(row, selection_objective),
                    reverse=True,
                )
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Quant training comparison metrics are invalid.") from exc
        if ranking_ids != expected_ranking:
            raise ValueError(
                "Quant training comparison ranking does not follow its approved objective."
            )
        return candidate_ids, ranking_ids

    @staticmethod
    def canonical_candidate_key(template: str, parameters: dict[str, Any]) -> str:
        """Stable identity for exact template/parameter de-duplication."""

        return canonical_digest({"template": template, "parameters": _json_value(parameters)})

    @staticmethod
    def _repair_memory_digest_payload(memory: QuantRepairMemory) -> dict[str, Any]:
        return memory.model_dump(mode="json", exclude={"context_digest"})

    @classmethod
    def _repair_memory_digest(cls, memory: QuantRepairMemory) -> str:
        return canonical_digest(cls._repair_memory_digest_payload(memory))

    @classmethod
    def _validated_repair_memory(
        cls,
        memory: QuantRepairMemory | None,
    ) -> QuantRepairMemory | None:
        if memory is None:
            return None
        if memory.context_digest != cls._repair_memory_digest(memory):
            raise invalid_state("The pinned Quant repair memory digest is invalid.")
        return memory

    @classmethod
    def _compose_repair_memory_pin(
        cls,
        run: QuantRunRecord,
        *,
        runs: dict[str, QuantRunRecord],
        artifacts: dict[str, QuantArtifactRecord],
    ) -> QuantRepairMemory:
        grouped: dict[
            tuple[str, str],
            dict[tuple[str, ...], list[tuple[datetime, QuantLearningTrace]]],
        ] = {}
        for artifact in artifacts.values():
            if (
                artifact.workspace_id != run.workspace_id
                or artifact.kind is not QuantArtifactKind.LEARNING_TRACE
            ):
                continue
            trace = QuantLearningTrace.model_validate(artifact.content)
            source_run = runs.get(str(trace.run_id))
            if (
                trace.outcome != "resolved"
                or source_run is None
                or source_run.workspace_id != run.workspace_id
                or trace.workspace_id != run.workspace_id
                or trace.closed_at >= run.created_at
                or trace.tool != quant_tool_identity(trace.tool.action)
                or any(item.required_change != "remove" for item in trace.violations)
                or any(item.change != "remove" for item in trace.correction_delta)
            ):
                continue
            violation_paths = tuple(sorted(item.path for item in trace.violations))
            delta_paths = tuple(sorted(item.path for item in trace.correction_delta))
            if not violation_paths or violation_paths != delta_paths:
                continue
            key = (trace.tool.action.value, trace.failed_call_fingerprint)
            grouped.setdefault(key, {}).setdefault(violation_paths, []).append(
                (trace.closed_at, trace)
            )

        candidates: list[tuple[datetime, QuantRepairMemoryEntry]] = []
        for signatures in grouped.values():
            if len(signatures) != 1:
                continue
            remove_paths, sources = next(iter(signatures.items()))
            ordered_sources = sorted(
                sources,
                key=lambda item: (item[0], str(item[1].trace_id)),
                reverse=True,
            )
            latest = ordered_sources[0][1]
            candidates.append(
                (
                    ordered_sources[0][0],
                    QuantRepairMemoryEntry(
                        source_trace_ids=[item.trace_id for _, item in ordered_sources[:3]],
                        action=latest.tool.action,
                        failed_call_fingerprint=latest.failed_call_fingerprint,
                        tool=latest.tool,
                        remove_paths=list(remove_paths),
                    ),
                )
            )
        entries = [
            entry
            for _, entry in sorted(
                candidates,
                key=lambda item: (
                    item[0],
                    item[1].action.value,
                    item[1].failed_call_fingerprint,
                ),
                reverse=True,
            )[:8]
        ]
        payload = {"schema_version": "quant-repair-memory-v1", "entries": entries}
        return QuantRepairMemory.model_validate(
            {**payload, "context_digest": canonical_digest(_json_value(payload))}
        )

    def _build_repair_memory_pin(self, run: QuantRunRecord) -> QuantRepairMemory:
        return self._compose_repair_memory_pin(
            run,
            runs=self._runs,
            artifacts=self._artifacts,
        )

    @classmethod
    def _validate_restored_repair_memory(
        cls,
        *,
        run: QuantRunRecord,
        runs: dict[str, QuantRunRecord],
        artifacts: dict[str, QuantArtifactRecord],
    ) -> None:
        memory = cls._validated_repair_memory(run.repair_memory)
        if memory is None:
            return
        if run.retry_of_run_id is not None:
            source = runs.get(run.retry_of_run_id)
            if (
                source is None
                or source.repair_memory is None
                or memory.model_dump(mode="json") != source.repair_memory.model_dump(mode="json")
            ):
                raise ValueError("Persisted Quant Retry repair memory is not an exact clone.")
            return
        expected = cls._compose_repair_memory_pin(
            run,
            runs=runs,
            artifacts=artifacts,
        )
        if memory.model_dump(mode="json") != expected.model_dump(mode="json"):
            raise ValueError("Persisted Quant repair memory does not match eligible prior traces.")

    def repair_memory_for_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
    ) -> QuantRepairMemory | None:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self._runs.get(run_id)
            if run is None or run.workspace_id != workspace_id:
                return None
            memory = self._validated_repair_memory(run.repair_memory)
            return memory.model_copy(deep=True) if memory is not None else None

    @staticmethod
    def _research_memory_digest_payload(
        memory: QuantResearchMemoryContext,
    ) -> dict[str, Any]:
        return memory.model_dump(mode="json", exclude={"context_digest"})

    @classmethod
    def _research_memory_digest(cls, memory: QuantResearchMemoryContext) -> str:
        return canonical_digest(cls._research_memory_digest_payload(memory))

    @classmethod
    def _validated_research_memory_pin(
        cls, memory: QuantResearchMemoryContext | None
    ) -> QuantResearchMemoryContext:
        if memory is None or memory.context_digest != cls._research_memory_digest(memory):
            raise invalid_state("The Run's pinned Research Memory is invalid.")
        return memory

    @classmethod
    def _empty_research_memory(cls) -> QuantResearchMemoryContext:
        payload: dict[str, Any] = {
            "schema_version": "quant-research-memory-v1",
            "source_run_ids": [],
            "sources": [],
            "tested_candidate_keys": [],
            "candidates": [],
            "comparability": "same_evidence",
        }
        return QuantResearchMemoryContext.model_validate(
            {**payload, "context_digest": canonical_digest(payload)}
        )

    @staticmethod
    def _research_memory_dataset_symbol(
        run: QuantRunRecord,
        *,
        daily_records: dict[tuple[str, str], QuantDatasetRecord],
        market_records: dict[tuple[str, str], QuantMarketDatasetV2Record],
    ) -> str:
        market_record = market_records.get((run.workspace_id, run.dataset_id))
        if market_record is not None:
            return market_record.dataset.symbol
        if run.dataset_id == SPY_DAILY_FIXTURE.dataset_id:
            return SPY_DAILY_FIXTURE.symbol
        daily_record = daily_records.get((run.workspace_id, run.dataset_id))
        if daily_record is None:
            raise ValueError("Research Memory references a missing dataset.")
        return daily_record.dataset.symbol

    @classmethod
    def _research_memory_evidence_identity(
        cls,
        run: QuantRunRecord,
        *,
        daily_records: dict[tuple[str, str], QuantDatasetRecord],
        market_records: dict[tuple[str, str], QuantMarketDatasetV2Record],
    ) -> dict[str, Any]:
        symbol = cls._research_memory_dataset_symbol(
            run,
            daily_records=daily_records,
            market_records=market_records,
        )
        interval = run.runtime_interval.value if run.runtime_interval is not None else "1D"
        periods_per_year = run.runtime_periods_per_year or 252
        range_start = (
            run.research_start_utc.isoformat()
            if run.research_start_utc is not None
            else run.research_start.isoformat()
        )
        range_end = (
            run.research_end_utc.isoformat()
            if run.research_end_utc is not None
            else run.research_end.isoformat()
        )
        descriptor_digest = run.runtime_descriptor_digest or canonical_digest(
            {
                "schema_version": "quant-research-memory-runtime-identity-v1",
                "dataset_id": run.dataset_id,
                "dataset_digest": run.dataset_digest,
                "symbol": symbol,
                "interval": interval,
                "periods_per_year": periods_per_year,
                "range_start": range_start,
                "range_end": range_end,
            }
        )
        training_split_digest = run.runtime_split_digest or canonical_digest(
            {
                "schema_version": "quant-research-memory-training-split-v1",
                "rule_version": AGENT_SPLIT_RULE_VERSION,
                "train_percent": AGENT_TRAIN_PERCENT,
                "dataset_id": run.dataset_id,
                "dataset_digest": run.dataset_digest,
                "runtime_descriptor_digest": descriptor_digest,
                "range_start": range_start,
                "range_end": range_end,
            }
        )
        return {
            "dataset_id": run.dataset_id,
            "dataset_digest": run.dataset_digest,
            "symbol": symbol,
            "interval": interval,
            "periods_per_year": periods_per_year,
            "range_start": range_start,
            "range_end": range_end,
            "runtime_descriptor_digest": descriptor_digest,
            "training_split_digest": training_split_digest,
        }

    @staticmethod
    def _research_memory_training_failure(
        candidate: QuantExperimentRecord,
    ) -> str | None:
        metrics = candidate.metrics
        if not metrics:
            return None
        try:
            if int(metrics.get("trade_count", 0)) == 0:
                return "zero_trades"
            if float(metrics["total_return_pct"]) < 0:
                return "negative_training_return"
            if float(metrics["sharpe_ratio"]) <= 0:
                return "non_positive_training_sharpe"
        except (KeyError, TypeError, ValueError):
            return None
        return None

    @staticmethod
    def _research_memory_contract_family(run: QuantRunRecord) -> str:
        if run.runtime_interval is None and run.market_run_contract_version is None:
            return "legacy-daily-v1"
        if run.market_run_contract_version == QUANT_MARKET_RUN_CONTRACT_VERSION:
            return "market-v2-public"
        return "market-v2-private"

    @staticmethod
    def _research_memory_terminal_event_at(
        source: QuantRunRecord,
        *,
        events: dict[str, list[QuantEventRecord]],
    ) -> datetime | None:
        terminal_events = [
            event.occurred_at
            for event in events.get(source.id, [])
            if event.event_type in {"run.completed", "run.failed", "run.cancelled"}
        ]
        return min(terminal_events) if terminal_events else None

    @classmethod
    def _research_memory_source_was_available(
        cls,
        *,
        target: QuantRunRecord,
        source: QuantRunRecord,
        relationship: str,
        events: dict[str, list[QuantEventRecord]],
        terminal_source_override: str | None,
    ) -> bool:
        is_series_parent_override = (
            source.id == terminal_source_override
            and relationship == "ancestor"
            and target.parent_run_id == source.id
            and target.research_loop_policy is not None
            and target.research_series_version == 2
            and source.research_series_version == 1
            and target.research_series_root_run_id == source.research_series_root_run_id
        )
        if source.state not in RESEARCH_MEMORY_TERMINAL_STATES:
            return is_series_parent_override
        terminal_at = cls._research_memory_terminal_event_at(source, events=events)
        if terminal_at is not None:
            return terminal_at <= target.created_at or is_series_parent_override
        if is_series_parent_override:
            return True
        # Only a true pre-P17 record may use the conservative legacy fallback.
        return (
            source.research_memory_contract_version is None
            and source.updated_at <= target.created_at
        )

    @staticmethod
    def _research_memory_ancestor_ids_from_records(
        run: QuantRunRecord,
        *,
        runs: dict[str, QuantRunRecord],
    ) -> list[str]:
        ancestor_ids: list[str] = []
        visited = {run.id}
        parent_id = run.parent_run_id
        while parent_id is not None:
            if parent_id in visited:
                raise ValueError("The Run's refinement lineage contains a cycle.")
            visited.add(parent_id)
            parent = runs.get(parent_id)
            if parent is None or parent.workspace_id != run.workspace_id:
                raise ValueError("The Run's refinement ancestor is unavailable.")
            ancestor_ids.append(parent.id)
            parent_id = parent.parent_run_id
        return ancestor_ids

    def _latest_research_report_artifact(self, run_id: str) -> QuantArtifactRecord | None:
        reports = [
            artifact
            for artifact in self._artifacts.values()
            if artifact.run_id == run_id and artifact.kind is QuantArtifactKind.RESEARCH_REPORT
        ]
        if not reports:
            return None
        return max(reports, key=lambda artifact: artifact.ordinal)

    def _run_consumed_holdout_evidence(self, run: QuantRunRecord) -> bool:
        report_artifact = self._latest_research_report_artifact(run.id)
        if report_artifact is None:
            return False
        generalization = report_artifact.content.get("generalization")
        if not isinstance(generalization, dict):
            return False
        if generalization.get("holdout_evidence_state") == "fresh_sealed":
            return True
        return generalization.get("status") in {"pass", "fail", "inconclusive"} and isinstance(
            generalization.get("holdout"), dict
        )

    def _run_lineage_closure(self, run: QuantRunRecord) -> list[QuantRunRecord]:
        lineage: list[QuantRunRecord] = []
        queue = [run]
        visited = {run.id}
        while queue:
            current = queue.pop(0)
            for source_id in (current.parent_run_id, current.retry_of_run_id):
                if source_id is None or source_id in visited:
                    continue
                source = self._runs.get(source_id)
                if source is None or source.workspace_id != run.workspace_id:
                    continue
                visited.add(source_id)
                lineage.append(source)
                queue.append(source)
        return lineage

    def _holdout_evidence_state(
        self,
        *,
        run: QuantRunRecord,
        runtime: QuantRuntimeDatasetDescriptor,
        runtime_split: QuantRuntimeSplit,
        selected: QuantExperimentRecord | None,
    ) -> tuple[HoldoutEvidenceState, str]:
        if selected is None:
            return "not_evaluated", "No completed candidate was selected for holdout evaluation."
        if (
            run.research_loop_policy is not None
            and run.research_series_version == 2
            and run.parent_run_id is not None
        ):
            return (
                "not_evaluated",
                "This automatic follow-up Run remained training-only and did not reopen the "
                "sealed holdout partition.",
            )
        current_holdout_keys = _runtime_holdout_bar_keys(
            runtime.dataset_digest, runtime_split.all_bars[runtime_split.split_index :]
        )
        for ancestor in self._run_lineage_closure(run):
            if not self._run_consumed_holdout_evidence(ancestor):
                continue
            ancestor_runtime = self._runtime_descriptor(ancestor)
            ancestor_split = _runtime_split(ancestor_runtime)
            ancestor_holdout_keys = _runtime_holdout_bar_keys(
                ancestor_runtime.dataset_digest,
                ancestor_split.all_bars[ancestor_split.split_index :],
            )
            if current_holdout_keys & ancestor_holdout_keys:
                return (
                    "development_only",
                    "This Run overlaps holdout bars already consumed in its lineage, so it "
                    "does not retain a fresh sealed holdout evaluation.",
                )
        return "fresh_sealed", ""

    @classmethod
    def _compose_research_memory_pin(
        cls,
        run: QuantRunRecord,
        *,
        runs: dict[str, QuantRunRecord],
        experiments: dict[str, QuantExperimentRecord],
        artifacts: dict[str, QuantArtifactRecord],
        events: dict[str, list[QuantEventRecord]],
        daily_records: dict[tuple[str, str], QuantDatasetRecord],
        market_records: dict[tuple[str, str], QuantMarketDatasetV2Record],
        terminal_source_override: str | None = None,
    ) -> QuantResearchMemoryContext:
        """Build the complete bounded pin available at the target's creation time."""

        target_identity = cls._research_memory_evidence_identity(
            run,
            daily_records=daily_records,
            market_records=market_records,
        )
        ancestor_ids = cls._research_memory_ancestor_ids_from_records(run, runs=runs)
        source_candidates: list[tuple[QuantRunRecord, str]] = []
        for source_id in ancestor_ids:
            source = runs[source_id]
            source_candidates.append((source, "ancestor"))
        ancestor_set = set(ancestor_ids)
        history = sorted(
            (
                source
                for source in runs.values()
                if source.workspace_id == run.workspace_id
                and source.id != run.id
                and source.id not in ancestor_set
                and source.created_at <= run.created_at
            ),
            key=lambda item: (item.created_at, item.id),
            reverse=True,
        )
        source_candidates.extend((source, "workspace_history") for source in history)

        sources: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        tested_keys: set[str] = set()
        for source, relationship in source_candidates:
            if len(sources) >= RESEARCH_MEMORY_MAX_SOURCE_RUNS:
                break
            if cls._research_memory_contract_family(source) != (
                cls._research_memory_contract_family(run)
            ):
                continue
            if not cls._research_memory_source_was_available(
                target=run,
                source=source,
                relationship=relationship,
                events=events,
                terminal_source_override=terminal_source_override,
            ):
                continue
            source_identity = cls._research_memory_evidence_identity(
                source,
                daily_records=daily_records,
                market_records=market_records,
            )
            if source_identity != target_identity:
                continue
            ranking: list[str] = []
            for artifact in sorted(
                artifacts.values(),
                key=lambda item: (item.ordinal, item.id),
                reverse=True,
            ):
                if (
                    artifact.run_id != source.id
                    or artifact.kind is not QuantArtifactKind.VALIDATION_REPORT
                    or artifact.content.get("evaluation_partition") != "train"
                ):
                    continue
                _, ranking = cls._validated_training_comparison(
                    artifact.content,
                    selection_objective=source.selection_objective,
                )
                break
            rank_by_id = {
                candidate_id: index for index, candidate_id in enumerate(ranking, start=1)
            }
            source_memory_candidates: list[dict[str, Any]] = []
            for candidate in sorted(
                (
                    item
                    for item in experiments.values()
                    if item.run_id == source.id
                    and item.state == "completed"
                    and item.template != "fixture"
                ),
                key=lambda item: (item.ordinal, item.id),
            ):
                if len(candidates) + len(source_memory_candidates) >= (
                    RESEARCH_MEMORY_MAX_CANDIDATE_KEYS
                ):
                    break
                if candidate.template not in SUPPORTED_AGENT_CANDIDATE_FAMILIES:
                    continue
                expected_key = cls.canonical_candidate_key(candidate.template, candidate.parameters)
                if candidate.candidate_key != expected_key:
                    raise ValueError("A prior candidate's canonical identity is invalid.")
                if expected_key in tested_keys:
                    continue
                tested_keys.add(expected_key)
                source_memory_candidates.append(
                    {
                        "source_run_id": source.id,
                        "candidate_key": expected_key,
                        "template": candidate.template,
                        "parameters": _json_value(candidate.parameters),
                        "training_rank": rank_by_id.get(candidate.id),
                        "training_failure_category": (
                            cls._research_memory_training_failure(candidate)
                        ),
                    }
                )
            if not source_memory_candidates:
                continue
            sources.append(
                {
                    "run_id": source.id,
                    "relationship": relationship,
                    "attempt_number": source.attempt_number,
                    "retry_of_run_id": source.retry_of_run_id,
                    **source_identity,
                    "selection_objective": source.selection_objective,
                    "comparability": "same_evidence",
                    "limitations": [
                        "duplicate_avoidance_only",
                        "prior_training_context_only",
                    ],
                }
            )
            candidates.extend(source_memory_candidates)

        payload = {
            "schema_version": "quant-research-memory-v1",
            "source_run_ids": [source["run_id"] for source in sources],
            "sources": sources,
            "tested_candidate_keys": [candidate["candidate_key"] for candidate in candidates],
            "candidates": candidates,
            "comparability": "same_evidence",
        }
        return QuantResearchMemoryContext.model_validate(
            {**payload, "context_digest": canonical_digest(payload)}
        )

    def _build_research_memory_pin(
        self,
        run: QuantRunRecord,
        *,
        terminal_source_override: str | None = None,
    ) -> QuantResearchMemoryContext:
        """Select a stable same-evidence memory once, before a Run starts."""

        try:
            return self._compose_research_memory_pin(
                run,
                runs=self._runs,
                experiments=self._experiments,
                artifacts=self._artifacts,
                events=self._events,
                daily_records=self._datasets,
                market_records=self._market_datasets_v2,
                terminal_source_override=terminal_source_override,
            )
        except ValueError as exc:
            raise invalid_state(str(exc)) from exc

    @classmethod
    def _validate_restored_research_memory(
        cls,
        *,
        run: QuantRunRecord,
        memory: QuantResearchMemoryContext,
        runs: dict[str, QuantRunRecord],
        experiments: dict[str, QuantExperimentRecord],
        artifacts: dict[str, QuantArtifactRecord],
        events: dict[str, list[QuantEventRecord]],
        daily_records: dict[tuple[str, str], QuantDatasetRecord],
        market_records: dict[tuple[str, str], QuantMarketDatasetV2Record],
    ) -> None:
        if memory.context_digest != cls._research_memory_digest(memory):
            raise ValueError("Persisted Quant Research Memory digest does not match its content.")
        if run.research_memory_contract_version is None:
            if memory != cls._empty_research_memory():
                raise ValueError("Persisted legacy Quant Run has unexpected Research Memory.")
            return
        if run.research_memory_contract_version != RESEARCH_MEMORY_CONTRACT_VERSION:
            raise ValueError("Persisted Quant Research Memory contract is unsupported.")
        if run.retry_of_run_id is not None:
            retry_source = runs.get(run.retry_of_run_id)
            if (
                retry_source is None
                or retry_source.workspace_id != run.workspace_id
                or retry_source.research_memory is None
                or memory.model_dump(mode="json")
                != retry_source.research_memory.model_dump(mode="json")
            ):
                raise ValueError(
                    "Persisted Quant Retry must retain its source Research Memory pin."
                )
            return
        terminal_override = (
            run.parent_run_id
            if run.research_loop_policy is not None and run.research_series_version == 2
            else None
        )
        expected = cls._compose_research_memory_pin(
            run,
            runs=runs,
            experiments=experiments,
            artifacts=artifacts,
            events=events,
            daily_records=daily_records,
            market_records=market_records,
            terminal_source_override=terminal_override,
        )
        if memory.model_dump(mode="json") != expected.model_dump(mode="json"):
            raise ValueError(
                "Persisted Quant Research Memory is not the complete canonical creation-time pin."
            )

    def _validate_iteration_feedback_artifact(
        self,
        *,
        run: QuantRunRecord,
        artifact: QuantArtifactRecord,
        experiments: dict[str, QuantExperimentRecord],
        artifacts: dict[str, QuantArtifactRecord],
    ) -> QuantIterationFeedback:
        if (
            artifact.workspace_id != run.workspace_id
            or artifact.run_id != run.id
            or artifact.kind is not QuantArtifactKind.ITERATION_FEEDBACK
        ):
            raise ValueError("Quant iteration feedback must belong to the same workspace and Run.")
        feedback = QuantIterationFeedback.model_validate(artifact.content)
        comparison = artifacts.get(str(feedback.comparison_artifact_id))
        if (
            comparison is None
            or comparison.workspace_id != run.workspace_id
            or comparison.run_id != run.id
            or comparison.kind is not QuantArtifactKind.VALIDATION_REPORT
            or comparison.content.get("evaluation_partition") != "train"
        ):
            raise ValueError(
                "Quant iteration feedback must reference its run-scoped training comparison."
            )
        comparison_rows = comparison.content.get("candidates")
        if not isinstance(comparison_rows, list):
            raise ValueError("Quant iteration feedback comparison candidates are invalid.")
        _, comparison_ranking = self._validated_training_comparison(
            comparison.content,
            selection_objective=run.selection_objective,
        )
        rows_by_id = {
            str(item["candidate_id"]): item
            for item in comparison_rows
            if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
        }
        split = comparison.content.get("split")
        if not isinstance(split, dict):
            raise ValueError("Quant iteration feedback training split is invalid.")
        expected_training_split = {
            "rule_version": split.get("rule_version"),
            "train_bar_count": split.get("train_bar_count"),
            "train_start": split.get("train_start"),
            "train_end": split.get("train_end"),
        }
        if (
            feedback.benchmark.model_dump(mode="json")
            != _json_value(comparison.content.get("benchmark"))
            or feedback.training_split.model_dump(mode="json") != expected_training_split
        ):
            raise ValueError(
                "Quant iteration feedback evidence does not match its training comparison."
            )
        source_ids: list[str] = []
        source_keys: list[str] = []
        for item in feedback.completed_candidates:
            candidate = experiments.get(str(item.candidate_id))
            expected_key = self.canonical_candidate_key(item.template, item.parameters)
            comparison_row = rows_by_id.get(str(item.candidate_id))
            if (
                candidate is None
                or candidate.workspace_id != run.workspace_id
                or candidate.run_id != run.id
                or candidate.state != "completed"
                or candidate.template == "fixture"
                or candidate.feedback_artifact_id is not None
                or candidate.template != item.template
                or _json_value(candidate.parameters) != _json_value(item.parameters)
                or candidate.candidate_key != expected_key
                or item.canonical_key != expected_key
                or item.name != candidate.name
                or comparison_row is None
            ):
                raise ValueError(
                    "Quant iteration feedback candidate identity does not match its source Run."
                )
            walk_forward = comparison_row.get("walk_forward")
            if not isinstance(walk_forward, dict):
                raise ValueError("Quant iteration feedback walk-forward evidence is invalid.")
            aggregate = walk_forward.get("aggregate")
            if not isinstance(aggregate, dict):
                raise ValueError("Quant iteration feedback walk-forward aggregate is invalid.")
            expected_deltas = {
                "return_difference": comparison_row.get("return_difference"),
                "drawdown_difference": comparison_row.get("drawdown_difference"),
                "sharpe_difference": comparison_row.get("sharpe_difference"),
                "trade_count_difference": comparison_row.get("trade_count_difference"),
            }
            expected_walk_forward = {
                "status": walk_forward.get("status"),
                "evaluated_folds": aggregate.get("evaluated_folds"),
                "candidate_positive_return_folds": aggregate.get("candidate_positive_return_folds"),
                "candidate_lower_drawdown_folds": aggregate.get("candidate_lower_drawdown_folds"),
                "candidate_median_return_pct": aggregate.get("candidate_median_return_pct"),
                "benchmark_median_return_pct": aggregate.get("benchmark_median_return_pct"),
                "candidate_median_drawdown_pct": aggregate.get("candidate_median_drawdown_pct"),
                "benchmark_median_drawdown_pct": aggregate.get("benchmark_median_drawdown_pct"),
                "candidate_median_sharpe_ratio": aggregate.get("candidate_median_sharpe_ratio"),
                "benchmark_median_sharpe_ratio": aggregate.get("benchmark_median_sharpe_ratio"),
                "distinct_market_regimes": aggregate.get("distinct_market_regimes"),
                "regime_diversity_status": aggregate.get("regime_diversity_status"),
            }
            if (
                item.metrics.model_dump(mode="json") != _json_value(candidate.metrics)
                or item.deltas.model_dump(mode="json") != expected_deltas
                or item.walk_forward.model_dump(mode="json") != expected_walk_forward
            ):
                raise ValueError(
                    "Quant iteration feedback candidate evidence does not match its source."
                )
            source_ids.append(candidate.id)
            source_keys.append(expected_key)
        comparison_ids = list(rows_by_id)
        if set(comparison_ids) != set(source_ids):
            raise ValueError(
                "Quant iteration feedback candidates must match its training comparison."
            )
        if feedback.novelty.tested_candidate_keys != source_keys:
            raise ValueError(
                "Quant iteration feedback novelty keys must match its source candidates."
            )
        reference = experiments.get(str(feedback.improvement_reference.candidate_id))
        if (
            reference is None
            or reference.id not in source_ids
            or reference.candidate_key != feedback.improvement_reference.canonical_key
        ):
            raise ValueError(
                "Quant iteration feedback improvement reference must name a source candidate."
            )
        feedback_selection_rule = feedback.improvement_reference.selection_rule
        normalized_selection_rule = (
            "risk_adjusted_return"
            if feedback_selection_rule == "highest_sharpe_then_return_then_drawdown"
            else feedback_selection_rule
        )
        if normalized_selection_rule != run.selection_objective:
            raise ValueError(
                "Quant iteration feedback objective does not match its approved Run plan."
            )
        expected_reference_id = next(
            (candidate_id for candidate_id in comparison_ranking if candidate_id in source_ids),
            None,
        )
        if feedback.improvement_reference.candidate_id != expected_reference_id:
            raise ValueError("Quant iteration feedback improvement reference is not deterministic.")
        if any(
            candidate.feedback_artifact_id == artifact.id and candidate.id in source_ids
            for candidate in experiments.values()
        ):
            raise ValueError(
                "Quant iteration feedback cannot be the lineage source of its own comparison set."
            )
        return feedback

    def _validate_replan_evidence_binding(
        self,
        *,
        run: QuantRunRecord,
        decision: QuantEvidenceReplanDecision,
        feedback_artifact: QuantArtifactRecord,
        experiments: dict[str, QuantExperimentRecord],
        artifacts: dict[str, QuantArtifactRecord],
    ) -> tuple[QuantIterationFeedback, QuantExperimentRecord]:
        try:
            feedback = self._validate_iteration_feedback_artifact(
                run=run,
                artifact=feedback_artifact,
                experiments=experiments,
                artifacts=artifacts,
            )
        except ValueError as exc:
            raise ValueError("ITERATION_REPLAN_FEEDBACK_INVALID") from exc
        if decision.source_comparison_artifact_id != feedback.comparison_artifact_id:
            raise ValueError("ITERATION_REPLAN_COMPARISON_MISMATCH")
        if (
            decision.improvement_reference_candidate_id
            != feedback.improvement_reference.candidate_id
        ):
            raise ValueError("ITERATION_REPLAN_REFERENCE_MISMATCH")
        reference = experiments.get(str(feedback.improvement_reference.candidate_id))
        if reference is None:
            raise ValueError("ITERATION_REPLAN_REFERENCE_MISMATCH")
        return feedback, reference

    def _validate_candidate_replan_decision(
        self,
        *,
        run: QuantRunRecord,
        candidate_template: str,
        candidate_parameters: dict[str, Any],
        decision: QuantEvidenceReplanDecision,
        feedback_artifact: QuantArtifactRecord,
        experiments: dict[str, QuantExperimentRecord],
        artifacts: dict[str, QuantArtifactRecord],
    ) -> None:
        _, reference = self._validate_replan_evidence_binding(
            run=run,
            decision=decision,
            feedback_artifact=feedback_artifact,
            experiments=experiments,
            artifacts=artifacts,
        )
        if decision.action == "refine_parameters":
            if candidate_template != reference.template:
                raise ValueError("ITERATION_REPLAN_TEMPLATE_RELATION_INVALID")
            if _json_value(candidate_parameters) == _json_value(reference.parameters):
                raise ValueError("ITERATION_REPLAN_PARAMETERS_NOT_MATERIAL")
        elif decision.action == "switch_approved_family":
            if candidate_template == reference.template:
                raise ValueError("ITERATION_REPLAN_TEMPLATE_RELATION_INVALID")
            if candidate_template not in run.planned_candidate_families:
                raise ValueError("CANDIDATE_OUTSIDE_APPROVED_PLAN")
        else:
            raise ValueError("ITERATION_REPLAN_ACTION_INVALID")

    def _real_completed_candidates(self, run: QuantRunRecord) -> list[QuantExperimentRecord]:
        return sorted(
            (
                item
                for item in self._experiments.values()
                if item.run_id == run.id
                and item.state == "completed"
                and item.template != "fixture"
            ),
            key=lambda item: item.ordinal,
        )

    def _iteration_feedback_artifact(self, run: QuantRunRecord) -> QuantArtifactRecord | None:
        return next(
            (
                artifact
                for artifact in sorted(
                    self._artifacts.values(), key=lambda item: item.ordinal, reverse=True
                )
                if artifact.run_id == run.id
                and artifact.kind is QuantArtifactKind.ITERATION_FEEDBACK
            ),
            None,
        )

    def _latest_training_comparison(self, run: QuantRunRecord) -> dict[str, Any] | None:
        for artifact in sorted(
            self._artifacts.values(), key=lambda item: item.ordinal, reverse=True
        ):
            content = artifact.content
            if (
                artifact.run_id != run.id
                or artifact.kind is not QuantArtifactKind.VALIDATION_REPORT
                or content.get("evaluation_partition") != "train"
                or artifact.digest != canonical_digest(content)
            ):
                continue
            try:
                candidate_ids, ranking = self._validated_training_comparison(
                    content,
                    selection_objective=run.selection_objective,
                )
            except ValueError:
                continue
            rows = content.get("candidates")
            if not isinstance(rows, list):
                continue
            evidence: list[dict[str, Any]] = []
            evidence_valid = True
            for candidate_id in candidate_ids:
                row = next(
                    (
                        item
                        for item in rows
                        if isinstance(item, dict) and item.get("candidate_id") == candidate_id
                    ),
                    None,
                )
                walk_forward = row.get("walk_forward") if isinstance(row, dict) else None
                folds = walk_forward.get("folds") if isinstance(walk_forward, dict) else None
                trade_count = row.get("trade_count") if isinstance(row, dict) else None
                if (
                    isinstance(trade_count, bool)
                    or not isinstance(trade_count, int)
                    or trade_count < 0
                    or not isinstance(walk_forward, dict)
                    or walk_forward.get("evaluation_partition") != "train"
                    or not isinstance(folds, list)
                ):
                    evidence_valid = False
                    break
                pass_folds = [
                    fold
                    for fold in folds
                    if isinstance(fold, dict) and fold.get("status") == "pass"
                ]
                labels: list[str] = []
                for fold in pass_folds:
                    regime = fold.get("market_regime")
                    label = regime.get("label") if isinstance(regime, dict) else None
                    if not isinstance(label, str) or not label:
                        evidence_valid = False
                        break
                    if label not in labels:
                        labels.append(label)
                if not evidence_valid:
                    break
                evidence.append(
                    {
                        "candidate_id": candidate_id,
                        "trade_count": trade_count,
                        "walk_forward_pass_folds": len(pass_folds),
                        "pass_regime_labels": labels,
                    }
                )
            if not evidence_valid:
                continue
            return {
                "artifact_id": artifact.id,
                "candidate_ids": candidate_ids,
                "ranking": ranking,
                "candidates": evidence,
            }
        return None

    def _validate_research_decision(
        self,
        *,
        run: QuantRunRecord,
        selected: QuantExperimentRecord | None,
        completed: list[QuantExperimentRecord],
        comparison_artifact: QuantArtifactRecord | None,
        decision: QuantResearchDecision | None,
    ) -> str | None:
        """Validate one frozen selection using only the latest training comparison."""

        if selected is None:
            return "UNEXPECTED_RESEARCH_DECISION" if decision is not None else None
        if decision is None:
            return "RESEARCH_DECISION_REQUIRED"
        if (
            decision.selected_candidate_id != selected.id
            or comparison_artifact is None
            or decision.source_comparison_artifact_id != comparison_artifact.id
            or comparison_artifact.workspace_id != run.workspace_id
            or comparison_artifact.run_id != run.id
            or comparison_artifact.kind is not QuantArtifactKind.VALIDATION_REPORT
            or comparison_artifact.content.get("evaluation_partition") != "train"
            or comparison_artifact.digest != canonical_digest(comparison_artifact.content)
        ):
            return "RESEARCH_DECISION_BINDING_MISMATCH"
        try:
            candidate_ids, ranking = self._validated_training_comparison(
                comparison_artifact.content,
                selection_objective=run.selection_objective,
            )
        except ValueError:
            return "RESEARCH_DECISION_COMPARISON_INVALID"
        completed_by_id = {item.id: item for item in completed}
        if (
            set(candidate_ids) != set(completed_by_id)
            or not ranking
            or selected.id not in completed_by_id
        ):
            return "RESEARCH_DECISION_COMPARISON_INVALID"
        rows = comparison_artifact.content.get("candidates")
        if not isinstance(rows, list):
            return "RESEARCH_DECISION_EVIDENCE_INVALID"
        rows_by_id = {
            str(row["candidate_id"]): row
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("candidate_id"), str)
        }
        if set(rows_by_id) != set(completed_by_id) or any(
            not isinstance(row.get("walk_forward"), dict)
            or row["walk_forward"].get("evaluation_partition") != "train"
            for row in rows_by_id.values()
        ):
            return "RESEARCH_DECISION_EVIDENCE_INVALID"
        leader_id = ranking[0]
        if decision.decision_basis == "approved_objective_rank":
            return None if selected.id == leader_id else "RESEARCH_DECISION_RANK_MISMATCH"
        deviation = decision.deviation
        if (
            deviation is None
            or selected.id == leader_id
            or deviation.reference_candidate_id != leader_id
        ):
            return "RESEARCH_DECISION_OVERRIDE_REFERENCE_INVALID"

        def pass_folds(candidate_id: str) -> list[dict[str, Any]]:
            walk_forward = rows_by_id[candidate_id].get("walk_forward")
            if (
                not isinstance(walk_forward, dict)
                or walk_forward.get("evaluation_partition") != "train"
                or not isinstance(walk_forward.get("folds"), list)
            ):
                raise ValueError
            folds = cast(list[Any], walk_forward["folds"])
            if any(not isinstance(fold, dict) for fold in folds):
                raise ValueError
            return [cast(dict[str, Any], fold) for fold in folds if fold.get("status") == "pass"]

        try:
            if deviation.reason == "walk_forward_stability":
                scores = {
                    candidate_id: len(pass_folds(candidate_id)) for candidate_id in completed_by_id
                }
                best_score = max(scores.values())
                valid = (
                    scores[selected.id] > scores[leader_id]
                    and scores[selected.id] == best_score
                    and list(scores.values()).count(best_score) == 1
                )
            elif deviation.reason == "regime_coverage":
                scores: dict[str, int] = {}
                for candidate_id in completed_by_id:
                    labels: set[str] = set()
                    for fold in pass_folds(candidate_id):
                        market_regime = fold.get("market_regime")
                        label = (
                            market_regime.get("label") if isinstance(market_regime, dict) else None
                        )
                        if not isinstance(label, str) or not label:
                            raise ValueError
                        labels.add(label)
                    scores[candidate_id] = len(labels)
                best_score = max(scores.values())
                valid = (
                    scores[selected.id] >= 2
                    and scores[selected.id] > scores[leader_id]
                    and scores[selected.id] == best_score
                    and list(scores.values()).count(best_score) == 1
                )
            elif deviation.reason == "minimum_trade_evidence":
                trade_counts: dict[str, int] = {}
                for candidate_id, row in rows_by_id.items():
                    value = row.get("trade_count")
                    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                        raise ValueError
                    trade_counts[candidate_id] = value
                eligible = [
                    candidate_id for candidate_id in ranking if trade_counts[candidate_id] >= 1
                ]
                valid = (
                    trade_counts[leader_id] == 0 and bool(eligible) and selected.id == eligible[0]
                )
            else:  # pragma: no cover - closed by the Pydantic contract
                valid = False
        except (KeyError, TypeError, ValueError):
            return "RESEARCH_DECISION_EVIDENCE_INVALID"
        return None if valid else "RESEARCH_DECISION_OVERRIDE_UNSUPPORTED"

    def _strict_iteration_finish_error(
        self,
        run: QuantRunRecord,
        completed: list[QuantExperimentRecord],
    ) -> str | None:
        """Enforce the complete successful default 2+1 sequence before holdout."""

        if run.max_experiments != 3:
            return None
        real_completed = sorted(
            (item for item in completed if item.template != "fixture"),
            key=lambda item: item.ordinal,
        )
        base_candidates = [item for item in real_completed if item.feedback_artifact_id is None]
        if len(base_candidates) != 2:
            return "ITERATION_BASE_CANDIDATES_REQUIRED"
        feedback = self._iteration_feedback_artifact(run)
        if feedback is None:
            return "ITERATION_FEEDBACK_REQUIRED"
        try:
            feedback_content = self._validate_iteration_feedback_artifact(
                run=run,
                artifact=feedback,
                experiments=self._experiments,
                artifacts=self._artifacts,
            )
        except ValueError:
            return "ITERATION_FEEDBACK_INVALID"
        if {str(item.candidate_id) for item in feedback_content.completed_candidates} != {
            item.id for item in base_candidates
        }:
            return "ITERATION_FEEDBACK_INVALID"
        if run.used_experiments != run.max_experiments:
            return "ITERATION_CANDIDATE_REQUIRED"
        feedback_candidates = [
            item
            for item in self._experiments.values()
            if item.run_id == run.id and item.feedback_artifact_id == feedback.id
        ]
        if len(feedback_candidates) != 1:
            return "ITERATION_CANDIDATE_REQUIRED"
        exploration = feedback_candidates[0]
        if not exploration.change_rationale or not exploration.change_rationale.strip():
            return "ITERATION_CANDIDATE_RATIONALE_REQUIRED"
        strategy_artifact = self._artifacts.get(
            str(
                _uuid(
                    "agent-artifact",
                    exploration.run_id,
                    QuantArtifactKind.STRATEGY_SPEC,
                    exploration.id,
                )
            )
        )
        artifact_decision_payload = (
            strategy_artifact.content.get("replan_decision")
            if strategy_artifact is not None
            else None
        )
        if (exploration.replan_decision is None) != (artifact_decision_payload is None):
            return "ITERATION_REPLAN_DECISION_INVALID"
        if exploration.replan_decision is not None:
            try:
                artifact_decision = QuantEvidenceReplanDecision.model_validate(
                    artifact_decision_payload
                )
                if artifact_decision != exploration.replan_decision:
                    return "ITERATION_REPLAN_DECISION_INVALID"
                self._validate_candidate_replan_decision(
                    run=run,
                    candidate_template=exploration.template,
                    candidate_parameters=exploration.parameters,
                    decision=exploration.replan_decision,
                    feedback_artifact=feedback,
                    experiments=self._experiments,
                    artifacts=self._artifacts,
                )
            except (TypeError, ValueError):
                return "ITERATION_REPLAN_DECISION_INVALID"
        if exploration.state != "completed" or exploration.id not in {
            item.id for item in real_completed
        }:
            return "ITERATION_CANDIDATE_REQUIRED"
        if len(real_completed) != 3 or {item.id for item in real_completed} != {
            *(item.id for item in base_candidates),
            exploration.id,
        }:
            return "ITERATION_CANDIDATE_REQUIRED"
        canonical_keys: list[str] = []
        for candidate in real_completed:
            expected_key = self.canonical_candidate_key(candidate.template, candidate.parameters)
            if candidate.candidate_key != expected_key:
                return "ITERATION_CANDIDATE_CANONICAL_IDENTITY_INVALID"
            canonical_keys.append(expected_key)
        if len(set(canonical_keys)) != 3:
            return "ITERATION_CANDIDATE_NOT_NOVEL"
        return None

    def _stop_replan_finish_error(
        self,
        *,
        run: QuantRunRecord,
        completed: list[QuantExperimentRecord],
        decision: QuantEvidenceReplanDecision,
        experiments: dict[str, QuantExperimentRecord] | None = None,
        artifacts: dict[str, QuantArtifactRecord] | None = None,
    ) -> str | None:
        experiment_records = experiments or self._experiments
        artifact_records = artifacts or self._artifacts
        feedback_artifact = next(
            (
                artifact
                for artifact in sorted(
                    artifact_records.values(), key=lambda item: item.ordinal, reverse=True
                )
                if artifact.run_id == run.id
                and artifact.kind is QuantArtifactKind.ITERATION_FEEDBACK
            ),
            None,
        )
        if feedback_artifact is None:
            return "ITERATION_FEEDBACK_REQUIRED"
        if decision.action not in {
            "stop_no_novel_candidate",
            "stop_insufficient_budget",
        }:
            return "ITERATION_STOP_REPLAN_ACTION_INVALID"
        try:
            feedback, _ = self._validate_replan_evidence_binding(
                run=run,
                decision=decision,
                feedback_artifact=feedback_artifact,
                experiments=experiment_records,
                artifacts=artifact_records,
            )
        except ValueError as exc:
            return str(exc)
        real_completed = [
            item for item in completed if item.template != "fixture" and item.state == "completed"
        ]
        if len(completed) != 2 or len(real_completed) != 2:
            return "ITERATION_STOP_REQUIRES_A_B_ONLY"
        if {item.id for item in real_completed} != {
            str(item.candidate_id) for item in feedback.completed_candidates
        }:
            return "ITERATION_STOP_REQUIRES_A_B_ONLY"
        if any(
            item.run_id == run.id and item.feedback_artifact_id == feedback_artifact.id
            for item in experiment_records.values()
        ):
            return "ITERATION_STOP_REQUIRES_A_B_ONLY"
        if decision.action == "stop_insufficient_budget":
            if run.max_agent_iterations - run.agent_iteration >= 4:
                return "ITERATION_STOP_BUDGET_STILL_SUFFICIENT"
            return None
        assert decision.proposed_template is not None
        assert decision.proposed_parameters is not None
        if decision.proposed_template not in run.planned_candidate_families:
            return "ITERATION_STOP_PROPOSAL_OUTSIDE_APPROVED_PLAN"
        try:
            self._strategy_spec(decision.proposed_template, decision.proposed_parameters)
        except (KeyError, OverflowError, TypeError, ValueError):
            return "ITERATION_STOP_PROPOSAL_INVALID"
        proposed_key = self.canonical_candidate_key(
            decision.proposed_template, decision.proposed_parameters
        )
        memory = self._validated_research_memory_pin(run.research_memory)
        tested_keys = set(memory.tested_candidate_keys)
        tested_keys.update(
            item.candidate_key for item in real_completed if item.candidate_key is not None
        )
        if proposed_key not in tested_keys:
            return "ITERATION_STOP_PROPOSAL_IS_NOVEL"
        return None

    def _persist_iteration_feedback_if_eligible(
        self,
        *,
        run: QuantRunRecord,
        completed: list[QuantExperimentRecord],
        comparison: dict[str, Any],
        comparison_artifact_id: str,
    ) -> QuantArtifactRecord | None:
        real_completed = [item for item in completed if item.template != "fixture"]
        if (
            len(real_completed) < 2
            or run.used_experiments >= run.max_experiments
            or any(
                artifact.run_id == run.id and artifact.kind is QuantArtifactKind.ITERATION_FEEDBACK
                for artifact in self._artifacts.values()
            )
        ):
            return None
        rows = {
            str(item["candidate_id"]): item
            for item in comparison["candidates"]
            if isinstance(item, dict) and isinstance(item.get("candidate_id"), str)
        }
        feedback_candidates: list[dict[str, Any]] = []
        for candidate in real_completed:
            row = rows.get(candidate.id)
            if row is None or not candidate.metrics:
                return None
            aggregate = row["walk_forward"].get("aggregate", {})
            feedback_candidates.append(
                {
                    "candidate_id": candidate.id,
                    "name": candidate.name,
                    "template": candidate.template,
                    "parameters": candidate.parameters,
                    "canonical_key": candidate.candidate_key
                    or self.canonical_candidate_key(candidate.template, candidate.parameters),
                    "metrics": candidate.metrics,
                    "deltas": {
                        "return_difference": row["return_difference"],
                        "drawdown_difference": row["drawdown_difference"],
                        "sharpe_difference": row["sharpe_difference"],
                        "trade_count_difference": row["trade_count_difference"],
                    },
                    "walk_forward": {
                        "status": row["walk_forward"]["status"],
                        "evaluated_folds": aggregate["evaluated_folds"],
                        "candidate_positive_return_folds": aggregate.get(
                            "candidate_positive_return_folds"
                        ),
                        "candidate_lower_drawdown_folds": aggregate.get(
                            "candidate_lower_drawdown_folds"
                        ),
                        "candidate_median_return_pct": aggregate.get("candidate_median_return_pct"),
                        "benchmark_median_return_pct": aggregate.get("benchmark_median_return_pct"),
                        "candidate_median_drawdown_pct": aggregate.get(
                            "candidate_median_drawdown_pct"
                        ),
                        "benchmark_median_drawdown_pct": aggregate.get(
                            "benchmark_median_drawdown_pct"
                        ),
                        "candidate_median_sharpe_ratio": aggregate.get(
                            "candidate_median_sharpe_ratio"
                        ),
                        "benchmark_median_sharpe_ratio": aggregate.get(
                            "benchmark_median_sharpe_ratio"
                        ),
                        "distinct_market_regimes": aggregate.get("distinct_market_regimes"),
                        "regime_diversity_status": aggregate.get("regime_diversity_status"),
                    },
                }
            )
        feedback_by_id = {item["candidate_id"]: item for item in feedback_candidates}
        reference = next(
            (
                feedback_by_id[candidate_id]
                for candidate_id in comparison["ranking"]
                if candidate_id in feedback_by_id
            ),
            None,
        )
        if reference is None:
            return None
        split = comparison["split"]
        remaining_iterations = max(0, run.max_agent_iterations - run.agent_iteration)
        payload = QuantIterationFeedback.model_validate(
            {
                "schema_version": "quant-iteration-feedback-v1",
                "round": 1,
                "comparison_artifact_id": comparison_artifact_id,
                "evaluation_partition": "train",
                "training_split": {
                    "rule_version": split["rule_version"],
                    "train_bar_count": split["train_bar_count"],
                    "train_start": split["train_start"],
                    "train_end": split["train_end"],
                },
                "benchmark": comparison["benchmark"],
                "completed_candidates": feedback_candidates,
                "remaining_budget": {
                    "experiments": run.max_experiments - run.used_experiments,
                    "iterations": remaining_iterations,
                },
                "novelty": {
                    "exact_dedupe_rule": "template_parameters_canonical_v1",
                    "tested_candidate_keys": [
                        item["canonical_key"] for item in feedback_candidates
                    ],
                },
                "improvement_reference": {
                    "candidate_id": reference["candidate_id"],
                    "canonical_key": reference["canonical_key"],
                    "selection_rule": run.selection_objective,
                },
                "stop_signal": {
                    "code": (
                        "continue_train_only_iteration"
                        if remaining_iterations > 0
                        else "iteration_budget_exhausted"
                    ),
                    "reason": (
                        "A bounded experiment slot remains after the training comparison."
                        if remaining_iterations > 0
                        else "The iteration budget is exhausted; do not create another candidate."
                    ),
                },
            }
        )
        return self._new_agent_artifact(
            run,
            QuantArtifactKind.ITERATION_FEEDBACK,
            "Train-only iteration feedback",
            payload.model_dump(mode="json"),
            key="round:1",
        )

    def _validate_research_series_decision(
        self,
        *,
        run: QuantRunRecord,
        selected: QuantExperimentRecord | None,
        comparison: dict[str, Any] | None,
        decision: QuantResearchSeriesDecision | None,
    ) -> str | None:
        policy = run.research_loop_policy
        if policy is None:
            return "UNEXPECTED_RESEARCH_SERIES_DECISION" if decision is not None else None
        if decision is None:
            return "RESEARCH_SERIES_DECISION_REQUIRED"
        if comparison is None or decision.source_comparison_artifact_id != comparison.get(
            "artifact_id"
        ):
            return "RESEARCH_SERIES_COMPARISON_MISMATCH"
        context = self._research_series_context(run)
        if context is None:  # pragma: no cover - policy presence is checked above
            return "RESEARCH_SERIES_CONTEXT_INVALID"
        may_refine = "precommit_one_refinement" in context.allowed_actions
        if decision.action == "refine_selected":
            if not may_refine:
                return "RESEARCH_SERIES_BUDGET_EXHAUSTED"
            if selected is None or decision.seed_candidate_id != selected.id:
                return "RESEARCH_SERIES_SEED_MISMATCH"
            if selected.candidate_key is None:
                return "RESEARCH_SERIES_SEED_INVALID"
        return None

    def _precommit_research_series_child(
        self,
        *,
        run: QuantRunRecord,
        selected: QuantExperimentRecord,
        decision: QuantResearchSeriesDecision,
    ) -> QuantRunRecord:
        if decision.action != "refine_selected":
            raise invalid_state("Only a refinement decision can create a follow-up Run.")
        if run.research_series_root_run_id is None or run.research_loop_policy is None:
            raise invalid_state("The research series identity is incomplete.")
        root = self.get_run(workspace_id=run.workspace_id, run_id=run.research_series_root_run_id)
        if root.research_series_child_run_id is not None:
            return self.get_run(
                workspace_id=run.workspace_id,
                run_id=root.research_series_child_run_id,
            )
        descriptor = self._runtime_descriptor(run)
        split = _runtime_split(descriptor)
        project = self.get_project(workspace_id=run.workspace_id, project_id=run.project_id)
        child_id = str(
            _uuid(
                "research-series-follow-up-v1",
                root.id,
                run.id,
                decision.source_comparison_artifact_id,
                canonical_digest(run.research_loop_policy.model_dump(mode="json")),
            )
        )
        child = QuantRunRecord(
            id=child_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            question=run.question,
            mode=QuantRunMode.AUTO,
            dataset_id=run.dataset_id,
            dataset_digest=run.dataset_digest,
            research_start=run.research_start,
            research_end=run.research_end,
            research_start_utc=run.research_start_utc,
            research_end_utc=run.research_end_utc,
            runtime_interval=run.runtime_interval,
            runtime_periods_per_year=run.runtime_periods_per_year,
            runtime_descriptor_digest=descriptor.descriptor_digest,
            runtime_split_digest=split.seal_digest,
            market_run_contract_version=QUANT_MARKET_RUN_CONTRACT_VERSION,
            parent_run_id=run.id,
            seed_candidate_id=selected.id,
            refinement_reason=decision.refinement_reason,
            research_loop_policy=run.research_loop_policy,
            research_series_root_run_id=root.id,
            research_series_version=2,
            research_memory_contract_version=RESEARCH_MEMORY_CONTRACT_VERSION,
            trace_id=str(_uuid("trace", child_id, 1)),
            provider=run.provider,
            model=run.model,
            max_agent_iterations=12,
            max_experiments=3,
            max_repairs=run.max_repairs,
            strategy_scope=run.strategy_scope.model_copy(deep=True),
            planned_candidate_families=list(run.planned_candidate_families),
            selection_objective=run.selection_objective,
            completion_criteria=list(run.completion_criteria),
            data_authenticity=run.data_authenticity,
        )
        self._runs[child.id] = child
        root.research_series_child_run_id = child.id
        root.row_version += 1
        root.updated_at = _utcnow()
        project.latest_run_id = child.id
        project.row_version += 1
        project.updated_at = _utcnow()
        self._append_event(
            child,
            "run.queued",
            {
                "state": QuantRunState.QUEUED,
                "attempt_number": child.attempt_number,
                "safe_summary": "The precommitted research refinement was queued.",
            },
        )
        self._publish_plan(child)
        child.research_memory = self._build_research_memory_pin(
            child,
            terminal_source_override=run.id,
        )
        child.repair_memory = self._build_repair_memory_pin(child)
        self._cross_pin_research_memory_to_plan(child)
        if child.strategy_scope.status == "supported":
            self._start_run(
                child,
                "The train-only series decision precommitted one bounded refinement.",
            )
        return child

    def finish_agent_research(
        self,
        lease: QuantFixtureLease,
        *,
        selected_candidate_id: str | None,
        conclusion: str,
        next_step: str,
        series_decision: QuantResearchSeriesDecision | None = None,
        replan_decision: QuantEvidenceReplanDecision | None = None,
        research_decision: QuantResearchDecision | None = None,
    ) -> tuple[dict[str, Any] | None, list[str], str | None]:
        """Finish atomically even when post-decision evaluation raises."""

        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            baseline = self._workspace_mutation_baseline(lease.workspace_id)
            try:
                return self._finish_agent_research_mutating(
                    lease,
                    selected_candidate_id=selected_candidate_id,
                    conclusion=conclusion,
                    next_step=next_step,
                    series_decision=series_decision,
                    replan_decision=replan_decision,
                    research_decision=research_decision,
                )
            except Exception:
                durable = self._durable_workspace_truth(lease.workspace_id)
                if canonical_digest(durable.state) == canonical_digest(baseline.state):
                    self._restore_mutation_baseline(lease.workspace_id, baseline)
                else:
                    self._restore_workspace_preserving_references(
                        lease.workspace_id,
                        durable.state,
                        baseline,
                        repository_memory_contract_version=(
                            durable.research_memory_contract_version
                            or RESEARCH_MEMORY_CONTRACT_VERSION
                        ),
                        repository_replan_contract_marker=(
                            durable.evidence_replan_contract_marker
                            or LEGACY_EVIDENCE_REPLAN_REPOSITORY_MARKER
                        ),
                        repository_research_decision_contract_marker=(
                            durable.research_decision_contract_marker
                            or LEGACY_RESEARCH_DECISION_REPOSITORY_MARKER
                        ),
                    )
                    self._storage_versions[lease.workspace_id] = durable.storage_version
                    self._loaded_workspaces.add(lease.workspace_id)
                raise

    def _finish_agent_research_mutating(
        self,
        lease: QuantFixtureLease,
        *,
        selected_candidate_id: str | None,
        conclusion: str,
        next_step: str,
        series_decision: QuantResearchSeriesDecision | None = None,
        replan_decision: QuantEvidenceReplanDecision | None = None,
        research_decision: QuantResearchDecision | None = None,
    ) -> tuple[dict[str, Any] | None, list[str], str | None]:
        with self._lock:
            self._ensure_workspace_loaded(lease.workspace_id)
            run = self._runs.get(lease.run_id)
            if not self._agent_claim_is_writable(run, lease):
                return None, [], "STALE_CLAIM"
            assert run is not None
            if (
                replan_decision is not None
                and replan_decision.action
                in {"stop_no_novel_candidate", "stop_insufficient_budget"}
                and series_decision is not None
                and series_decision.action != "stop"
            ):
                return None, [], "ITERATION_STOP_SERIES_DECISION_CONFLICT"
            completed = [
                item
                for item in self._experiments.values()
                if item.run_id == run.id and item.state == "completed"
            ]
            if not completed and run.agent_iteration < run.max_agent_iterations - 1:
                return None, [], "NO_COMPLETED_CANDIDATES"
            if completed and selected_candidate_id is None:
                return None, [], "SELECTION_REQUIRED"
            selected = self._experiments.get(selected_candidate_id or "")
            if selected_candidate_id and (
                selected is None or selected.run_id != run.id or selected.state != "completed"
            ):
                return None, [], "INVALID_SELECTED_CANDIDATE"
            comparison: dict[str, Any] | None = None
            comparison_artifact: QuantArtifactRecord | None = None
            if completed:
                is_structured_stop = bool(
                    replan_decision is not None
                    and replan_decision.action
                    in {"stop_no_novel_candidate", "stop_insufficient_budget"}
                )
                if replan_decision is not None and not is_structured_stop:
                    return None, [], "ITERATION_STOP_REPLAN_ACTION_INVALID"
                iteration_error = (
                    self._stop_replan_finish_error(
                        run=run,
                        completed=completed,
                        decision=replan_decision,
                    )
                    if is_structured_stop and replan_decision is not None
                    else self._strict_iteration_finish_error(run, completed)
                )
                if iteration_error is not None:
                    return None, [], iteration_error
                if is_structured_stop and next_step != "stop":
                    return None, [], "ITERATION_STOP_NEXT_STEP_REQUIRED"
                comparison = self._latest_training_comparison(run)
                completed_ids = {item.id for item in completed}
                comparison_id_list = comparison["candidate_ids"] if comparison else []
                comparison_ids = set(comparison_id_list)
                ranking = comparison["ranking"] if comparison else []
                if (
                    comparison is None
                    or len(comparison_id_list) != len(completed_ids)
                    or comparison_ids != completed_ids
                    or len(ranking) != len(completed_ids)
                    or set(ranking) != completed_ids
                ):
                    return None, [], "FINAL_COMPARISON_REQUIRED"
                latest_candidate_artifact_ordinal = max(
                    (
                        artifact.ordinal
                        for artifact in self._artifacts.values()
                        if artifact.run_id == run.id
                        and artifact.kind
                        in {
                            QuantArtifactKind.STRATEGY_SPEC,
                            QuantArtifactKind.BACKTEST_RESULT,
                        }
                    ),
                    default=0,
                )
                comparison_artifact = self._artifacts.get(comparison["artifact_id"])
                if (
                    comparison_artifact is None
                    or comparison_artifact.ordinal <= latest_candidate_artifact_ordinal
                ):
                    return None, [], "FINAL_COMPARISON_REQUIRED"
                if selected_candidate_id not in comparison_ids:
                    return None, [], "INVALID_FINAL_COMPARISON_SELECTION"
                if research_decision is None and selected_candidate_id != ranking[0]:
                    # Preserve the established P16/P18 rejection for old
                    # callers while P19 additionally requires a typed choice.
                    return None, [], "FINAL_SELECTION_OBJECTIVE_MISMATCH"
                if research_decision is None:
                    research_decision = QuantResearchDecision(
                        selected_candidate_id=ranking[0],
                        source_comparison_artifact_id=str(comparison["artifact_id"]),
                        decision_basis="approved_objective_rank",
                    )
            research_decision_error = self._validate_research_decision(
                run=run,
                selected=selected,
                completed=completed,
                comparison_artifact=comparison_artifact,
                decision=research_decision,
            )
            if research_decision_error is not None:
                return None, [], research_decision_error
            series_error = self._validate_research_series_decision(
                run=run,
                selected=selected,
                comparison=comparison if completed else None,
                decision=series_decision,
            )
            if series_error is not None:
                return None, [], series_error
            baseline = self._workspace_mutation_baseline(run.workspace_id)
            child: QuantRunRecord | None = None
            if series_decision is not None:
                run.research_series_decision = series_decision
                if series_decision.action == "refine_selected":
                    assert selected is not None
                    child = self._precommit_research_series_child(
                        run=run,
                        selected=selected,
                        decision=series_decision,
                    )
            runtime = self._runtime_descriptor(run)
            dataset_record = self._datasets.get((run.workspace_id, runtime.dataset_id))
            market_record = self._market_datasets_v2.get((run.workspace_id, runtime.dataset_id))
            if runtime.dataset_id == SPY_DAILY_FIXTURE.dataset_id:
                source_limitation = "The pinned dataset is synthetic and is not real market data."
            elif market_record is not None:
                source_limitation = (
                    "The pinned market bars were retrieved from the declared provider and "
                    "were not cross-validated against a second source."
                    if market_record.evidence.source_kind
                    is QuantMarketDataProvenance.PROVIDER_FETCH
                    else "The pinned market bars were imported by the workspace and were not "
                    "independently verified against a market data provider."
                )
            elif (
                dataset_record is not None
                and dataset_record.source_metadata.provider_id == "nasdaq_equity"
            ):
                source_limitation = (
                    "The pinned unadjusted bars, Nasdaq listing information, and dividend rows "
                    "retain provider-response digests; dividends were not independently verified "
                    "and split history was unavailable."
                )
            elif (
                dataset_record is not None
                and dataset_record.source_metadata.kind == "provider_fetch"
            ):
                source_limitation = (
                    "The pinned bars were retrieved from the declared provider and retain a "
                    "raw-response digest, but were not cross-validated against a second source."
                )
            else:
                source_limitation = (
                    "The pinned dataset was imported by the workspace and was not independently "
                    "verified against a market data provider."
                )
            runtime_split = _runtime_split(runtime)
            all_bars = runtime_split.all_bars
            training_bars = runtime_split.training_bars
            split_index = runtime_split.split_index
            split = runtime_split.metadata
            robustness_artifact: QuantArtifactRecord | None = None
            if selected is not None:
                assert comparison_artifact is not None
                report_artifact_id = str(
                    _uuid(
                        "agent-artifact",
                        run.id,
                        QuantArtifactKind.RESEARCH_REPORT.value,
                        "agent-report",
                    )
                )
                robustness_artifact = self._new_agent_artifact(
                    run,
                    QuantArtifactKind.ROBUSTNESS_SENSITIVITY,
                    "Training cost and parameter sensitivity",
                    self._robustness_sensitivity_content(
                        run=run,
                        selected=selected,
                        comparison_artifact=comparison_artifact,
                        runtime=runtime,
                        runtime_split=runtime_split,
                        report_artifact_id=report_artifact_id,
                    ),
                    key="robustness-sensitivity-v1",
                )
                self._append_artifact_event(run, robustness_artifact)
            automatic_train_only_follow_up = (
                run.research_loop_policy is not None
                and run.research_series_version == 2
                and run.parent_run_id is not None
            )
            holdout_evidence_state, holdout_reason = self._holdout_evidence_state(
                run=run,
                runtime=runtime,
                runtime_split=runtime_split,
                selected=selected,
            )
            generalization: dict[str, Any] = {
                "status": "not_evaluated",
                "reason": holdout_reason,
                "selected_candidate_id": selected_candidate_id,
                "split": split,
                "holdout_evidence_state": holdout_evidence_state,
            }
            walk_forward: dict[str, Any] | None = None
            if selected is not None:
                execution = BASELINE_EXECUTION
                walk_forward = self._walk_forward_candidate(
                    training_bars,
                    self._strategy_spec(selected.template, selected.parameters),
                    execution,
                    runtime.cadence,
                )
                train_benchmark_result = backtest_buy_and_hold(
                    training_bars, execution, cadence=runtime.cadence
                )
                if holdout_evidence_state == "fresh_sealed":
                    holdout_result = run_backtest(
                        all_bars,
                        self._strategy_spec(selected.template, selected.parameters),
                        execution,
                        measurement_start_index=split_index,
                        cadence=runtime.cadence,
                    )
                    holdout_benchmark_result = backtest_buy_and_hold(
                        all_bars[split_index:], execution, cadence=runtime.cadence
                    )
                    holdout_metrics = self._metrics_projection(holdout_result.metrics)
                    holdout_benchmark = self._metrics_projection(holdout_benchmark_result.metrics)
                    if holdout_result.metrics.exposure == 0:
                        status = "inconclusive"
                        reason = (
                            "The selected strategy had no market exposure in the holdout period."
                        )
                    elif (
                        holdout_result.metrics.max_drawdown
                        > holdout_benchmark_result.metrics.max_drawdown
                        and holdout_result.metrics.total_return > 0
                    ):
                        status = "pass"
                        reason = (
                            "The selected strategy remained profitable and had a smaller maximum "
                            "drawdown than buy and hold on the sealed holdout period."
                        )
                    else:
                        status = "fail"
                        reason = (
                            "The selected strategy did not preserve both positive return and a "
                            "smaller maximum drawdown on the sealed holdout period."
                        )
                    generalization = {
                        "status": status,
                        "reason": reason,
                        "selected_candidate_id": selected.id,
                        "split": split,
                        "holdout_evidence_state": holdout_evidence_state,
                        "train": {
                            "candidate": selected.metrics,
                            "benchmark": self._metrics_projection(train_benchmark_result.metrics),
                        },
                        "holdout": {
                            "candidate": holdout_metrics,
                            "benchmark": holdout_benchmark,
                        },
                    }
                    # A model selects a candidate from training evidence before the
                    # sealed holdout is known. Do not retain a training-only
                    # recommendation once that holdout contradicts it.
                    if status == "fail":
                        next_step = "revise_research"
                    elif status == "inconclusive":
                        next_step = "collect_more_evidence"
                else:
                    generalization = {
                        "status": "not_evaluated",
                        "reason": holdout_reason,
                        "selected_candidate_id": selected.id,
                        "split": split,
                        "holdout_evidence_state": holdout_evidence_state,
                        "train": {
                            "candidate": selected.metrics,
                            "benchmark": self._metrics_projection(train_benchmark_result.metrics),
                        },
                    }
                    next_step = "collect_more_evidence"
            conclusion = user_facing_report_text(
                conclusion,
                fallback=(
                    f"The final training comparison selected {selected.name} for sealed "
                    "holdout evaluation."
                    if selected is not None
                    else "No completed strategy was available for sealed holdout evaluation."
                ),
            )
            if replan_decision is not None and selected is not None:
                conclusion = f"The final A/B training comparison selected {selected.name}. " + (
                    "The remaining action budget could not support creating, backtesting, "
                    "comparing, and finishing another candidate, so no third candidate ran."
                    if replan_decision.action == "stop_insufficient_budget"
                    else (
                        "The bounded replan proposal repeated an already-tested canonical "
                        "strategy, so no third candidate ran."
                    )
                )
            if selected is not None and holdout_evidence_state == "development_only":
                conclusion = (
                    f"The final training comparison selected {selected.name}, but this Run "
                    "overlapped holdout evidence already consumed in its lineage. The retained "
                    "result is development-only and does not establish a new sealed validation "
                    "outcome."
                )
            elif (
                selected is not None
                and holdout_evidence_state == "not_evaluated"
                and automatic_train_only_follow_up
            ):
                conclusion = (
                    f"The final training comparison selected {selected.name}, but this "
                    "automatic follow-up Run remained training-only and did not reopen the "
                    "sealed holdout period."
                )
            holdout_limitation = (
                "The Agent selected and revised candidates using only the chronological "
                "training partition. Holdout metrics were computed after selection."
                if holdout_evidence_state == "fresh_sealed"
                else (
                    "This Run overlapped holdout evidence already consumed in its lineage, so "
                    "the retained result is development-only and requires new evidence before "
                    "another sealed holdout evaluation."
                    if holdout_evidence_state == "development_only"
                    else (
                        "This automatic follow-up Run remained training-only and did not "
                        "reopen the sealed holdout partition."
                        if automatic_train_only_follow_up
                        else "No completed candidate was selected for holdout evaluation."
                    )
                )
            )
            report = {
                "research_goal": run.question,
                "plan_summary": run.plan_summary,
                "dataset": self.agent_dataset_summary(run),
                "benchmark": self.agent_benchmark_summary(run),
                "candidates_tested": [self.agent_candidate_summary(item) for item in completed],
                "selected_candidate_id": selected_candidate_id,
                "conclusion": conclusion,
                "next_step": next_step,
                "generalization": generalization,
                "walk_forward": walk_forward,
                "replan_decision": (
                    replan_decision.model_dump(mode="json") if replan_decision is not None else None
                ),
                "research_decision": (
                    research_decision.model_dump(mode="json")
                    if research_decision is not None
                    else None
                ),
                **(
                    {
                        "robustness_sensitivity": {
                            "artifact_id": robustness_artifact.id,
                            "artifact_digest": robustness_artifact.digest,
                        }
                    }
                    if robustness_artifact is not None
                    else {}
                ),
                "limitations": [
                    source_limitation,
                    holdout_limitation,
                    "Results are local backtests, not investment advice or trading instructions.",
                    "No statistical significance or live execution was evaluated.",
                ],
                "run_metadata": {
                    "run_id": run.id,
                    "provider": run.provider,
                    "model": run.model,
                    "iterations": run.agent_iteration + 1,
                    "precommitted_follow_up_run_id": child.id if child is not None else None,
                },
            }
            artifact = self._new_agent_artifact(
                run,
                QuantArtifactKind.RESEARCH_REPORT,
                "Autonomous Quant Research Report",
                report,
                key="agent-report",
            )
            run.final_conclusion = conclusion
            run.state = QuantRunState.COMPLETED
            run.agent_status = "completed"
            self._append_event(
                run,
                "report.generated",
                {
                    "artifact_id": artifact.id,
                    "safe_summary": "The autonomous research report was generated.",
                },
            )
            self._append_artifact_event(run, artifact)
            self._append_event(
                run,
                "run.completed",
                {
                    "state": QuantRunState.COMPLETED,
                    "plan_revision": run.plan_revision,
                    "attempt_number": run.attempt_number,
                    "safe_summary": "The autonomous research run completed.",
                },
            )
            run.row_version += 1
            run.updated_at = _utcnow()
            self._persist_workspace_or_restore(run.workspace_id, baseline)
            return (
                report,
                [
                    *([robustness_artifact.id] if robustness_artifact is not None else []),
                    artifact.id,
                ],
                None,
            )

    def _new_agent_artifact(
        self,
        run: QuantRunRecord,
        kind: QuantArtifactKind,
        title: str,
        content: dict[str, Any],
        *,
        key: str,
    ) -> QuantArtifactRecord:
        artifact = QuantArtifactRecord(
            id=str(_uuid("agent-artifact", run.id, kind.value, key)),
            workspace_id=run.workspace_id,
            run_id=run.id,
            ordinal=1 + sum(item.run_id == run.id for item in self._artifacts.values()),
            kind=kind,
            title=title,
            digest=canonical_digest(content),
            content=_json_value(content),
            data_authenticity=run.data_authenticity,
        )
        self._artifacts[artifact.id] = artifact
        return artifact

    def _append_artifact_event(self, run: QuantRunRecord, artifact: QuantArtifactRecord) -> None:
        self._append_event(
            run,
            "artifact.published",
            {
                "artifact_id": artifact.id,
                "artifact_kind": artifact.kind,
                "safe_summary": f"Artifact published: {artifact.title}.",
            },
        )

    def _runtime_descriptor(self, run: QuantRunRecord) -> QuantRuntimeDatasetDescriptor:
        market_record = self._market_datasets_v2.get((run.workspace_id, run.dataset_id))
        if market_record is not None:
            if run.research_start_utc is None or run.research_end_utc is None:
                raise invalid_state("A market Run requires complete UTC research bounds.")
            descriptor = _market_runtime_descriptor(
                market_record,
                coverage_start_utc=run.research_start_utc,
                coverage_end_utc=run.research_end_utc,
            )
            split = _runtime_split(descriptor)
            if (
                run.dataset_digest != descriptor.dataset_digest
                or run.research_start_utc != descriptor.coverage_start_utc
                or run.research_end_utc != descriptor.coverage_end_utc
                or run.research_start != descriptor.coverage_start_utc.date()
                or run.research_end != descriptor.coverage_end_utc.date()
                or run.runtime_interval is not descriptor.interval
                or run.runtime_periods_per_year != descriptor.periods_per_year
                or run.runtime_descriptor_digest != descriptor.descriptor_digest
                or run.runtime_split_digest != split.seal_digest
                or run.data_authenticity is not descriptor.data_authenticity
            ):
                raise invalid_state(
                    "The run's pinned market runtime descriptor no longer matches storage."
                )
            return descriptor

        runtime_pin_values = (
            run.research_start_utc,
            run.research_end_utc,
            run.runtime_interval,
            run.runtime_periods_per_year,
            run.runtime_descriptor_digest,
            run.runtime_split_digest,
        )
        if any(value is not None for value in runtime_pin_values):
            raise invalid_state("A daily run cannot contain market runtime pins.")
        dataset = self.dataset_for_run(run)
        record = self._datasets.get((run.workspace_id, run.dataset_id))
        quality_status = _dataset_quality(record).status if record is not None else "passed"
        bars = tuple(
            DailyBar(
                date=bar.trading_date,
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
            )
            for bar in self.bars_for_run(run)
        )
        if len(bars) < MIN_AUTONOMOUS_RESEARCH_BARS:
            raise invalid_state(
                f"Runtime research requires at least {MIN_AUTONOMOUS_RESEARCH_BARS} daily bars."
            )
        coverage_start_utc = datetime.combine(bars[0].date, datetime.min.time(), tzinfo=UTC)
        coverage_end_utc = datetime.combine(bars[-1].date, datetime.min.time(), tzinfo=UTC)
        descriptor_digest = _runtime_descriptor_digest(
            dataset_id=dataset.dataset_id,
            dataset_digest=dataset.digest,
            record_digest=None,
            symbol=dataset.symbol,
            interval=BacktestInterval.DAILY,
            periods_per_year=252,
            coverage_start_utc=coverage_start_utc,
            coverage_end_utc=coverage_end_utc,
            data_authenticity=run.data_authenticity,
            quality_status=quality_status,
            bar_count=len(bars),
        )
        return QuantRuntimeDatasetDescriptor(
            dataset_id=dataset.dataset_id,
            dataset_digest=dataset.digest,
            record_digest=None,
            symbol=dataset.symbol,
            interval=BacktestInterval.DAILY,
            periods_per_year=252,
            coverage_start_utc=coverage_start_utc,
            coverage_end_utc=coverage_end_utc,
            data_authenticity=run.data_authenticity,
            quality_status=quality_status,
            bars=bars,
            cadence=None,
            descriptor_digest=descriptor_digest,
        )

    def runtime_projection(self, run: QuantRunRecord) -> QuantRuntimeProjection:
        """Return one revalidated descriptor/source boundary for context and result views."""

        descriptor = self._runtime_descriptor(run)
        split = _runtime_split(descriptor)
        market_record = self._market_datasets_v2.get((run.workspace_id, run.dataset_id))
        if market_record is not None:
            return QuantRuntimeProjection(
                descriptor=descriptor,
                split=split,
                daily_dataset=None,
                daily_record=None,
                market_record=market_record,
            )
        return QuantRuntimeProjection(
            descriptor=descriptor,
            split=split,
            daily_dataset=self.dataset_for_run(run),
            daily_record=self.get_dataset(workspace_id=run.workspace_id, dataset_id=run.dataset_id),
            market_record=None,
        )

    def _agent_split(
        self, run: QuantRunRecord
    ) -> tuple[tuple[BacktestBar, ...], tuple[BacktestBar, ...], int, dict[str, Any]]:
        split = _runtime_split(self._runtime_descriptor(run))
        return split.all_bars, split.training_bars, split.split_index, split.metadata

    def _walk_forward_candidate(
        self,
        training_bars: tuple[BacktestBar, ...],
        strategy: StrategySpec,
        execution: ExecutionConfig,
        cadence: BacktestCadence | None = None,
    ) -> dict[str, Any]:
        """Evaluate a fixed candidate in repeated, expanding training-only windows.

        The helper deliberately accepts only the chronological training partition.
        Each measurement window starts with fresh cash while earlier bars remain
        available solely for indicator history; the sealed final holdout cannot
        enter this calculation.
        """
        count = len(training_bars)
        window_size = max(20, count // 5)
        initial_train_end = count - AGENT_WALK_FORWARD_FOLDS * window_size
        if initial_train_end < 1:
            return {
                "method": "expanding",
                "rule_version": AGENT_WALK_FORWARD_RULE_VERSION,
                "evaluation_partition": "train",
                "fold_count": 0,
                "window_bar_count": window_size,
                "state_rule_version": AGENT_WALK_FORWARD_STATE_RULE_VERSION,
                "state_lookback_bars": AGENT_WALK_FORWARD_STATE_LOOKBACK_BARS,
                "status": "not_evaluated",
                "reason": "Training partition is too short for three walk-forward windows.",
                "folds": [],
                "aggregate": {
                    "evaluated_folds": 0,
                    "distinct_market_regimes": 0,
                    "regime_diversity_status": "insufficient_regime_diversity",
                    "by_market_regime": [],
                },
            }

        folds: list[dict[str, Any]] = []
        for fold_index in range(AGENT_WALK_FORWARD_FOLDS):
            evaluation_start = initial_train_end + fold_index * window_size
            evaluation_end = evaluation_start + window_size
            market_regime = self._walk_forward_market_regime(
                training_bars,
                evaluation_start,
                periods_per_year=(cadence.periods_per_year if cadence is not None else 252),
            )
            measured = run_backtest(
                training_bars[:evaluation_end],
                strategy,
                execution,
                measurement_start_index=evaluation_start,
                cadence=cadence,
            )
            benchmark = backtest_buy_and_hold(
                training_bars[evaluation_start:evaluation_end],
                execution,
                cadence=cadence,
            )
            candidate_metrics = self._metrics_projection(measured.metrics)
            benchmark_metrics = self._metrics_projection(benchmark.metrics)
            if measured.metrics.exposure == 0:
                status = "inconclusive"
            elif (
                measured.metrics.total_return > 0
                and measured.metrics.max_drawdown > benchmark.metrics.max_drawdown
            ):
                status = "pass"
            else:
                status = "fail"
            folds.append(
                {
                    "fold_index": fold_index + 1,
                    "history_start": _runtime_bar_label(training_bars[0]),
                    "history_end": _runtime_bar_label(training_bars[evaluation_start - 1]),
                    "evaluation_start": _runtime_bar_label(training_bars[evaluation_start]),
                    "evaluation_end": _runtime_bar_label(training_bars[evaluation_end - 1]),
                    "market_regime": market_regime,
                    "candidate": candidate_metrics,
                    "benchmark": benchmark_metrics,
                    "status": status,
                }
            )

        candidate_returns = [float(item["candidate"]["total_return_pct"]) for item in folds]
        benchmark_returns = [float(item["benchmark"]["total_return_pct"]) for item in folds]
        candidate_drawdowns = [float(item["candidate"]["maximum_drawdown_pct"]) for item in folds]
        benchmark_drawdowns = [float(item["benchmark"]["maximum_drawdown_pct"]) for item in folds]
        candidate_sharpes = [float(item["candidate"]["sharpe_ratio"]) for item in folds]
        benchmark_sharpes = [float(item["benchmark"]["sharpe_ratio"]) for item in folds]
        by_label: dict[str, list[dict[str, Any]]] = {}
        for fold in folds:
            label = str(fold["market_regime"]["label"])
            by_label.setdefault(label, []).append(fold)
        by_market_regime = [
            self._walk_forward_regime_summary(label, by_label[label]) for label in sorted(by_label)
        ]
        aggregate = {
            "evaluated_folds": len(folds),
            "candidate_positive_return_folds": sum(value > 0 for value in candidate_returns),
            "candidate_lower_drawdown_folds": sum(
                candidate > benchmark
                for candidate, benchmark in zip(
                    candidate_drawdowns, benchmark_drawdowns, strict=True
                )
            ),
            "candidate_median_return_pct": round(median(candidate_returns), 4),
            "benchmark_median_return_pct": round(median(benchmark_returns), 4),
            "candidate_median_drawdown_pct": round(median(candidate_drawdowns), 4),
            "benchmark_median_drawdown_pct": round(median(benchmark_drawdowns), 4),
            "candidate_median_sharpe_ratio": round(median(candidate_sharpes), 4),
            "benchmark_median_sharpe_ratio": round(median(benchmark_sharpes), 4),
            "distinct_market_regimes": len(by_market_regime),
            "regime_diversity_status": (
                "covered" if len(by_market_regime) > 1 else "insufficient_regime_diversity"
            ),
            "by_market_regime": by_market_regime,
        }
        return {
            "method": "expanding",
            "rule_version": AGENT_WALK_FORWARD_RULE_VERSION,
            "evaluation_partition": "train",
            "fold_count": AGENT_WALK_FORWARD_FOLDS,
            "window_bar_count": window_size,
            "state_rule_version": AGENT_WALK_FORWARD_STATE_RULE_VERSION,
            "state_lookback_bars": AGENT_WALK_FORWARD_STATE_LOOKBACK_BARS,
            "status": "completed",
            "reason": "Fixed candidate evaluated in three expanding training-only windows.",
            "folds": folds,
            "aggregate": aggregate,
        }

    @staticmethod
    def _walk_forward_market_regime(
        training_bars: tuple[BacktestBar, ...],
        evaluation_start: int,
        *,
        periods_per_year: int = 252,
    ) -> dict[str, Any]:
        """Classify from bars strictly before a walk-forward measurement begins."""
        history_count = min(AGENT_WALK_FORWARD_STATE_LOOKBACK_BARS, evaluation_start)
        history = training_bars[evaluation_start - history_count : evaluation_start]
        closes = [bar.close for bar in history]
        trailing_return = closes[-1] / closes[0] - 1.0
        period_returns = [
            closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))
        ]
        annualized_volatility = (
            pstdev(period_returns) * sqrt(float(periods_per_year)) if period_returns else 0.0
        )
        trend = (
            "uptrend"
            if trailing_return >= AGENT_WALK_FORWARD_TREND_THRESHOLD
            else "downtrend"
            if trailing_return <= -AGENT_WALK_FORWARD_TREND_THRESHOLD
            else "sideways"
        )
        volatility = (
            "high_volatility"
            if annualized_volatility >= AGENT_WALK_FORWARD_HIGH_VOLATILITY_THRESHOLD
            else "normal_volatility"
        )
        return {
            "label": f"{trend}_{volatility}",
            "trend": trend,
            "volatility": volatility,
            "history_start": _runtime_bar_label(history[0]),
            "history_end": _runtime_bar_label(history[-1]),
            "history_bar_count": history_count,
            "trailing_return_pct": round(trailing_return * 100, 4),
            "annualized_volatility_pct": round(annualized_volatility * 100, 4),
        }

    @staticmethod
    def _walk_forward_regime_summary(label: str, folds: list[dict[str, Any]]) -> dict[str, Any]:
        def metric(side: str, name: str) -> float:
            return round(median(float(fold[side][name]) for fold in folds), 4)

        return {
            "label": label,
            "fold_count": len(folds),
            "candidate_median_return_pct": metric("candidate", "total_return_pct"),
            "benchmark_median_return_pct": metric("benchmark", "total_return_pct"),
            "candidate_median_drawdown_pct": metric("candidate", "maximum_drawdown_pct"),
            "benchmark_median_drawdown_pct": metric("benchmark", "maximum_drawdown_pct"),
            "candidate_median_sharpe_ratio": metric("candidate", "sharpe_ratio"),
            "benchmark_median_sharpe_ratio": metric("benchmark", "sharpe_ratio"),
        }

    @classmethod
    def _robustness_parameter_neighbors(
        cls,
        template: str,
        parameters: dict[str, int | float],
    ) -> list[dict[str, Any]]:
        """Return deterministic, de-duplicated one-at-a-time local perturbations."""

        template_definition = next(
            (item for item in cls.agent_templates() if item["name"] == template),
            None,
        )
        if template_definition is None:
            raise ValueError("Unknown strategy template.")
        parameter_definitions = cast(dict[str, dict[str, Any]], template_definition["parameters"])
        if set(parameters) != set(parameter_definitions):
            raise ValueError("Strategy parameters do not match the selected template.")

        normalized: dict[str, int | float] = {}
        for name, definition in parameter_definitions.items():
            value = parameters[name]
            if isinstance(value, bool):
                raise ValueError("Strategy parameters must be numeric.")
            numeric = float(value)
            if not isfinite(numeric):
                raise ValueError("Strategy parameters must be finite.")
            if definition["type"] == "integer":
                if not numeric.is_integer():
                    raise ValueError("Integer strategy parameters must be whole numbers.")
                normalized[name] = int(numeric)
            elif definition["type"] == "number":
                normalized[name] = value
            else:  # pragma: no cover - the closed template registry is server-owned
                raise ValueError("Unsupported strategy parameter type.")
            if not definition["minimum"] <= numeric <= definition["maximum"]:
                raise ValueError("Strategy parameters must stay inside template bounds.")
        cls._strategy_spec(template, normalized)

        baseline_key = cls.canonical_candidate_key(template, normalized)
        seen_keys = {baseline_key}
        neighbors: list[dict[str, Any]] = []
        for name, definition in parameter_definitions.items():
            value = normalized[name]
            step = (
                5
                if template == "rsi_mean_reversion"
                and name in {"entry_threshold", "exit_threshold"}
                else max(1, round(abs(float(value)) * 0.1))
            )
            for direction, signed_step in (("lower", -step), ("upper", step)):
                changed = float(value) + signed_step
                changed = min(float(definition["maximum"]), changed)
                changed = max(float(definition["minimum"]), changed)
                changed_value: int | float = (
                    int(changed) if definition["type"] == "integer" else changed
                )
                if changed_value == value:
                    continue
                neighbor_parameters = {
                    key: (changed_value if key == name else item)
                    for key, item in normalized.items()
                }
                try:
                    cls._strategy_spec(template, neighbor_parameters)
                except (KeyError, OverflowError, TypeError, ValueError):
                    continue
                canonical_key = cls.canonical_candidate_key(template, neighbor_parameters)
                if canonical_key in seen_keys:
                    continue
                seen_keys.add(canonical_key)
                neighbors.append(
                    {
                        "parameter_name": name,
                        "direction": direction,
                        "parameters": neighbor_parameters,
                        "canonical_key": canonical_key,
                    }
                )
        return neighbors

    def _robustness_sensitivity_content(
        self,
        *,
        run: QuantRunRecord,
        selected: QuantExperimentRecord,
        comparison_artifact: QuantArtifactRecord,
        runtime: QuantRuntimeDatasetDescriptor,
        runtime_split: QuantRuntimeSplit,
        report_artifact_id: str,
    ) -> dict[str, Any]:
        """Run bounded sensitivity checks on the training partition only."""

        parameter_definitions = next(
            item["parameters"]
            for item in self.agent_templates()
            if item["name"] == selected.template
        )
        candidate_parameters = {name: selected.parameters[name] for name in parameter_definitions}
        expected_key = self.canonical_candidate_key(selected.template, candidate_parameters)
        if selected.candidate_key != expected_key:
            raise ValueError("Selected candidate canonical identity is invalid.")
        strategy = self._strategy_spec(selected.template, candidate_parameters)
        training_bars = runtime_split.training_bars
        cost_scenarios: list[dict[str, Any]] = []
        kernel_call_count = 0
        for scenario in COST_SENSITIVITY_SCENARIOS:
            candidate_result = run_backtest(
                training_bars,
                strategy,
                scenario.execution,
                cadence=runtime.cadence,
            )
            kernel_call_count += 1
            benchmark_result = backtest_buy_and_hold(
                training_bars,
                scenario.execution,
                cadence=runtime.cadence,
            )
            kernel_call_count += 1
            cost_scenarios.append(
                {
                    "scenario": scenario.name,
                    "multiplier": scenario.multiplier,
                    "fee_rate": scenario.execution.fee_rate,
                    "slippage_rate": scenario.execution.slippage_rate,
                    "candidate_metrics": self._metrics_projection(candidate_result.metrics),
                    "benchmark_metrics": self._metrics_projection(benchmark_result.metrics),
                }
            )

        parameter_neighbors: list[dict[str, Any]] = []
        for neighbor in self._robustness_parameter_neighbors(
            selected.template, candidate_parameters
        ):
            result = run_backtest(
                training_bars,
                self._strategy_spec(selected.template, neighbor["parameters"]),
                BASELINE_EXECUTION,
                cadence=runtime.cadence,
            )
            kernel_call_count += 1
            parameter_neighbors.append(
                {
                    **neighbor,
                    "candidate_metrics": self._metrics_projection(result.metrics),
                }
            )

        split_digest = runtime_split.seal_digest or canonical_digest(
            {
                "identity_kind": "deterministic_legacy_split",
                "metadata": runtime_split.metadata,
            }
        )
        contract = QuantRobustnessSensitivity.model_validate(
            {
                "schema_version": "robustness_sensitivity_v1",
                "evaluation_partition": "train",
                "run_id": run.id,
                "report_artifact_id": report_artifact_id,
                "candidate": {
                    "candidate_id": selected.id,
                    "template": selected.template,
                    "parameters": candidate_parameters,
                    "canonical_key": expected_key,
                },
                "final_training_comparison": {
                    "artifact_id": comparison_artifact.id,
                    "artifact_digest": comparison_artifact.digest,
                },
                "dataset": {
                    "dataset_id": runtime.dataset_id,
                    "dataset_digest": runtime.dataset_digest,
                },
                "interval": runtime.interval.value,
                "periods_per_year": runtime.periods_per_year,
                "runtime_descriptor_digest": runtime.descriptor_digest,
                "training_split": {
                    "identity_kind": (
                        "sealed_market_split"
                        if runtime_split.seal_digest is not None
                        else "deterministic_legacy_split"
                    ),
                    "rule_version": AGENT_SPLIT_RULE_VERSION,
                    "training_bar_count": len(training_bars),
                    "training_start": _runtime_bar_label(training_bars[0]),
                    "training_end": _runtime_bar_label(training_bars[-1]),
                    "training_split_digest": split_digest,
                    "sealed_split_digest": runtime_split.seal_digest,
                },
                "execution_rule_version": EXECUTION_RULE_VERSION,
                "sampler_rule_version": PARAMETER_NEIGHBORHOOD_RULE_VERSION,
                "cost_scenarios": cost_scenarios,
                "parameter_neighbors": parameter_neighbors,
                "kernel_call_count": kernel_call_count,
            }
        )
        return contract.model_dump(mode="json")

    @classmethod
    def _validate_robustness_sensitivity_artifact(
        cls,
        *,
        run: QuantRunRecord,
        selected: QuantExperimentRecord,
        comparison_artifact: QuantArtifactRecord,
        robustness_artifact: QuantArtifactRecord,
        report_artifact: QuantArtifactRecord,
        runtime: QuantRuntimeDatasetDescriptor,
        runtime_split: QuantRuntimeSplit,
    ) -> None:
        """Validate the complete W3-B1 identity graph without re-running kernels."""

        if (
            run.state is not QuantRunState.COMPLETED
            or selected.state != "completed"
            or selected.run_id != run.id
            or robustness_artifact.workspace_id != run.workspace_id
            or robustness_artifact.run_id != run.id
            or robustness_artifact.kind is not QuantArtifactKind.ROBUSTNESS_SENSITIVITY
            or report_artifact.workspace_id != run.workspace_id
            or report_artifact.run_id != run.id
            or report_artifact.kind is not QuantArtifactKind.RESEARCH_REPORT
            or comparison_artifact.workspace_id != run.workspace_id
            or comparison_artifact.run_id != run.id
            or comparison_artifact.kind is not QuantArtifactKind.VALIDATION_REPORT
            or comparison_artifact.content.get("evaluation_partition") != "train"
        ):
            raise ValueError("Persisted Quant robustness sensitivity lineage is invalid.")
        if (
            comparison_artifact.ordinal >= robustness_artifact.ordinal
            or robustness_artifact.ordinal >= report_artifact.ordinal
        ):
            raise ValueError("Persisted Quant robustness sensitivity ordinal is invalid.")
        if (
            robustness_artifact.digest != canonical_digest(robustness_artifact.content)
            or comparison_artifact.digest != canonical_digest(comparison_artifact.content)
            or (
                report_artifact.content.get("research_decision") is not None
                and report_artifact.digest != canonical_digest(report_artifact.content)
            )
        ):
            raise ValueError("Persisted Quant robustness sensitivity digest is invalid.")
        try:
            contract = QuantRobustnessSensitivity.model_validate(robustness_artifact.content)
        except (TypeError, ValueError) as exc:
            raise ValueError("Persisted Quant robustness sensitivity contract is invalid.") from exc

        report_link = report_artifact.content.get("robustness_sensitivity")
        if (
            not isinstance(report_link, dict)
            or set(report_link) != {"artifact_id", "artifact_digest"}
            or report_link["artifact_id"] != robustness_artifact.id
            or report_link["artifact_digest"] != robustness_artifact.digest
            or contract.report_artifact_id != report_artifact.id
            or report_artifact.content.get("selected_candidate_id") != selected.id
        ):
            raise ValueError("Persisted Quant report and robustness sensitivity link is invalid.")

        expected_parameters = {
            name: selected.parameters[name]
            for name in next(
                item["parameters"]
                for item in cls.agent_templates()
                if item["name"] == selected.template
            )
        }
        expected_key = cls.canonical_candidate_key(selected.template, expected_parameters)
        if (
            selected.candidate_key != expected_key
            or contract.run_id != run.id
            or contract.candidate.candidate_id != selected.id
            or contract.candidate.template != selected.template
            or contract.candidate.parameters != expected_parameters
            or contract.candidate.canonical_key != expected_key
            or contract.final_training_comparison.artifact_id != comparison_artifact.id
            or contract.final_training_comparison.artifact_digest != comparison_artifact.digest
            or contract.dataset.dataset_id != runtime.dataset_id
            or contract.dataset.dataset_digest != runtime.dataset_digest
            or contract.interval != runtime.interval.value
            or contract.periods_per_year != runtime.periods_per_year
            or contract.runtime_descriptor_digest != runtime.descriptor_digest
        ):
            raise ValueError("Persisted Quant robustness sensitivity identity is invalid.")

        expected_split_digest = runtime_split.seal_digest or canonical_digest(
            {
                "identity_kind": "deterministic_legacy_split",
                "metadata": runtime_split.metadata,
            }
        )
        expected_split_kind = (
            "sealed_market_split"
            if runtime_split.seal_digest is not None
            else "deterministic_legacy_split"
        )
        split = contract.training_split
        if (
            split.identity_kind != expected_split_kind
            or split.rule_version != AGENT_SPLIT_RULE_VERSION
            or split.training_bar_count != len(runtime_split.training_bars)
            or split.training_start != _runtime_bar_label(runtime_split.training_bars[0])
            or split.training_end != _runtime_bar_label(runtime_split.training_bars[-1])
            or split.training_split_digest != expected_split_digest
            or split.sealed_split_digest != runtime_split.seal_digest
        ):
            raise ValueError("Persisted Quant robustness sensitivity training split is invalid.")

        baseline = contract.cost_scenarios[0]
        comparison_benchmark = comparison_artifact.content.get("benchmark")
        if (
            baseline.candidate_metrics.model_dump(mode="json") != selected.metrics
            or not isinstance(comparison_benchmark, dict)
            or baseline.benchmark_metrics.model_dump(mode="json") != comparison_benchmark
        ):
            raise ValueError("Persisted Quant robustness sensitivity baseline metrics are invalid.")

        expected_neighbors = cls._robustness_parameter_neighbors(
            selected.template, expected_parameters
        )
        retained_neighbor_identities = [
            {
                "parameter_name": item.parameter_name,
                "direction": item.direction,
                "parameters": item.parameters,
                "canonical_key": item.canonical_key,
            }
            for item in contract.parameter_neighbors
        ]
        if retained_neighbor_identities != expected_neighbors:
            raise ValueError("Persisted Quant robustness sensitivity neighborhood is invalid.")

    @staticmethod
    def _strategy_spec(template: str, parameters: dict[str, Any]) -> StrategySpec:
        if template == "sma_crossover":
            return StrategySpec.sma(int(parameters["fast_window"]), int(parameters["slow_window"]))
        if template == "rsi_mean_reversion":
            return StrategySpec.rsi(
                int(parameters.get("period", 14)),
                oversold=float(parameters["entry_threshold"]),
                overbought=float(parameters["exit_threshold"]),
            )
        if template == "breakout":
            return StrategySpec.breakout(int(parameters["lookback_window"]))
        raise ValueError("Unknown strategy template.")

    @staticmethod
    def _metrics_projection(metrics: BacktestMetrics) -> dict[str, Any]:
        return {
            "total_return_pct": round(metrics.total_return * 100, 4),
            "annualized_return_pct": round(metrics.annualized_return * 100, 4),
            "maximum_drawdown_pct": round(metrics.max_drawdown * 100, 4),
            "sharpe_ratio": round(metrics.sharpe_ratio, 4),
            "trade_count": metrics.trade_count,
            "win_rate_pct": round(metrics.win_rate * 100, 4),
            "final_equity": round(metrics.final_equity, 4),
        }

    # Immutable datasets
    def import_dataset_csv(
        self,
        *,
        workspace_id: str,
        name: str,
        symbol: str,
        csv_text: str,
        file_name: str | None = None,
        source_name: str = "User-provided CSV",
        source_reference: str | None = None,
        source_kind: Literal["csv_upload", "provider_fetch"] = "csv_upload",
        provider_id: Literal["binance_spot", "nasdaq_equity"] | None = None,
        provider_response_digest: str | None = None,
        provider_response_attestations: tuple[QuantProviderResponseAttestation, ...] = (),
        corporate_actions_attestation: QuantCorporateActionsAttestation | None = None,
        price_adjustment_verification_status: Literal[
            "not_applicable", "unverified", "verified", "conflict"
        ] = "unverified",
        retrieved_at: datetime | None = None,
        requested_limit: int | None = None,
        returned_bar_count: int | None = None,
        dropped_incomplete_count: int | None = None,
        normalization_note: str | None = None,
        attestation_status: Literal["declared", "provider_retrieved"] = "declared",
        market_calendar: Literal[
            "unknown", "weekday", "24x7", "XNYS", "XNAS", "XSHG", "XSHE"
        ] = "unknown",
        time_zone: str = "UTC",
        price_adjustment: Literal[
            "unknown", "unadjusted", "split_adjusted", "total_return_adjusted"
        ] = "unknown",
    ) -> QuantDatasetRecord:
        dataset = parse_ohlcv_csv(csv_text, name=name, symbol=symbol)
        source_metadata = QuantDatasetSourceMetadata(
            kind=source_kind,
            file_name=file_name,
            source_name=source_name,
            source_reference=source_reference,
            submitted_csv_digest=("sha256:" + sha256(csv_text.encode("utf-8")).hexdigest()),
            provider_id=provider_id,
            provider_response_digest=provider_response_digest,
            provider_response_attestations=provider_response_attestations,
            corporate_actions_attestation=corporate_actions_attestation,
            price_adjustment_verification_status=(price_adjustment_verification_status),
            retrieved_at=retrieved_at,
            requested_limit=requested_limit,
            returned_bar_count=returned_bar_count,
            dropped_incomplete_count=dropped_incomplete_count,
            normalization_note=normalization_note,
            attestation_status=attestation_status,
            market_calendar=market_calendar,
            time_zone=time_zone,
            price_adjustment=price_adjustment,
        )
        data_quality = assess_daily_bar_quality(
            dataset,
            market_calendar=source_metadata.market_calendar,
            time_zone=source_metadata.time_zone,
            price_adjustment=source_metadata.price_adjustment,
        )
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            key = (workspace_id, dataset.dataset_id)
            existing = self._datasets.get(key)
            if existing is not None:
                return existing
            record = QuantDatasetRecord(
                id=dataset.dataset_id,
                workspace_id=workspace_id,
                name=name.strip(),
                dataset=dataset,
                source_metadata=source_metadata,
                data_quality=data_quality,
                data_authenticity=(
                    DataAuthenticity.COLLECTED
                    if source_kind == "provider_fetch"
                    else DataAuthenticity.IMPORTED
                ),
            )
            self._datasets[key] = record
            self._persist_workspace(workspace_id)
            return record

    def list_datasets(self, *, workspace_id: str) -> list[QuantDatasetRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            return sorted(
                (
                    record
                    for record in self._datasets.values()
                    if record.workspace_id == workspace_id
                ),
                key=lambda item: item.created_at,
                reverse=True,
            )

    # Isolated v2 market datasets: stored and previewable, never daily-run inputs in C2B.
    def import_market_dataset_v2(
        self,
        *,
        workspace_id: str,
        name: str,
        dataset: QuantMarketBarDataset,
        evidence: QuantMarketDatasetEvidence,
        quality: QuantMarketDatasetCadenceQuality,
    ) -> QuantMarketDatasetV2Record:
        if not name.strip():
            raise ValueError("v2 market dataset name is required.")
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            key = (workspace_id, dataset.dataset_id)
            existing = self._market_datasets_v2.get(key)
            if existing is not None:
                if (
                    existing.dataset == dataset
                    and existing.quality == quality
                    and (
                        existing.evidence == evidence
                        or _same_connector_refetch(existing.evidence, evidence)
                    )
                ):
                    return existing
                raise invalid_state(
                    "A v2 market dataset with this identity already has different stored evidence."
                )
            record = QuantMarketDatasetV2Record(
                id=dataset.dataset_id,
                workspace_id=workspace_id,
                name=name.strip(),
                dataset=dataset,
                evidence=evidence,
                quality=quality,
                record_digest=_market_dataset_v2_record_digest(
                    dataset=dataset, evidence=evidence, quality=quality
                ),
                data_authenticity=_market_dataset_v2_authenticity(evidence),
            )
            self._market_datasets_v2[key] = record
            try:
                self._persist_workspace(workspace_id)
            except Exception:
                self._market_datasets_v2.pop(key, None)
                raise
            return record

    def import_market_dataset_v2_csv(
        self,
        *,
        workspace_id: str,
        name: str,
        symbol: str,
        interval: QuantBarInterval,
        market_calendar: QuantMarketCalendar = QuantMarketCalendar.CONTINUOUS,
        csv_text: str,
        source_name: str,
        source_reference: str | None,
        file_name: str | None = None,
    ) -> QuantMarketDatasetV2Record:
        dataset = parse_market_ohlcv_csv(
            csv_text,
            symbol=symbol,
            interval=interval,
            market_calendar=market_calendar,
        )
        quality = _market_dataset_cadence_quality(dataset)
        evidence = QuantMarketDatasetEvidence(
            source_kind=QuantMarketDataProvenance.CSV_UPLOAD,
            source_name=source_name,
            source_reference=source_reference,
            file_name=file_name,
            submitted_csv_digest="sha256:" + sha256(csv_text.encode("utf-8")).hexdigest(),
            normalizer_version=QUANT_MARKET_OHLCV_CSV_PARSER_VERSION,
        )
        return self.import_market_dataset_v2(
            workspace_id=workspace_id,
            name=name,
            dataset=dataset,
            evidence=evidence,
            quality=quality,
        )

    def list_market_datasets_v2(self, *, workspace_id: str) -> list[QuantMarketDatasetV2Record]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            return sorted(
                (
                    record
                    for record in self._market_datasets_v2.values()
                    if record.workspace_id == workspace_id
                ),
                key=lambda item: item.created_at,
                reverse=True,
            )

    def get_market_dataset_v2(
        self, *, workspace_id: str, dataset_id: str
    ) -> QuantMarketDatasetV2Record:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            record = self._market_datasets_v2.get((workspace_id, dataset_id))
            if record is None:
                raise not_found("QuantMarketDatasetV2")
            return record

    def market_dataset_v2_preview(
        self, *, workspace_id: str, dataset_id: str, max_points: int
    ) -> dict[str, Any]:
        if not 1 <= max_points <= 400:
            raise ValueError("v2 preview max_points must be from 1 to 400.")
        record = self.get_market_dataset_v2(workspace_id=workspace_id, dataset_id=dataset_id)
        bars = _latest_contiguous_market_tail(record.dataset, max_points=max_points)
        return {
            "dataset": self.to_market_dataset_v2_response(record),
            "data_authenticity": record.data_authenticity.value,
            "total_bar_count": len(record.dataset.bars),
            "returned_bar_count": len(bars),
            "max_points": max_points,
            "sampling_rule": "latest_contiguous",
            "bars": [bar.model_dump(mode="json") for bar in bars],
        }

    def validate_market_dataset_for_run(
        self,
        *,
        workspace_id: str,
        dataset_id: str,
        research_start_utc: datetime,
        research_end_utc: datetime,
    ) -> QuantRuntimeDatasetDescriptor:
        """Validate the public v2 research boundary before provider work or mutation."""

        for value in (research_start_utc, research_end_utc):
            offset = value.utcoffset()
            if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
                raise invalid_state("Market research timestamps must use the UTC offset.")
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            record = self._market_datasets_v2.get((workspace_id, dataset_id))
            if record is None:
                raise not_found("QuantMarketDatasetV2")
            try:
                descriptor = _market_runtime_descriptor(
                    record,
                    coverage_start_utc=research_start_utc,
                    coverage_end_utc=research_end_utc,
                )
                sufficiency = _market_research_sufficiency(
                    interval=record.dataset.interval,
                    periods_per_year=descriptor.periods_per_year,
                    bar_count=len(descriptor.bars),
                    coverage_start_utc=descriptor.coverage_start_utc,
                    coverage_end_utc=descriptor.coverage_end_utc,
                )
                if not sufficiency.eligible:
                    raise ValueError(
                        "Runtime research requires at least "
                        f"{sufficiency.required_bars:,} cadence-consistent "
                        f"{record.dataset.interval.value} bars."
                    )
                _runtime_split(descriptor)
            except ValueError as exc:
                raise invalid_state(str(exc)) from exc
            return descriptor

    def validate_market_run_create(
        self,
        *,
        workspace_id: str,
        project_id: str,
        expected_project_row_version: int,
        dataset_id: str,
        research_start_utc: datetime,
        research_end_utc: datetime,
        parent_run_id: str | None = None,
        seed_candidate_id: str | None = None,
        refinement_reason: str | None = None,
    ) -> QuantRuntimeDatasetDescriptor:
        """Validate every create precondition before an Agent provider is invoked."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            project = self.get_project(workspace_id=workspace_id, project_id=project_id)
            if project.row_version != expected_project_row_version:
                raise version_conflict(project.id, project.row_version)
            descriptor = self.validate_market_dataset_for_run(
                workspace_id=workspace_id,
                dataset_id=dataset_id,
                research_start_utc=research_start_utc,
                research_end_utc=research_end_utc,
            )
            self._validate_refinement(
                workspace_id=workspace_id,
                project_id=project_id,
                dataset_id=dataset_id,
                parent_run_id=parent_run_id,
                seed_candidate_id=seed_candidate_id,
                refinement_reason=refinement_reason,
                contract_family="market-v2-public",
                runtime_descriptor=descriptor,
            )
            return descriptor

    def _reject_market_dataset_v2_for_research(
        self, *, workspace_id: str, dataset_id: str | None
    ) -> None:
        if dataset_id is not None and (workspace_id, dataset_id) in self._market_datasets_v2:
            raise invalid_state(
                "This v2 dataset uses the dedicated public /v1/quant/market-runs contract; "
                "the legacy daily Run contract cannot accept it."
            )

    def _reject_private_market_run_public_mutation(self, run: QuantRunRecord) -> None:
        """Keep legacy Run mutations closed for every cadence-aware v2 record."""

        has_runtime_pins = any(
            value is not None
            for value in (
                run.research_start_utc,
                run.research_end_utc,
                run.runtime_interval,
                run.runtime_periods_per_year,
                run.runtime_descriptor_digest,
                run.runtime_split_digest,
            )
        )
        if has_runtime_pins:
            if run.market_run_contract_version == QUANT_MARKET_RUN_CONTRACT_VERSION:
                raise invalid_state(
                    "This public market Run must use the dedicated market-run endpoint."
                )
            raise invalid_state(
                "This private multi-interval Run is readable, but public mutations remain disabled."
            )
        self._reject_market_dataset_v2_for_research(
            workspace_id=run.workspace_id,
            dataset_id=run.dataset_id,
        )

    def _require_public_market_run(self, run: QuantRunRecord) -> None:
        """Fail closed unless a persisted v2 Run owns the public market contract."""

        if run.market_run_contract_version != QUANT_MARKET_RUN_CONTRACT_VERSION:
            raise invalid_state("This Run is not a public market-run v2 resource.")
        self._runtime_descriptor(run)

    def _require_private_market_runtime_run(self, run: QuantRunRecord) -> None:
        if run.market_run_contract_version is not None:
            raise invalid_state("A public market Run cannot use a private runtime boundary.")
        if (run.workspace_id, run.dataset_id) not in self._market_datasets_v2:
            raise invalid_state("Internal market runtime operation requires a v2 dataset.")
        self._runtime_descriptor(run)

    def dataset_for_run(self, run: QuantRunRecord) -> QuantDailyBarDataset:
        if run.dataset_id == SPY_DAILY_FIXTURE.dataset_id:
            dataset = SPY_DAILY_FIXTURE
        else:
            record = self._datasets.get((run.workspace_id, run.dataset_id))
            if record is None:
                raise not_found("QuantDataset")
            dataset = record.dataset
        if dataset.digest != run.dataset_digest:
            raise invalid_state("The run's pinned dataset digest no longer matches storage.")
        return dataset

    def _dataset_data_authenticity(self, *, workspace_id: str, dataset_id: str) -> DataAuthenticity:
        """Use the pinned dataset's real origin for every run-derived record."""

        if dataset_id == SPY_DAILY_FIXTURE.dataset_id:
            return DataAuthenticity.GENERATED
        record = self._datasets.get((workspace_id, dataset_id))
        if record is None:
            raise not_found("QuantDataset")
        return record.data_authenticity

    def bars_for_run(self, run: QuantRunRecord):
        dataset = self.dataset_for_run(run)
        return tuple(
            bar
            for bar in dataset.bars
            if run.research_start <= bar.trading_date <= run.research_end
        )

    def get_dataset(self, *, workspace_id: str, dataset_id: str) -> QuantDatasetRecord | None:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            if dataset_id == SPY_DAILY_FIXTURE.dataset_id:
                return None
            record = self._datasets.get((workspace_id, dataset_id))
            if record is None:
                raise not_found("QuantDataset")
            return record

    def dataset_preview(
        self, *, workspace_id: str, dataset_id: str, max_points: int
    ) -> dict[str, Any]:
        """Return a bounded, contiguous tail of stored OHLCV observations."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            dataset = self._resolve_dataset(workspace_id=workspace_id, dataset_id=dataset_id)
            preview_bars = dataset.bars[-max_points:]
            return {
                "dataset_id": dataset.dataset_id,
                "symbol": dataset.symbol,
                "interval": dataset.interval,
                "data_authenticity": self._dataset_data_authenticity(
                    workspace_id=workspace_id,
                    dataset_id=dataset.dataset_id,
                ).value,
                "covered_start": dataset.covered_start,
                "covered_end": dataset.covered_end,
                "total_bar_count": len(dataset.bars),
                "returned_bar_count": len(preview_bars),
                "max_points": max_points,
                "sampling_rule": "latest_contiguous",
                "bars": [
                    {
                        "date": bar.trading_date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                    }
                    for bar in preview_bars
                ],
            }

    def _resolve_dataset(
        self, *, workspace_id: str, dataset_id: str | None
    ) -> QuantDailyBarDataset:
        selected_id = dataset_id or SPY_DAILY_FIXTURE.dataset_id
        if selected_id == SPY_DAILY_FIXTURE.dataset_id:
            return SPY_DAILY_FIXTURE
        record = self._datasets.get((workspace_id, selected_id))
        if record is None:
            raise not_found("QuantDataset")
        quality = _dataset_quality(record)
        if quality.status == "blocked":
            issue_codes = ", ".join(
                issue.code for issue in quality.issues if issue.severity == "blocked"
            )
            raise invalid_state(
                "Autonomous research is blocked by data quality checks: " + issue_codes
            )
        if len(record.dataset.bars) < MIN_AUTONOMOUS_RESEARCH_BARS:
            raise invalid_state(
                f"Autonomous research requires at least {MIN_AUTONOMOUS_RESEARCH_BARS} daily bars."
            )
        return record.dataset

    def validate_dataset_for_run(
        self,
        *,
        workspace_id: str,
        dataset_id: str | None,
        research_start: date | None = None,
        research_end: date | None = None,
    ) -> QuantDailyBarDataset:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            self._reject_market_dataset_v2_for_research(
                workspace_id=workspace_id, dataset_id=dataset_id
            )
            dataset = self._resolve_dataset(workspace_id=workspace_id, dataset_id=dataset_id)
            start = research_start or dataset.covered_start
            end = research_end or dataset.covered_end
            if start < dataset.covered_start or end > dataset.covered_end or start > end:
                raise invalid_state("Research range must stay inside dataset coverage.")
            selected_bars = tuple(bar for bar in dataset.bars if start <= bar.trading_date <= end)
            if len(selected_bars) < MIN_AUTONOMOUS_RESEARCH_BARS:
                raise invalid_state(
                    f"Research range requires at least {MIN_AUTONOMOUS_RESEARCH_BARS} daily bars."
                )
            return dataset

    # Projects
    def create_project(self, *, workspace_id: str, name: str, objective: str) -> QuantProjectRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            project = QuantProjectRecord(
                id=str(_uuid("project", workspace_id, name, objective)),
                workspace_id=workspace_id,
                name=name,
                objective=objective,
            )
            self._projects[project.id] = project
            self._persist_workspace(workspace_id)
            return project

    def list_projects(self, *, workspace_id: str) -> list[QuantProjectRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            return [
                project
                for project in sorted(
                    self._projects.values(), key=lambda item: item.created_at, reverse=True
                )
                if project.workspace_id == workspace_id
            ]

    def get_project(self, *, workspace_id: str, project_id: str) -> QuantProjectRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            project = self._projects.get(project_id)
            if project is None or project.workspace_id != workspace_id:
                raise not_found("QuantProject")
            return project

    # Runs
    def create_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        question: str,
        mode: QuantRunMode,
        expected_project_row_version: int,
        agent_plan: QuantAgentPlan | None = None,
        dataset_id: str | None = None,
        research_start: date | None = None,
        research_end: date | None = None,
        parent_run_id: str | None = None,
        seed_candidate_id: str | None = None,
        refinement_reason: str | None = None,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            project = self.get_project(workspace_id=workspace_id, project_id=project_id)
            if project.row_version != expected_project_row_version:
                raise version_conflict(project.id, project.row_version)
            self._reject_market_dataset_v2_for_research(
                workspace_id=workspace_id, dataset_id=dataset_id
            )
            dataset = self._resolve_dataset(workspace_id=workspace_id, dataset_id=dataset_id)
            parent, seed = self._validate_refinement(
                workspace_id=workspace_id,
                project_id=project_id,
                dataset_id=dataset.dataset_id,
                parent_run_id=parent_run_id,
                seed_candidate_id=seed_candidate_id,
                refinement_reason=refinement_reason,
            )
            self.validate_dataset_for_run(
                workspace_id=workspace_id,
                dataset_id=dataset_id,
                research_start=research_start,
                research_end=research_end,
            )
            selected_start = research_start or dataset.covered_start
            selected_end = research_end or dataset.covered_end
            run_id = str(
                _uuid(
                    "run",
                    workspace_id,
                    project_id,
                    question,
                    mode.value,
                    dataset.dataset_id,
                    selected_start,
                    selected_end,
                    parent.id if parent is not None else None,
                    seed.id if seed is not None else None,
                    project.row_version,
                )
            )
            run = QuantRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                question=question,
                mode=mode,
                dataset_id=dataset.dataset_id,
                dataset_digest=dataset.digest,
                research_start=selected_start,
                research_end=selected_end,
                parent_run_id=parent.id if parent is not None else None,
                seed_candidate_id=seed.id if seed is not None else None,
                refinement_reason=refinement_reason.strip() if refinement_reason else None,
                research_memory_contract_version=RESEARCH_MEMORY_CONTRACT_VERSION,
                trace_id=str(_uuid("trace", run_id, 1)),
                provider=self._configured_agent_provider(),
                model=self._configured_agent_model(),
                data_authenticity=self._dataset_data_authenticity(
                    workspace_id=workspace_id, dataset_id=dataset.dataset_id
                ),
            )
            baseline = self._workspace_mutation_baseline(workspace_id)
            try:
                self._runs[run.id] = run
                project.latest_run_id = run.id
                project.row_version += 1
                project.updated_at = _utcnow()
                self._append_event(
                    run,
                    "run.queued",
                    {
                        "state": QuantRunState.QUEUED,
                        "attempt_number": run.attempt_number,
                        "safe_summary": "The run was queued.",
                    },
                )
                self._publish_plan(run, agent_plan)
                run.research_memory = self._build_research_memory_pin(run)
                run.repair_memory = self._build_repair_memory_pin(run)
                self._cross_pin_research_memory_to_plan(run)
                if mode is QuantRunMode.AUTO and run.strategy_scope.status == "supported":
                    self._start_run(run, "Auto Research accepted the generated bounded plan.")
            except Exception:
                self._restore_mutation_baseline(workspace_id, baseline)
                raise
            self._persist_workspace_or_restore(workspace_id, baseline)
            return run

    def _create_market_runtime_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        question: str,
        mode: QuantRunMode,
        expected_project_row_version: int,
        dataset_id: str,
        research_start_utc: datetime | None = None,
        research_end_utc: datetime | None = None,
    ) -> QuantRunRecord:
        """Provision a full-coverage v2 run for internal C3B1 verification only."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            project = self.get_project(workspace_id=workspace_id, project_id=project_id)
            if project.row_version != expected_project_row_version:
                raise version_conflict(project.id, project.row_version)
            record = self._market_datasets_v2.get((workspace_id, dataset_id))
            if record is None:
                raise not_found("QuantMarketDatasetV2")
            try:
                descriptor = _market_runtime_descriptor(record)
                split = _runtime_split(descriptor)
            except ValueError as exc:
                raise invalid_state(str(exc)) from exc
            selected_start = research_start_utc or descriptor.coverage_start_utc
            selected_end = research_end_utc or descriptor.coverage_end_utc
            if (
                selected_start != descriptor.coverage_start_utc
                or selected_end != descriptor.coverage_end_utc
            ):
                raise invalid_state(
                    "C3B1 market runtime research requires the complete UTC dataset coverage."
                )
            run_id = str(
                _uuid(
                    "market-runtime-run",
                    workspace_id,
                    project_id,
                    question,
                    mode.value,
                    descriptor.descriptor_digest,
                    split.seal_digest,
                    project.row_version,
                )
            )
            run = QuantRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                question=question,
                mode=mode,
                dataset_id=descriptor.dataset_id,
                dataset_digest=descriptor.dataset_digest,
                research_start=descriptor.coverage_start_utc.date(),
                research_end=descriptor.coverage_end_utc.date(),
                research_start_utc=descriptor.coverage_start_utc,
                research_end_utc=descriptor.coverage_end_utc,
                runtime_interval=descriptor.interval,
                runtime_periods_per_year=descriptor.periods_per_year,
                runtime_descriptor_digest=descriptor.descriptor_digest,
                runtime_split_digest=split.seal_digest,
                research_memory_contract_version=RESEARCH_MEMORY_CONTRACT_VERSION,
                trace_id=str(_uuid("trace", run_id, 1)),
                provider=self._configured_agent_provider(),
                model=self._configured_agent_model(),
                data_authenticity=descriptor.data_authenticity,
            )
            baseline = self._workspace_mutation_baseline(workspace_id)
            try:
                self._runs[run.id] = run
                project.latest_run_id = run.id
                project.row_version += 1
                project.updated_at = _utcnow()
                self._append_event(
                    run,
                    "run.queued",
                    {
                        "state": QuantRunState.QUEUED,
                        "attempt_number": run.attempt_number,
                        "safe_summary": "The internal market runtime run was queued.",
                    },
                )
                self._publish_plan(run)
                run.research_memory = self._build_research_memory_pin(run)
                run.repair_memory = self._build_repair_memory_pin(run)
                self._cross_pin_research_memory_to_plan(run)
                if mode is QuantRunMode.AUTO and run.strategy_scope.status == "supported":
                    self._start_run(run, "Internal market runtime verification accepted the plan.")
            except Exception:
                self._restore_mutation_baseline(workspace_id, baseline)
                raise
            self._persist_workspace_or_restore(workspace_id, baseline)
            return run

    def create_market_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        question: str,
        mode: QuantRunMode,
        expected_project_row_version: int,
        dataset_id: str,
        research_start_utc: datetime,
        research_end_utc: datetime,
        agent_plan: QuantAgentPlan | None = None,
        parent_run_id: str | None = None,
        seed_candidate_id: str | None = None,
        refinement_reason: str | None = None,
        research_loop: QuantResearchLoopPolicy | None = None,
    ) -> QuantRunRecord:
        """Create a public bounded-window run from a stored, eligible v2 dataset."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            if research_loop is not None and (
                mode is not QuantRunMode.AUTO or parent_run_id is not None
            ):
                raise invalid_state(
                    "A research loop can be enabled only on a root Auto Research Run."
                )
            descriptor = self.validate_market_run_create(
                workspace_id=workspace_id,
                project_id=project_id,
                expected_project_row_version=expected_project_row_version,
                dataset_id=dataset_id,
                research_start_utc=research_start_utc,
                research_end_utc=research_end_utc,
                parent_run_id=parent_run_id,
                seed_candidate_id=seed_candidate_id,
                refinement_reason=refinement_reason,
            )
            project = self.get_project(workspace_id=workspace_id, project_id=project_id)
            split = _runtime_split(descriptor)
            parent, seed = self._validate_refinement(
                workspace_id=workspace_id,
                project_id=project_id,
                dataset_id=descriptor.dataset_id,
                parent_run_id=parent_run_id,
                seed_candidate_id=seed_candidate_id,
                refinement_reason=refinement_reason,
                contract_family="market-v2-public",
                runtime_descriptor=descriptor,
            )
            run_id = str(
                _uuid(
                    "public-market-run",
                    workspace_id,
                    project_id,
                    question,
                    mode.value,
                    descriptor.descriptor_digest,
                    split.seal_digest,
                    parent.id if parent is not None else None,
                    seed.id if seed is not None else None,
                    project.row_version,
                )
            )
            run = QuantRunRecord(
                id=run_id,
                workspace_id=workspace_id,
                project_id=project_id,
                question=question,
                mode=mode,
                dataset_id=descriptor.dataset_id,
                dataset_digest=descriptor.dataset_digest,
                research_start=descriptor.coverage_start_utc.date(),
                research_end=descriptor.coverage_end_utc.date(),
                research_start_utc=descriptor.coverage_start_utc,
                research_end_utc=descriptor.coverage_end_utc,
                runtime_interval=descriptor.interval,
                runtime_periods_per_year=descriptor.periods_per_year,
                runtime_descriptor_digest=descriptor.descriptor_digest,
                runtime_split_digest=split.seal_digest,
                market_run_contract_version=QUANT_MARKET_RUN_CONTRACT_VERSION,
                parent_run_id=parent.id if parent is not None else None,
                seed_candidate_id=seed.id if seed is not None else None,
                refinement_reason=refinement_reason.strip() if refinement_reason else None,
                research_loop_policy=research_loop,
                research_memory_contract_version=RESEARCH_MEMORY_CONTRACT_VERSION,
                trace_id=str(_uuid("trace", run_id, 1)),
                provider=self._configured_agent_provider(),
                model=self._configured_agent_model(),
                data_authenticity=descriptor.data_authenticity,
            )
            if research_loop is not None:
                run.research_series_root_run_id = run.id
                run.research_series_version = 1
            baseline = self._workspace_mutation_baseline(workspace_id)
            try:
                self._runs[run.id] = run
                project.latest_run_id = run.id
                project.row_version += 1
                project.updated_at = _utcnow()
                self._append_event(
                    run,
                    "run.queued",
                    {
                        "state": QuantRunState.QUEUED,
                        "attempt_number": run.attempt_number,
                        "safe_summary": "The market research run was queued.",
                    },
                )
                self._publish_plan(run, agent_plan)
                run.research_memory = self._build_research_memory_pin(run)
                run.repair_memory = self._build_repair_memory_pin(run)
                self._cross_pin_research_memory_to_plan(run)
                if mode is QuantRunMode.AUTO and run.strategy_scope.status == "supported":
                    self._start_run(run, "Auto Research accepted the cadence-aware plan.")
            except Exception:
                self._restore_mutation_baseline(workspace_id, baseline)
                raise
            self._persist_workspace_or_restore(workspace_id, baseline)
            return run

    def _validate_refinement(
        self,
        *,
        workspace_id: str,
        project_id: str,
        dataset_id: str,
        parent_run_id: str | None,
        seed_candidate_id: str | None,
        refinement_reason: str | None,
        contract_family: Literal["legacy-daily-v1", "market-v2-public"] = "legacy-daily-v1",
        runtime_descriptor: QuantRuntimeDatasetDescriptor | None = None,
    ) -> tuple[QuantRunRecord | None, QuantExperimentRecord | None]:
        fields = (parent_run_id, seed_candidate_id, refinement_reason)
        if not any(fields):
            return None, None
        if not all(fields):
            raise invalid_state(
                "A refinement requires the source run, source candidate and a reason together."
            )
        assert (
            parent_run_id is not None
            and seed_candidate_id is not None
            and refinement_reason is not None
        )
        if not refinement_reason.strip() or len(refinement_reason.strip()) > 2_000:
            raise invalid_state("A refinement reason must contain 1 to 2,000 characters.")
        parent = self.get_run(workspace_id=workspace_id, run_id=parent_run_id)
        if contract_family == "legacy-daily-v1":
            self._reject_private_market_run_public_mutation(parent)
        else:
            if runtime_descriptor is None:  # pragma: no cover - internal closed call boundary
                raise invalid_state("A public market refinement requires a runtime descriptor.")
            self._require_public_market_run(parent)
            parent_runtime = self._runtime_descriptor(parent)
            parent_source_identity = (
                parent.dataset_id,
                parent.dataset_digest,
                parent_runtime.record_digest,
                parent_runtime.symbol,
                parent_runtime.interval,
                parent_runtime.periods_per_year,
                parent.market_run_contract_version,
                parent.data_authenticity,
            )
            requested_source_identity = (
                runtime_descriptor.dataset_id,
                runtime_descriptor.dataset_digest,
                runtime_descriptor.record_digest,
                runtime_descriptor.symbol,
                runtime_descriptor.interval,
                runtime_descriptor.periods_per_year,
                QUANT_MARKET_RUN_CONTRACT_VERSION,
                runtime_descriptor.data_authenticity,
            )
            if parent_source_identity != requested_source_identity:
                raise invalid_state(
                    "Market refinements must retain the source dataset and cadence identity."
                )
        if parent.project_id != project_id:
            raise invalid_state("Refinements must stay in the source research project.")
        if parent.state not in {
            QuantRunState.COMPLETED,
            QuantRunState.FAILED,
            QuantRunState.CANCELLED,
        }:
            raise invalid_state("Continue research requires a terminal source run.")
        if parent.dataset_id != dataset_id:
            raise invalid_state("Refinements must use the source dataset.")
        seed = self._experiments.get(seed_candidate_id)
        if (
            seed is None
            or seed.workspace_id != workspace_id
            or seed.run_id != parent.id
            or seed.state != "completed"
            or seed.template == "fixture"
            or not seed.parameters
        ):
            raise invalid_state(
                "The source candidate no longer has a usable strategy specification."
            )
        try:
            self._strategy_spec(seed.template, seed.parameters)
        except (KeyError, OverflowError, TypeError, ValueError) as exc:
            raise invalid_state(
                "The source candidate no longer has a usable strategy specification."
            ) from exc
        return parent, seed

    def list_runs(
        self, *, workspace_id: str, project_id: str | None = None
    ) -> list[QuantRunRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            runs = [run for run in self._runs.values() if run.workspace_id == workspace_id]
            if project_id is not None:
                runs = [run for run in runs if run.project_id == project_id]
            return sorted(runs, key=lambda item: item.created_at, reverse=True)

    def list_legacy_runs(
        self, *, workspace_id: str, project_id: str | None = None
    ) -> list[QuantRunRecord]:
        """Return only runs representable by the unchanged daily v1 response contract."""

        return [
            run
            for run in self.list_runs(workspace_id=workspace_id, project_id=project_id)
            if run.runtime_interval is None and run.market_run_contract_version is None
        ]

    def list_market_runs(
        self, *, workspace_id: str, project_id: str | None = None
    ) -> list[QuantRunRecord]:
        runs = [
            run
            for run in self.list_runs(workspace_id=workspace_id, project_id=project_id)
            if run.market_run_contract_version == QUANT_MARKET_RUN_CONTRACT_VERSION
        ]
        for run in runs:
            self._require_public_market_run(run)
        return runs

    def get_run(self, *, workspace_id: str, run_id: str) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self._runs.get(run_id)
            if run is None or run.workspace_id != workspace_id:
                raise not_found("QuantRun")
            return run

    def get_legacy_run(self, *, workspace_id: str, run_id: str) -> QuantRunRecord:
        run = self.get_run(workspace_id=workspace_id, run_id=run_id)
        self._reject_private_market_run_public_mutation(run)
        return run

    def get_market_run(self, *, workspace_id: str, run_id: str) -> QuantRunRecord:
        run = self.get_run(workspace_id=workspace_id, run_id=run_id)
        self._require_public_market_run(run)
        return run

    def approve_plan(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        plan_revision: int,
        reason: str | None,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._reject_private_market_run_public_mutation(run)
            return self._approve_plan_locked(
                run=run,
                expected_row_version=expected_row_version,
                plan_revision=plan_revision,
                reason=reason,
            )

    def approve_market_run_plan(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        plan_revision: int,
        reason: str | None,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._require_public_market_run(run)
            return self._approve_plan_locked(
                run=run,
                expected_row_version=expected_row_version,
                plan_revision=plan_revision,
                reason=reason,
            )

    def _approve_plan_locked(
        self,
        *,
        run: QuantRunRecord,
        expected_row_version: int,
        plan_revision: int,
        reason: str | None,
    ) -> QuantRunRecord:
        if (
            run.row_version != expected_row_version
            and run.state is not QuantRunState.RUNNING_EXPERIMENTS
        ):
            raise version_conflict(run.id, run.row_version)
        if run.plan_revision != plan_revision:
            raise invalid_state("The plan revision is no longer current.")
        if run.strategy_scope.status == "unsupported":
            raise invalid_state(
                "Unsupported strategy scope cannot be approved; request plan changes or cancel."
            )
        if run.state is QuantRunState.CANCELLED:
            return run
        if run.state in {QuantRunState.COMPLETED, QuantRunState.FAILED}:
            return run
        if run.state is QuantRunState.RUNNING_EXPERIMENTS:
            return run
        if run.state is not QuantRunState.WAITING_PLAN_APPROVAL:
            raise invalid_state("Approve-plan requires a plan awaiting approval.")
        baseline = self._workspace_mutation_baseline(run.workspace_id)
        self._start_run(run, reason, explicit_approval=True)
        self._persist_workspace_or_restore(run.workspace_id, baseline)
        return run

    def request_plan_changes(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        plan_revision: int,
        change_request: str,
        agent_plan: QuantAgentPlan | None = None,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._reject_private_market_run_public_mutation(run)
            return self._request_plan_changes_locked(
                run=run,
                expected_row_version=expected_row_version,
                plan_revision=plan_revision,
                change_request=change_request,
                agent_plan=agent_plan,
            )

    def prepare_plan_changes(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        plan_revision: int,
    ) -> str | None:
        """Validate a legacy replan before an external planner call, without mutation."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._reject_private_market_run_public_mutation(run)
            return (
                run.question
                if self._validate_plan_changes_locked(
                    run=run,
                    expected_row_version=expected_row_version,
                    plan_revision=plan_revision,
                )
                else None
            )

    def request_market_run_plan_changes(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        plan_revision: int,
        change_request: str,
        agent_plan: QuantAgentPlan | None = None,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._require_public_market_run(run)
            return self._request_plan_changes_locked(
                run=run,
                expected_row_version=expected_row_version,
                plan_revision=plan_revision,
                change_request=change_request,
                agent_plan=agent_plan,
            )

    def prepare_market_run_plan_changes(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        plan_revision: int,
    ) -> str | None:
        """Validate a public market replan before an external planner call, without mutation."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._require_public_market_run(run)
            return (
                run.question
                if self._validate_plan_changes_locked(
                    run=run,
                    expected_row_version=expected_row_version,
                    plan_revision=plan_revision,
                )
                else None
            )

    @staticmethod
    def _validate_plan_changes_locked(
        *, run: QuantRunRecord, expected_row_version: int, plan_revision: int
    ) -> bool:
        if run.row_version != expected_row_version:
            raise invalid_state("The Run row version is no longer current.")
        if run.plan_revision != plan_revision:
            raise invalid_state("The plan revision is no longer current.")
        if run.state is QuantRunState.CANCELLED:
            return False
        if run.state in {QuantRunState.COMPLETED, QuantRunState.FAILED}:
            raise invalid_state("Plan changes can only be requested before a run finishes.")
        if run.state is not QuantRunState.WAITING_PLAN_APPROVAL:
            raise invalid_state("Plan changes require a plan awaiting approval.")
        return True

    def _request_plan_changes_locked(
        self,
        *,
        run: QuantRunRecord,
        expected_row_version: int,
        plan_revision: int,
        change_request: str,
        agent_plan: QuantAgentPlan | None = None,
    ) -> QuantRunRecord:
        if not self._validate_plan_changes_locked(
            run=run,
            expected_row_version=expected_row_version,
            plan_revision=plan_revision,
        ):
            return run
        if agent_plan is None:
            raise invalid_state("Plan changes require a newly generated executable Agent plan.")
        baseline = self._workspace_mutation_baseline(run.workspace_id)
        run.plan_change_request = change_request
        run.plan_revision += 1
        run.state = QuantRunState.PLANNING
        run.row_version += 1
        run.updated_at = _utcnow()
        self._append_event(
            run,
            "plan.changes_requested",
            {
                "state": QuantRunState.PLANNING,
                "plan_revision": plan_revision,
                "reason_code": "plan_changes_requested",
                "safe_summary": "Changes were requested for the plan.",
            },
        )
        self._publish_plan(run, agent_plan)
        self._persist_workspace_or_restore(run.workspace_id, baseline)
        return run

    def cancel_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._reject_private_market_run_public_mutation(run)
            return self._cancel_run_locked(
                run=run,
                expected_row_version=expected_row_version,
                reason=reason,
            )

    def _cancel_market_runtime_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        """Cancel an internally provisioned v2 Run without opening a public boundary."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._require_private_market_runtime_run(run)
            return self._cancel_run_locked(
                run=run,
                expected_row_version=expected_row_version,
                reason=reason,
            )

    def cancel_market_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._require_public_market_run(run)
            return self._cancel_run_locked(
                run=run,
                expected_row_version=expected_row_version,
                reason=reason,
            )

    def _cancel_run_locked(
        self,
        *,
        run: QuantRunRecord,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        workspace_id = run.workspace_id
        if run.row_version != expected_row_version and run.state is not QuantRunState.CANCELLED:
            raise version_conflict(run.id, run.row_version)
        if run.state is QuantRunState.CANCELLED:
            self._ensure_worker_lease_invalidated(run)
            return run
        if run.state in {QuantRunState.COMPLETED, QuantRunState.FAILED}:
            return run
        baseline = self._workspace_mutation_baseline(workspace_id)
        run.state = QuantRunState.CANCELLED
        run.agent_status = "cancelled"
        run.cancelled_reason = reason
        run.row_version += 1
        run.updated_at = _utcnow()
        self._append_event(
            run,
            "run.cancelled",
            {
                "state": QuantRunState.CANCELLED,
                "reason_code": reason,
                "safe_summary": "Run cancelled.",
            },
        )
        self._persist_workspace_or_restore(workspace_id, baseline)
        self._ensure_worker_lease_invalidated(run)
        return run

    def retry_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            # A corrupt legacy row must not turn the idempotent retry branch into
            # an escape hatch for C2B-only market datasets.
            self._reject_private_market_run_public_mutation(run)
            return self._retry_run_locked(
                run=run,
                expected_row_version=expected_row_version,
                reason=reason,
            )

    def _retry_market_runtime_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        """Retry an internally provisioned v2 run without opening the public gate."""

        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._require_private_market_runtime_run(run)
            return self._retry_run_locked(
                run=run,
                expected_row_version=expected_row_version,
                reason=reason,
            )

    def retry_market_run(
        self,
        *,
        workspace_id: str,
        run_id: str,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            self._require_public_market_run(run)
            return self._retry_run_locked(
                run=run,
                expected_row_version=expected_row_version,
                reason=reason,
            )

    @staticmethod
    def _refinement_pair_error(parent: QuantRunRecord, child: QuantRunRecord) -> str | None:
        if parent.id == child.id:
            return "A Quant refinement cannot reference itself."
        if parent.workspace_id != child.workspace_id:
            return "A Quant refinement must stay in its source workspace."
        if parent.project_id != child.project_id:
            return "A Quant refinement must stay in its source project."
        if parent.dataset_id != child.dataset_id or parent.dataset_digest != child.dataset_digest:
            return "A Quant refinement must retain its source dataset identity."

        def contract_family(run: QuantRunRecord) -> str:
            if run.runtime_interval is None and run.market_run_contract_version is None:
                return "legacy-daily-v1"
            if run.market_run_contract_version == QUANT_MARKET_RUN_CONTRACT_VERSION:
                return "market-v2-public"
            return "market-v2-private"

        parent_family = contract_family(parent)
        child_family = contract_family(child)
        if parent_family != child_family:
            return "A Quant refinement must retain its source Run contract family."
        if child_family == "market-v2-private":
            return "A private market runtime Run cannot contain public refinement lineage."
        if child_family == "market-v2-public":
            parent_source_identity = (
                parent.runtime_interval,
                parent.runtime_periods_per_year,
                parent.market_run_contract_version,
                parent.data_authenticity,
            )
            child_source_identity = (
                child.runtime_interval,
                child.runtime_periods_per_year,
                child.market_run_contract_version,
                child.data_authenticity,
            )
            if parent_source_identity != child_source_identity:
                return (
                    "A Quant market refinement must retain its source dataset and cadence identity."
                )
        if parent.state not in {
            QuantRunState.COMPLETED,
            QuantRunState.FAILED,
            QuantRunState.CANCELLED,
        }:
            return "A Quant refinement requires a terminal source Run."
        return None

    @staticmethod
    def _retry_pair_error(source: QuantRunRecord, child: QuantRunRecord) -> str | None:
        if source.id == child.id:
            return "A Quant retry cannot reference itself."
        if source.retry_child_run_id != child.id or child.retry_of_run_id != source.id:
            return "Quant retry source and child links must agree in both directions."
        if child.attempt_number != source.attempt_number + 1:
            return "A Quant retry child must advance the attempt number exactly once."
        source_identity = (
            source.workspace_id,
            source.project_id,
            source.question,
            source.mode,
            source.dataset_id,
            source.dataset_digest,
            source.research_start,
            source.research_end,
            source.research_start_utc,
            source.research_end_utc,
            source.runtime_interval,
            source.runtime_periods_per_year,
            source.runtime_descriptor_digest,
            source.runtime_split_digest,
            source.market_run_contract_version,
            source.parent_run_id,
            source.seed_candidate_id,
            source.refinement_reason,
            source.provider,
            source.model,
            source.max_agent_iterations,
            source.max_experiments,
            source.max_repairs,
            source.strategy_scope.model_dump(mode="json"),
            tuple(source.planned_candidate_families),
            source.selection_objective,
            tuple(source.completion_criteria),
            source.data_authenticity,
            source.research_loop_policy,
            source.research_series_root_run_id,
            source.research_series_version,
            (
                source.research_memory.model_dump(mode="json")
                if source.research_memory is not None
                else None
            ),
            (
                source.repair_memory.model_dump(mode="json")
                if source.repair_memory is not None
                else None
            ),
        )
        child_identity = (
            child.workspace_id,
            child.project_id,
            child.question,
            child.mode,
            child.dataset_id,
            child.dataset_digest,
            child.research_start,
            child.research_end,
            child.research_start_utc,
            child.research_end_utc,
            child.runtime_interval,
            child.runtime_periods_per_year,
            child.runtime_descriptor_digest,
            child.runtime_split_digest,
            child.market_run_contract_version,
            child.parent_run_id,
            child.seed_candidate_id,
            child.refinement_reason,
            child.provider,
            child.model,
            child.max_agent_iterations,
            child.max_experiments,
            child.max_repairs,
            child.strategy_scope.model_dump(mode="json"),
            tuple(child.planned_candidate_families),
            child.selection_objective,
            tuple(child.completion_criteria),
            child.data_authenticity,
            child.research_loop_policy,
            child.research_series_root_run_id,
            child.research_series_version,
            (
                child.research_memory.model_dump(mode="json")
                if child.research_memory is not None
                else None
            ),
            (
                child.repair_memory.model_dump(mode="json")
                if child.repair_memory is not None
                else None
            ),
        )
        if child_identity != source_identity:
            return "A Quant retry child must retain its source Run identity and runtime pins."
        return None

    def _retry_run_locked(
        self,
        *,
        run: QuantRunRecord,
        expected_row_version: int,
        reason: str,
    ) -> QuantRunRecord:
        workspace_id = run.workspace_id
        if run.row_version != expected_row_version and run.retry_child_run_id is None:
            raise version_conflict(run.id, run.row_version)
        if run.retry_child_run_id is not None:
            child = self.get_run(workspace_id=workspace_id, run_id=run.retry_child_run_id)
            relationship_error = self._retry_pair_error(run, child)
            if relationship_error is not None:
                raise invalid_state(relationship_error)
            return child
        if run.state not in {
            QuantRunState.COMPLETED,
            QuantRunState.FAILED,
            QuantRunState.CANCELLED,
        }:
            raise invalid_state("Retry requires a terminal run.")
        if run.research_loop_policy is not None:
            raise invalid_state(
                "Retry is unavailable for a bounded research series; start a new research Run."
            )
        baseline = self._workspace_mutation_baseline(workspace_id)
        child = QuantRunRecord(
            id=str(_uuid("run-retry", run.id, run.attempt_number + 1, reason)),
            workspace_id=workspace_id,
            project_id=run.project_id,
            question=run.question,
            mode=run.mode,
            attempt_number=run.attempt_number + 1,
            retry_of_run_id=run.id,
            trace_id=str(_uuid("trace", run.id, run.attempt_number + 1)),
            provider=run.provider,
            model=run.model,
            max_agent_iterations=run.max_agent_iterations,
            max_experiments=run.max_experiments,
            max_repairs=run.max_repairs,
            strategy_scope=run.strategy_scope.model_copy(deep=True),
            planned_candidate_families=list(run.planned_candidate_families),
            selection_objective=run.selection_objective,
            completion_criteria=list(run.completion_criteria),
            dataset_id=run.dataset_id,
            dataset_digest=run.dataset_digest,
            research_start=run.research_start,
            research_end=run.research_end,
            research_start_utc=run.research_start_utc,
            research_end_utc=run.research_end_utc,
            runtime_interval=run.runtime_interval,
            runtime_periods_per_year=run.runtime_periods_per_year,
            runtime_descriptor_digest=run.runtime_descriptor_digest,
            runtime_split_digest=run.runtime_split_digest,
            market_run_contract_version=run.market_run_contract_version,
            parent_run_id=run.parent_run_id,
            seed_candidate_id=run.seed_candidate_id,
            refinement_reason=run.refinement_reason,
            research_loop_policy=run.research_loop_policy,
            research_series_root_run_id=run.research_series_root_run_id,
            research_series_version=run.research_series_version,
            research_memory_contract_version=RESEARCH_MEMORY_CONTRACT_VERSION,
            research_memory=self._validated_research_memory_pin(run.research_memory).model_copy(
                deep=True
            ),
            repair_memory=(
                run.repair_memory.model_copy(deep=True) if run.repair_memory is not None else None
            ),
            data_authenticity=run.data_authenticity,
        )
        self._runs[child.id] = child
        run.retry_child_run_id = child.id
        run.row_version += 1
        run.updated_at = _utcnow()
        self._append_event(
            child,
            "run.queued",
            {
                "state": QuantRunState.QUEUED,
                "attempt_number": child.attempt_number,
                "safe_summary": "The retry was queued.",
            },
        )
        self._publish_plan(child)
        if child.mode is QuantRunMode.AUTO and child.strategy_scope.status == "supported":
            self._start_run(child, "Auto Research accepted the retry plan.")
        self._persist_workspace_or_restore(workspace_id, baseline)
        return child

    def execute_fixture_once(self, *, workspace_id: str, fixture_state: str) -> bool:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            running = [
                run
                for run in sorted(self._runs.values(), key=lambda item: item.created_at)
                if run.workspace_id == workspace_id
                and run.state is QuantRunState.RUNNING_EXPERIMENTS
            ]
            if not running:
                return False
            run = running[0]
            self._finish_run(run, fixture_state)
            self._persist_workspace(workspace_id)
            return True

    def _publish_plan(self, run: QuantRunRecord, agent_plan: QuantAgentPlan | None = None) -> None:
        seed_template: str | None = None
        if run.seed_candidate_id is not None:
            seed = self._experiments.get(run.seed_candidate_id)
            if seed is None:
                raise invalid_state("A Continue plan no longer has its selected seed candidate.")
            seed_template = seed.template
        agent_plan = _pin_seed_family_to_plan(
            agent_plan,
            seed_template=seed_template,
        )
        if agent_plan is not None and len(set(agent_plan.candidate_families)) != len(
            agent_plan.candidate_families
        ):
            raise invalid_state("The Agent plan contains duplicate candidate families.")
        summary = agent_plan.objective_summary if agent_plan else self._plan_summary(run)
        run.plan_summary = summary
        run.plan_steps = (
            [step.model_dump(mode="json") for step in agent_plan.steps]
            if agent_plan
            else self._agent_plan_steps(run.question)
        )
        if agent_plan is not None:
            run.planned_candidate_families = list(agent_plan.candidate_families)
            run.strategy_scope = agent_plan.strategy_scope.model_copy(deep=True)
            run.selection_objective = agent_plan.selection_objective
            run.completion_criteria = list(agent_plan.completion_criteria)
            run.max_experiments = agent_plan.max_experiments
            run.max_repairs = agent_plan.max_repairs
        plan_content: dict[str, Any] = {
            "objective_summary": run.plan_summary,
            "candidate_families": list(run.planned_candidate_families),
            "strategy_scope": run.strategy_scope.model_dump(mode="json"),
            "selection_objective": run.selection_objective,
            "completion_criteria": list(run.completion_criteria),
        }
        if run.research_memory_contract_version is not None and run.research_memory is not None:
            plan_content.update(
                {
                    "research_memory_contract_version": (run.research_memory_contract_version),
                    "research_memory_digest": run.research_memory.context_digest,
                }
            )
        plan_artifact = QuantArtifactRecord(
            id=str(_uuid("artifact", run.id, run.plan_revision, "plan")),
            workspace_id=run.workspace_id,
            run_id=run.id,
            ordinal=1,
            kind=QuantArtifactKind.PLAN,
            title=f"Plan revision {run.plan_revision}",
            digest=f"sha256:plan:{run.id}:{run.plan_revision}",
            content=plan_content,
        )
        self._artifacts[plan_artifact.id] = plan_artifact
        run.plan_artifact_id = plan_artifact.id
        self._append_event(
            run,
            "plan.proposed",
            {
                "state": QuantRunState.PLANNING,
                "plan_revision": run.plan_revision,
                "plan_steps": [step["title"] for step in run.plan_steps],
                "candidate_families": list(run.planned_candidate_families),
                "strategy_scope": run.strategy_scope.model_dump(mode="json"),
                "selection_objective": run.selection_objective,
                "artifact_id": plan_artifact.id,
                "safe_summary": "A plan revision was proposed for review.",
            },
        )
        self._append_event(
            run,
            "plan.awaiting_approval",
            {
                "state": QuantRunState.WAITING_PLAN_APPROVAL,
                "plan_revision": run.plan_revision,
                "safe_summary": "The plan is waiting for approval.",
            },
        )
        run.state = QuantRunState.WAITING_PLAN_APPROVAL
        run.row_version += 1
        run.updated_at = _utcnow()

    def _cross_pin_research_memory_to_plan(self, run: QuantRunRecord) -> None:
        if (
            run.research_memory_contract_version != RESEARCH_MEMORY_CONTRACT_VERSION
            or run.research_memory is None
            or run.plan_artifact_id is None
        ):
            raise invalid_state("The Run's Research Memory plan pin is incomplete.")
        artifact = self._artifacts.get(run.plan_artifact_id)
        if (
            artifact is None
            or artifact.workspace_id != run.workspace_id
            or artifact.run_id != run.id
            or artifact.kind is not QuantArtifactKind.PLAN
        ):
            raise invalid_state("The Run's Research Memory plan artifact is unavailable.")
        artifact.content["research_memory_contract_version"] = run.research_memory_contract_version
        artifact.content["research_memory_digest"] = run.research_memory.context_digest

    def _start_run(
        self,
        run: QuantRunRecord,
        reason: str | None,
        *,
        explicit_approval: bool = False,
    ) -> None:
        if run.strategy_scope.status == "unsupported":
            raise invalid_state(
                "Unsupported strategy scope cannot execute; request plan changes or cancel."
            )
        if run.strategy_scope.status == "bounded_proxy" and not explicit_approval:
            raise invalid_state("A bounded strategy proxy requires explicit plan approval.")
        run.state = QuantRunState.RUNNING_EXPERIMENTS
        run.agent_status = "waiting_next_step"
        run.approval_reason = reason
        run.row_version += 1
        run.updated_at = _utcnow()
        self._append_event(
            run,
            "plan.approved",
            {
                "state": QuantRunState.RUNNING_EXPERIMENTS,
                "plan_revision": run.plan_revision,
                "safe_summary": "The bounded Agent plan was accepted.",
            },
        )
        self._append_event(
            run,
            "run.started",
            {
                "state": QuantRunState.RUNNING_EXPERIMENTS,
                "plan_revision": run.plan_revision,
                "attempt_number": run.attempt_number,
                "safe_summary": "The autonomous research run started.",
            },
        )

    @staticmethod
    def _agent_plan_steps(question: str) -> list[dict[str, Any]]:
        lowered = question.lower()
        if any(
            token in lowered for token in ("trade", "frequent", "opportunit", "频繁", "交易机会")
        ):
            families = "RSI mean reversion, fast SMA and short breakout"
        elif any(token in lowered for token in ("mean reversion", "均值回归")):
            families = "RSI mean reversion and a short SMA control"
        elif any(token in lowered for token in ("drawdown", "回撤")):
            families = "slow SMA and long breakout drawdown controls"
        else:
            families = "simple SMA, RSI and breakout templates"
        return [
            {"key": "inspect", "title": "Inspect the pinned research context", "owner": "agent"},
            {"key": "templates", "title": f"Select from {families}", "owner": "agent"},
            {
                "key": "experiments",
                "title": "Create and backtest up to three candidates",
                "owner": "agent",
            },
            {
                "key": "compare",
                "title": "Compare completed candidates with buy and hold",
                "owner": "agent",
            },
            {
                "key": "report",
                "title": "Finish with an evidence-backed conclusion",
                "owner": "agent",
            },
        ]

    @staticmethod
    def _configured_agent_provider() -> str:
        provider = os.environ.get("POKIEQUANT_AGENT_PROVIDER", "mock").strip().lower()
        if provider in {"", "mock"}:
            return "mock"
        if provider in {"deepseek", "openai_compatible"}:
            return "deepseek"
        raise ValueError("POKIEQUANT_AGENT_PROVIDER is invalid.")

    @staticmethod
    def _configured_agent_model() -> str | None:
        if QuantStore._configured_agent_provider() != "deepseek":
            return None
        return (
            os.environ.get("POKIEQUANT_AGENT_MODEL")
            or os.environ.get("DEEPSEEK_MODEL")
            or "deepseek-v4-flash"
        ).strip() or "deepseek-v4-flash"

    def _finish_run(self, run: QuantRunRecord, fixture_state: str) -> None:
        # Import inside the fixture-only path so normal quant-agent worker code
        # never depends on the Phase 0 fixture script generator.
        from packages.contracts.quant.runtime import build_quant_script

        scenario = {
            "completed": QuantFixtureScenario.NORMAL,
            "completed_rejected_candidate": QuantFixtureScenario.NORMAL,
            "completed_no_viable_candidates": QuantFixtureScenario.NO_VIABLE,
            "failed": QuantFixtureScenario.FAILED_SAFE,
        }[fixture_state]
        for step in build_quant_script(run_id=run.id, scenario=scenario):
            # The canonical script is the only worker sequence. Candidate-scoped
            # failures therefore remain repair events and never become run.failed.
            run.state = step.run_state
            payload = step.payload.model_dump(mode="json", exclude_none=True)
            if step.event_type.value == "run.failed":
                payload.setdefault("reason_code", "fixture_worker_failed_safe")
                run.failure_reason = payload.get("safe_summary", "Fixture worker stopped safely.")
            self._append_event(run, step.event_type.value, payload)
            if step.artifact is not None:
                ordinal = 1 + sum(
                    artifact.run_id == run.id for artifact in self._artifacts.values()
                )
                self._artifacts[step.artifact.artifact_id] = QuantArtifactRecord(
                    id=step.artifact.artifact_id,
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=ordinal,
                    kind=step.artifact.kind,
                    title=step.artifact.label,
                    digest=step.artifact.digest,
                )
            if step.experiment is not None:
                existing = self._experiments.get(step.experiment.experiment_id)
                verdict = {
                    QuantCandidateVerdict.PROMISING: QuantExperimentVerdict.VIABLE,
                    QuantCandidateVerdict.REJECTED: QuantExperimentVerdict.REJECTED,
                    QuantCandidateVerdict.INCONCLUSIVE: QuantExperimentVerdict.NOT_VIABLE,
                    QuantCandidateVerdict.INVALID: QuantExperimentVerdict.REJECTED,
                    None: QuantExperimentVerdict.NOT_VIABLE,
                }[step.experiment.verdict]
                self._experiments[step.experiment.experiment_id] = QuantExperimentRecord(
                    id=step.experiment.experiment_id,
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=(
                        existing.ordinal
                        if existing is not None
                        else 1
                        + sum(
                            experiment.run_id == run.id for experiment in self._experiments.values()
                        )
                    ),
                    name=step.experiment.candidate_name,
                    hypothesis="Deterministic synthetic fixture hypothesis.",
                    verdict=verdict,
                    summary="Canonical fixture runtime result; no real backtest occurred.",
                )
        if run.state is QuantRunState.WAITING_FOR_REVIEW:
            # The legacy Phase 0 API fixture carries a pre-recorded synthetic
            # review. The worker script still stops at review.required; this
            # repository-owned projection records the reviewed terminal state.
            run.state = QuantRunState.COMPLETED
            self._append_event(
                run,
                "run.completed",
                {
                    "state": QuantRunState.COMPLETED,
                    "plan_revision": run.plan_revision,
                    "attempt_number": run.attempt_number,
                    "reason_code": "synthetic_review_fixture_complete",
                    "safe_summary": "The synthetic reviewed run completed.",
                },
            )
        run.row_version += 1
        run.updated_at = _utcnow()

    def _fixture_outputs(
        self, run: QuantRunRecord, fixture_state: str
    ) -> tuple[list[QuantExperimentRecord], list[QuantArtifactRecord]]:
        report = QuantArtifactRecord(
            id=str(_uuid("artifact", run.id, run.plan_revision, fixture_state, "report")),
            workspace_id=run.workspace_id,
            run_id=run.id,
            ordinal=2,
            kind=QuantArtifactKind.RESEARCH_REPORT,
            title=f"fixture-{fixture_state}-report",
            digest=f"sha256:fixture-{fixture_state}-report",
        )
        if fixture_state == "completed_no_viable_candidates":
            experiments = [
                QuantExperimentRecord(
                    id=str(_uuid("experiment", run.id, "no-viable-1")),
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=1,
                    name="candidate-1",
                    hypothesis="No viable candidate expected.",
                    verdict=QuantExperimentVerdict.NOT_VIABLE,
                    summary="Fixture state excludes viable outputs.",
                ),
                QuantExperimentRecord(
                    id=str(_uuid("experiment", run.id, "no-viable-2")),
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=2,
                    name="candidate-2",
                    hypothesis="No viable candidate expected.",
                    verdict=QuantExperimentVerdict.NOT_VIABLE,
                    summary="Fixture state excludes viable outputs.",
                ),
            ]
            return experiments, [report]
        if fixture_state == "completed_rejected_candidate":
            experiments = [
                QuantExperimentRecord(
                    id=str(_uuid("experiment", run.id, "rejected")),
                    workspace_id=run.workspace_id,
                    run_id=run.id,
                    ordinal=1,
                    name="candidate-1",
                    hypothesis="Rejected candidate retained for auditability.",
                    verdict=QuantExperimentVerdict.REJECTED,
                    summary="Rejected candidate retained.",
                )
            ]
            return experiments, [report]
        experiments = [
            QuantExperimentRecord(
                id=str(_uuid("experiment", run.id, "viable")),
                workspace_id=run.workspace_id,
                run_id=run.id,
                ordinal=1,
                name="candidate-1",
                hypothesis="Fixture completion produced one viable candidate.",
                verdict=QuantExperimentVerdict.VIABLE,
                summary="Deterministic fixture success.",
                template="sma_crossover",
                parameters={"fast_window": 20, "slow_window": 50},
                metrics={
                    "annualized_return_pct": 11.8,
                    "maximum_drawdown_pct": -8.4,
                    "sharpe_ratio": 1.24,
                    "trade_count": 14,
                },
            ),
            QuantExperimentRecord(
                id=str(_uuid("experiment", run.id, "rejected")),
                workspace_id=run.workspace_id,
                run_id=run.id,
                ordinal=2,
                name="candidate-2",
                hypothesis="Rejected candidate retained for auditability.",
                verdict=QuantExperimentVerdict.REJECTED,
                summary="Rejected candidate retained.",
                template="sma_crossover",
                parameters={"fast_window": 50, "slow_window": 100},
                metrics={
                    "annualized_return_pct": 6.2,
                    "maximum_drawdown_pct": -13.1,
                    "sharpe_ratio": 0.71,
                    "trade_count": 8,
                },
            ),
        ]
        report.content = {
            "research_goal": run.question,
            "dataset": self.agent_dataset_summary(run),
            "benchmark": self.agent_benchmark_summary(run),
            "selected_candidate_id": experiments[1].id,
            "conclusion": "The retained fixture candidate requires further validation.",
            "next_step": "review_holdout_evidence",
            "generalization": {
                "status": "inconclusive",
                "reason": "The deterministic fixture retains no separate holdout metrics.",
                "selected_candidate_id": experiments[1].id,
                "split": self._agent_split(run)[3],
            },
            "limitations": [
                "This deterministic fixture is not real market data.",
                "No live execution was evaluated.",
            ],
        }
        return experiments, [report]

    def _append_event(
        self, run: QuantRunRecord, event_type: str, payload: dict[str, Any]
    ) -> QuantEventRecord:
        sequence = run.latest_sequence + 1
        event = QuantEventRecord(
            id=str(_uuid("event", run.id, sequence, event_type)),
            workspace_id=run.workspace_id,
            run_id=run.id,
            sequence=sequence,
            event_type=event_type,
            payload=payload,
            trace_id=str(_uuid("trace", run.id, sequence, event_type)),
            occurred_at=_utcnow(),
            data_authenticity=run.data_authenticity,
        )
        self._events.setdefault(run.id, []).append(event)
        run.latest_sequence = sequence
        return event

    def _plan_summary(self, run: QuantRunRecord) -> str:
        focus = self._agent_plan_steps(run.question)[1]["title"]
        return _text(
            "Bounded autonomous plan for",
            run.question,
            f"Focus: {focus}.",
            f"Revision {run.plan_revision}.",
        )

    def agent_dataset_summary(self, run: QuantRunRecord) -> dict[str, Any]:
        projection = self.runtime_projection(run)
        runtime = projection.descriptor
        split = projection.split.metadata
        market_record = projection.market_record
        if market_record is not None:
            training_split = {
                "method": split["method"],
                "rule_version": split["rule_version"],
                "train_bar_count": split["train_bar_count"],
                "train_start": split["train_start"],
                "train_end": split["train_end"],
                "dataset_id": split["dataset_id"],
                "dataset_digest": split["dataset_digest"],
                "interval": split["interval"],
                "periods_per_year": split["periods_per_year"],
            }
            return {
                "dataset_id": runtime.dataset_id,
                "symbol": runtime.symbol,
                "interval": runtime.interval.value,
                "periods_per_year": runtime.periods_per_year,
                "bars": len(runtime.bars),
                "start": runtime.coverage_start_utc.isoformat(),
                "end": runtime.coverage_end_utc.isoformat(),
                "utc_coverage": {
                    "start": runtime.coverage_start_utc.isoformat(),
                    "end": runtime.coverage_end_utc.isoformat(),
                },
                "digest": runtime.dataset_digest,
                "runtime_descriptor_digest": runtime.descriptor_digest,
                "sealed_split_digest": projection.split.seal_digest,
                "authenticity": runtime.data_authenticity.value,
                "source_metadata": market_record.evidence.model_dump(mode="json"),
                "data_quality": market_record.quality.model_dump(mode="json"),
                "evaluation_partition": "train",
                "split": training_split,
            }
        dataset = projection.daily_dataset
        if dataset is None:  # pragma: no cover - runtime projection is a closed union
            raise invalid_state("The daily runtime projection is incomplete.")
        record = projection.daily_record
        return {
            "dataset_id": dataset.dataset_id,
            "symbol": dataset.symbol,
            "interval": dataset.interval.value,
            "bars": len(self.bars_for_run(run)),
            "start": run.research_start.isoformat(),
            "end": run.research_end.isoformat(),
            "digest": dataset.digest,
            "authenticity": (
                record.data_authenticity.value if record is not None else "synthetic_fixture"
            ),
            "source_metadata": (
                record.source_metadata.model_dump(mode="json")
                if record is not None
                else {
                    "kind": "synthetic_fixture",
                    "generator": "deterministic-weekday-generator-v2",
                }
            ),
            "data_quality": (
                _dataset_quality(record).model_dump(mode="json") if record is not None else None
            ),
            "evaluation_partition": "train",
            "split": split,
        }

    def agent_benchmark_summary(self, run: QuantRunRecord) -> dict[str, Any]:
        runtime = self._runtime_descriptor(run)
        result = backtest_buy_and_hold(
            _runtime_split(runtime).training_bars,
            BASELINE_EXECUTION,
            cadence=runtime.cadence,
        )
        return self._metrics_projection(result.metrics)

    @staticmethod
    def agent_templates() -> list[dict[str, Any]]:
        return [
            {
                "name": "sma_crossover",
                "description": (
                    "Long when the fast moving average is above the slow moving average."
                ),
                "parameters": {
                    "fast_window": {"type": "integer", "minimum": 2, "maximum": 150},
                    "slow_window": {"type": "integer", "minimum": 10, "maximum": 300},
                },
            },
            {
                "name": "rsi_mean_reversion",
                "description": "Enter after oversold RSI and exit after recovery.",
                "parameters": {
                    "period": {"type": "integer", "minimum": 2, "maximum": 100},
                    "entry_threshold": {"type": "number", "minimum": 10, "maximum": 45},
                    "exit_threshold": {"type": "number", "minimum": 45, "maximum": 80},
                },
            },
            {
                "name": "breakout",
                "description": "Enter when price breaks above a trailing range.",
                "parameters": {
                    "lookback_window": {"type": "integer", "minimum": 5, "maximum": 250}
                },
            },
        ]

    @staticmethod
    def agent_candidate_summary(candidate: QuantExperimentRecord) -> dict[str, Any]:
        return {
            "candidate_id": candidate.id,
            "name": candidate.name,
            "template": candidate.template,
            "hypothesis": candidate.hypothesis,
            "parameters": candidate.parameters,
            "state": candidate.state,
            "repair_count": candidate.repair_count,
            "verdict": candidate.verdict.value,
            "metrics": candidate.metrics or None,
            "latest_observation": candidate.latest_observation,
            "parent_experiment_id": candidate.parent_experiment_id,
            "feedback_artifact_id": candidate.feedback_artifact_id,
        }

    def agent_context_data(self, *, workspace_id: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            candidates = sorted(
                (
                    item
                    for item in self._experiments.values()
                    if item.run_id == run.id and item.template != "fixture"
                ),
                key=lambda item: item.ordinal,
            )
            events = self._events.get(run.id, [])[-15:]
            latest_observation_by_action: dict[str, dict[str, Any]] = {}
            for event in self._events.get(run.id, []):
                action = event.payload.get("action")
                if event.event_type in {"tool.completed", "tool.failed"} and isinstance(
                    action, str
                ):
                    observation: dict[str, Any] = {
                        "action": action,
                        "success": event.payload.get("success"),
                        "safe_summary": event.payload.get("safe_summary"),
                        "error_code": event.payload.get("error_code"),
                        "call_fingerprint": event.payload.get("call_fingerprint"),
                        "repair": event.payload.get("tool_repair"),
                    }
                    if (
                        event.event_type == "tool.failed"
                        and observation.get("error_code") == "INVALID_ARGUMENTS"
                        and isinstance(observation.get("repair"), dict)
                        and isinstance(observation.get("call_fingerprint"), str)
                    ):
                        rejected_arguments = self.rejected_arguments_for_repair(
                            workspace_id=workspace_id,
                            run_id=run.id,
                            call_fingerprint=observation["call_fingerprint"],
                        )
                        if rejected_arguments is not None:
                            observation["rejected_arguments"] = rejected_arguments
                    latest_observation_by_action[action] = observation
            observations = list(latest_observation_by_action.values())
            refinement: dict[str, Any] | None = None
            if run.parent_run_id and run.seed_candidate_id:
                parent = self.get_run(workspace_id=workspace_id, run_id=run.parent_run_id)
                seed = self._experiments.get(run.seed_candidate_id)
                if seed is not None and seed.run_id == parent.id:
                    refinement = {
                        "parent_run_id": parent.id,
                        "seed_candidate_id": seed.id,
                        "refinement_reason": run.refinement_reason,
                        "source_research_goal": parent.question,
                        "seed_candidate": {
                            "name": seed.name,
                            "template": seed.template,
                            "parameters": seed.parameters,
                        },
                    }
            iteration_feedback = next(
                (
                    artifact.content
                    for artifact in self.artifacts_for_run(workspace_id=workspace_id, run_id=run.id)
                    if artifact.kind is QuantArtifactKind.ITERATION_FEEDBACK
                ),
                None,
            )
            latest_comparison = self._latest_training_comparison(run)
            research_series = self._research_series_context(run)
            return {
                "run_id": run.id,
                "project_id": run.project_id,
                "research_goal": run.question,
                "mode": run.mode.value,
                "run_state": run.state.value,
                "dataset_summary": self.agent_dataset_summary(run),
                "benchmark_summary": self.agent_benchmark_summary(run),
                "available_templates": self.agent_templates(),
                "candidates": [self.agent_candidate_summary(item) for item in candidates],
                "budget": {
                    "max_iterations": run.max_agent_iterations,
                    "used_iterations": run.agent_iteration,
                    "remaining_iterations": max(0, run.max_agent_iterations - run.agent_iteration),
                    "max_experiments": run.max_experiments,
                    "used_experiments": run.used_experiments,
                    "remaining_experiments": max(0, run.max_experiments - run.used_experiments),
                    "max_repairs": run.max_repairs,
                    "used_repairs": run.used_repairs,
                    "remaining_repairs": max(0, run.max_repairs - run.used_repairs),
                },
                "recent_events": [
                    {
                        "sequence": event.sequence,
                        "event_type": event.event_type,
                        "safe_summary": event.payload.get("safe_summary"),
                    }
                    for event in events
                ],
                "recent_observations": observations,
                "plan_summary": run.plan_summary,
                "approved_plan": {
                    "candidate_families": list(run.planned_candidate_families),
                    "strategy_scope": run.strategy_scope.model_dump(mode="json"),
                    "selection_objective": run.selection_objective,
                    "completion_criteria": list(run.completion_criteria),
                },
                "final_conclusion": run.final_conclusion,
                "refinement": refinement,
                "iteration_feedback": iteration_feedback,
                "latest_comparison": latest_comparison,
                "research_series": (
                    research_series.model_dump(mode="json") if research_series is not None else None
                ),
                "research_memory": self._validated_research_memory_pin(
                    run.research_memory
                ).model_dump(mode="json"),
            }

    def _research_series_context(self, run: QuantRunRecord) -> QuantResearchSeriesContext | None:
        policy = run.research_loop_policy
        if policy is None:
            return None
        if run.research_series_root_run_id is None or run.research_series_version is None:
            raise invalid_state("The research series identity is incomplete.")
        root = self._runs.get(run.research_series_root_run_id)
        if root is None:
            raise invalid_state("The research series root is unavailable.")
        remaining = max(0, policy.max_versions - run.research_series_version)
        if root.research_series_child_run_id is not None:
            remaining = 0
        memory = self._validated_research_memory_pin(run.research_memory)
        ancestor_keys = list(memory.tested_candidate_keys)
        ancestor_candidates: list[dict[str, object]] = [
            {
                "candidate_key": candidate.candidate_key,
                "template": candidate.template,
                "parameters": _json_value(candidate.parameters),
            }
            for candidate in memory.candidates
        ]
        allowed_actions: list[Literal["finish_without_follow_up", "precommit_one_refinement"]] = [
            "finish_without_follow_up"
        ]
        blocking_reasons: list[str] = []
        if (
            policy.follow_up_mode == "one_train_only_follow_up"
            and remaining > 0
            and run.mode is QuantRunMode.AUTO
        ):
            allowed_actions.append("precommit_one_refinement")
        else:
            blocking_reasons.append("No automatic follow-up version remains in this policy.")
        return QuantResearchSeriesContext(
            root_run_id=run.research_series_root_run_id,
            current_run_id=run.id,
            version_number=run.research_series_version,
            remaining_versions=remaining,
            allowed_actions=allowed_actions,
            blocking_reasons=blocking_reasons,
            ancestor_candidate_keys=ancestor_keys,
            ancestor_candidates=ancestor_candidates,
            policy_digest=research_loop_policy_digest(policy),
        )

    # Serializers
    def to_project_response(self, project: QuantProjectRecord) -> dict[str, Any]:
        return {
            "id": project.id,
            "workspace_id": project.workspace_id,
            "row_version": project.row_version,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "name": project.name,
            "objective": project.objective,
            "status": project.status,
            "data_authenticity": project.data_authenticity,
        }

    def to_run_response(self, run: QuantRunRecord) -> dict[str, Any]:
        return {
            "id": run.id,
            "workspace_id": run.workspace_id,
            "row_version": run.row_version,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "project_id": run.project_id,
            "dataset_id": run.dataset_id,
            "dataset_digest": run.dataset_digest,
            "research_start": run.research_start,
            "research_end": run.research_end,
            "state": run.state,
            "mode": run.mode,
            "question": run.question,
            "plan_revision": run.plan_revision,
            "attempt_number": run.attempt_number,
            "trace_id": run.trace_id,
            "latest_sequence": run.latest_sequence,
            "retry_of_run_id": run.retry_of_run_id,
            "parent_run_id": run.parent_run_id,
            "seed_candidate_id": run.seed_candidate_id,
            "refinement_reason": run.refinement_reason,
            "failure_reason": run.failure_reason,
            "agent_iteration": run.agent_iteration,
            "agent_status": run.agent_status,
            "max_agent_iterations": run.max_agent_iterations,
            "max_experiments": run.max_experiments,
            "max_repairs": run.max_repairs,
            "used_experiments": run.used_experiments,
            "used_repairs": run.used_repairs,
            "last_action": run.last_action,
            "last_observation": run.last_observation,
            "final_conclusion": run.final_conclusion,
            "provider": run.provider,
            "model": run.model,
            "data_authenticity": run.data_authenticity,
        }

    def to_market_run_response(self, run: QuantRunRecord) -> dict[str, Any]:
        self._require_public_market_run(run)
        descriptor = self._runtime_descriptor(run)
        if (
            run.research_start_utc is None
            or run.research_end_utc is None
            or run.runtime_split_digest is None
        ):  # pragma: no cover - the public gate validates the complete pin set
            raise invalid_state("The public market Run is missing its pinned runtime identity.")
        series_context = self._research_series_context(run)
        return {
            "schema_version": QUANT_MARKET_RUN_CONTRACT_VERSION,
            "id": run.id,
            "workspace_id": run.workspace_id,
            "row_version": run.row_version,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "project_id": run.project_id,
            "dataset_id": descriptor.dataset_id,
            "dataset_digest": descriptor.dataset_digest,
            "symbol": descriptor.symbol,
            "interval": descriptor.interval.value,
            "periods_per_year": descriptor.periods_per_year,
            "research_start_utc": run.research_start_utc,
            "research_end_utc": run.research_end_utc,
            "runtime_descriptor_digest": descriptor.descriptor_digest,
            "sealed_split_digest": run.runtime_split_digest,
            "state": run.state,
            "mode": run.mode,
            "question": run.question,
            "plan_revision": run.plan_revision,
            "attempt_number": run.attempt_number,
            "retry_of_run_id": run.retry_of_run_id,
            "parent_run_id": run.parent_run_id,
            "seed_candidate_id": run.seed_candidate_id,
            "refinement_reason": run.refinement_reason,
            "research_loop": (
                run.research_loop_policy.model_dump(mode="json")
                if run.research_loop_policy is not None
                else None
            ),
            "research_series": (
                series_context.model_dump(mode="json") if series_context is not None else None
            ),
            "latest_sequence": run.latest_sequence,
            "trace_id": run.trace_id,
            "failure_reason": run.failure_reason,
            "agent_iteration": run.agent_iteration,
            "agent_status": run.agent_status,
            "max_agent_iterations": run.max_agent_iterations,
            "max_experiments": run.max_experiments,
            "max_repairs": run.max_repairs,
            "used_experiments": run.used_experiments,
            "used_repairs": run.used_repairs,
            "last_action": run.last_action,
            "last_observation": run.last_observation,
            "final_conclusion": run.final_conclusion,
            "provider": run.provider,
            "model": run.model,
            "data_authenticity": run.data_authenticity,
        }

    @staticmethod
    def to_dataset_response(record: QuantDatasetRecord) -> dict[str, Any]:
        dataset = record.dataset
        return {
            "dataset_id": record.id,
            "workspace_id": record.workspace_id,
            "name": record.name,
            "symbol": dataset.symbol,
            "interval": dataset.interval.value,
            "covered_start": dataset.covered_start,
            "covered_end": dataset.covered_end,
            "bar_count": len(dataset.bars),
            "schema_version": dataset.schema_version,
            "parser_version": record.parser_version,
            "digest": dataset.digest,
            "source_metadata": record.source_metadata.model_dump(mode="json"),
            "data_quality": _dataset_quality(record).model_dump(mode="json"),
            "data_authenticity": record.data_authenticity,
            "created_at": record.created_at,
        }

    @staticmethod
    def to_market_dataset_v2_response(record: QuantMarketDatasetV2Record) -> dict[str, Any]:
        dataset = record.dataset
        try:
            descriptor = _market_runtime_descriptor(record)
        except ValueError:
            research_eligible = False
        else:
            research_eligible = _market_research_sufficiency(
                interval=dataset.interval,
                periods_per_year=descriptor.periods_per_year,
                bar_count=len(descriptor.bars),
                coverage_start_utc=descriptor.coverage_start_utc,
                coverage_end_utc=descriptor.coverage_end_utc,
            ).eligible
        return {
            "dataset_id": record.id,
            "workspace_id": record.workspace_id,
            "name": record.name,
            "symbol": dataset.symbol,
            "interval": dataset.interval,
            "covered_start": dataset.covered_start,
            "covered_end": dataset.covered_end,
            "bar_count": len(dataset.bars),
            "market_calendar": dataset.market_calendar,
            "market_session": dataset.market_session,
            "time_zone": dataset.time_zone,
            "periods_per_year": dataset.periods_per_year,
            "schema_version": dataset.schema_version,
            "digest": dataset.digest,
            "record_digest": record.record_digest,
            "evidence": record.evidence.model_dump(mode="json"),
            "quality": record.quality.model_dump(mode="json"),
            "research_eligible": research_eligible,
            "data_authenticity": record.data_authenticity,
            "created_at": record.created_at,
        }

    def to_artifact_response(self, artifact: QuantArtifactRecord) -> dict[str, Any]:
        return {
            "id": artifact.id,
            "workspace_id": artifact.workspace_id,
            "run_id": artifact.run_id,
            "ordinal": artifact.ordinal,
            "kind": artifact.kind,
            "title": artifact.title,
            "digest": artifact.digest,
            "review_status": artifact.review_status,
            "created_at": artifact.created_at,
            "data_authenticity": artifact.data_authenticity,
        }

    def to_experiment_response(self, experiment: QuantExperimentRecord) -> dict[str, Any]:
        return {
            "id": experiment.id,
            "workspace_id": experiment.workspace_id,
            "run_id": experiment.run_id,
            "ordinal": experiment.ordinal,
            "name": experiment.name,
            "hypothesis": experiment.hypothesis,
            "verdict": experiment.verdict,
            "summary": experiment.summary,
            "template": experiment.template,
            "parameters": experiment.parameters,
            "state": experiment.state,
            "metrics": experiment.metrics,
            "repair_count": experiment.repair_count,
            "candidate_key": experiment.candidate_key,
            "parent_experiment_id": experiment.parent_experiment_id,
            "created_at": experiment.created_at,
            "data_authenticity": experiment.data_authenticity,
        }

    def events_for_run(
        self, *, workspace_id: str, run_id: str, after_sequence: int = 0
    ) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            run = self.get_run(workspace_id=workspace_id, run_id=run_id)
            return [
                event.to_contract()
                for event in self._events.get(run.id, [])
                if event.sequence > after_sequence
            ]

    def workspace_ids(self) -> list[str]:
        with self._lock:
            configured = os.environ.get("GLINT_WORKSPACE_ID")
            bind = self._session_factory.kw.get("bind")
            if configured:
                self._ensure_workspace_loaded(configured)
            elif bind is not None and bind.dialect.name == "sqlite":
                with self._session_factory() as db:
                    for workspace_id in db.scalars(select(QuantRepositoryState.workspace_id)):
                        self._ensure_workspace_loaded(workspace_id)
            workspaces = {project.workspace_id for project in self._projects.values()}
            workspaces.update(run.workspace_id for run in self._runs.values())
            return sorted(workspaces)

    def latest_sequence(self, *, workspace_id: str, run_id: str) -> int:
        return self.get_run(workspace_id=workspace_id, run_id=run_id).latest_sequence

    def artifacts_for_run(self, *, workspace_id: str, run_id: str) -> list[QuantArtifactRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            self.get_run(workspace_id=workspace_id, run_id=run_id)
            return [artifact for artifact in self._artifacts.values() if artifact.run_id == run_id]

    def experiments_for_run(self, *, workspace_id: str, run_id: str) -> list[QuantExperimentRecord]:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            self.get_run(workspace_id=workspace_id, run_id=run_id)
            return [item for item in self._experiments.values() if item.run_id == run_id]

    def get_artifact(self, *, workspace_id: str, artifact_id: str) -> QuantArtifactRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            artifact = self._artifacts.get(artifact_id)
            if artifact is None or artifact.workspace_id != workspace_id:
                raise not_found("QuantArtifact")
            return artifact

    def get_experiment(self, *, workspace_id: str, experiment_id: str) -> QuantExperimentRecord:
        with self._lock:
            self._ensure_workspace_loaded(workspace_id)
            experiment = self._experiments.get(experiment_id)
            if experiment is None or experiment.workspace_id != workspace_id:
                raise not_found("QuantExperiment")
            return experiment


def get_quant_store() -> QuantStore:
    return QuantStore()


def reset_quant_store() -> None:
    from services.api.app.modules.quant.snapshot import reset_workspace_fixtures

    reset_workspace_fixtures()
