"""Database-rebuilt bounded context for one Quant agent decision."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from ..base import ContractModel, Digest, NonEmptyString, VersionString
from .agent import QuantStrategyScopeDecision
from .series import QuantResearchSeriesContext

_RFC3339_UTC_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)


def _require_strict_utc_timestamp(value: object) -> object:
    if isinstance(value, datetime):
        offset = value.utcoffset()
        if offset is None or offset != UTC.utcoffset(value):
            raise ValueError("timestamp must use the UTC offset")
        return value
    if not isinstance(value, str) or _RFC3339_UTC_PATTERN.fullmatch(value) is None:
        raise ValueError("timestamp must be an RFC3339 UTC value")
    return value


class QuantAgentBudget(ContractModel):
    max_iterations: int = Field(ge=0)
    used_iterations: int = Field(ge=0)
    remaining_iterations: int = Field(ge=0)
    max_experiments: int = Field(ge=0)
    used_experiments: int = Field(ge=0)
    remaining_experiments: int = Field(ge=0)
    max_repairs: int = Field(ge=0)
    used_repairs: int = Field(ge=0)
    remaining_repairs: int = Field(ge=0)


class QuantAgentCandidateContext(ContractModel):
    candidate_id: str
    name: str
    template: str
    hypothesis: str
    parameters: dict[str, int | float | str | bool]
    state: str
    repair_count: int
    verdict: str | None
    metrics: dict[str, float | int | str | bool] | None
    latest_observation: str | None
    parent_experiment_id: str | None = None
    feedback_artifact_id: str | None = None


class QuantAgentComparisonCandidateEvidence(ContractModel):
    """Only the evidence required for one closed final-selection decision."""

    candidate_id: NonEmptyString = Field(max_length=128)
    trade_count: int = Field(ge=0)
    walk_forward_pass_folds: int = Field(ge=0)
    pass_regime_labels: list[NonEmptyString] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_regimes(self) -> QuantAgentComparisonCandidateEvidence:
        if len(set(self.pass_regime_labels)) != len(self.pass_regime_labels):
            raise ValueError("pass_regime_labels must be unique")
        return self


class QuantAgentComparisonContext(ContractModel):
    """The latest persisted training comparison with bounded train-only evidence."""

    artifact_id: NonEmptyString = Field(max_length=200)
    candidate_ids: list[NonEmptyString] = Field(min_length=1, max_length=100)
    ranking: list[NonEmptyString] = Field(min_length=1, max_length=100)
    candidates: list[QuantAgentComparisonCandidateEvidence] = Field(
        default_factory=list, max_length=100
    )


class QuantExecutablePlanContext(ContractModel):
    """The approved plan policy that constrains subsequent Agent actions."""

    candidate_families: list[Literal["sma_crossover", "rsi_mean_reversion", "breakout"]] = Field(
        max_length=3
    )
    strategy_scope: QuantStrategyScopeDecision
    selection_objective: Literal["risk_adjusted_return", "total_return", "drawdown_control"]
    completion_criteria: list[NonEmptyString] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_policy(self) -> QuantExecutablePlanContext:
        if len(set(self.candidate_families)) != len(self.candidate_families):
            raise ValueError("candidate_families must be unique")
        if self.strategy_scope.status == "unsupported":
            if self.candidate_families:
                raise ValueError("unsupported scope cannot approve candidate families")
        elif not self.candidate_families:
            raise ValueError("supported and bounded_proxy scope require candidate families")
        if any(item != item.strip() for item in self.completion_criteria):
            raise ValueError("completion_criteria must contain trimmed text")
        return self


class QuantAgentMarketUtcCoverage(ContractModel):
    """Pinned UTC coverage for a v2 runtime dataset."""

    start: AwareDatetime
    end: AwareDatetime

    _strict_start = field_validator("start", mode="before")(_require_strict_utc_timestamp)
    _strict_end = field_validator("end", mode="before")(_require_strict_utc_timestamp)

    @model_validator(mode="after")
    def validate_order(self) -> QuantAgentMarketUtcCoverage:
        if self.start > self.end:
            raise ValueError("UTC dataset coverage must be ordered.")
        return self


class QuantAgentMarketQuality(ContractModel):
    """The accepted cadence-quality result visible to an Agent decision."""

    status: Literal["accepted"]
    cadence_gap_count: Literal[0]
    normalization_note: NonEmptyString = Field(max_length=1_000)


class QuantAgentMarketTrainingPartition(ContractModel):
    """Train-only split summary; sealed holdout boundaries stay out of Agent context."""

    method: Literal["chronological"]
    rule_version: VersionString
    train_bar_count: int = Field(ge=1)
    train_start: AwareDatetime
    train_end: AwareDatetime
    dataset_id: NonEmptyString = Field(max_length=200)
    dataset_digest: Digest
    interval: Literal["1h", "4h", "1D"]
    periods_per_year: int = Field(ge=1, le=10_000)

    _strict_train_start = field_validator("train_start", mode="before")(
        _require_strict_utc_timestamp
    )
    _strict_train_end = field_validator("train_end", mode="before")(_require_strict_utc_timestamp)

    @model_validator(mode="after")
    def validate_order(self) -> QuantAgentMarketTrainingPartition:
        if self.train_start > self.train_end:
            raise ValueError("The train-only partition must be ordered.")
        return self


class QuantAgentMarketDatasetSummary(ContractModel):
    """Strict v2 dataset summary consumed by the bounded Agent worker."""

    dataset_id: NonEmptyString = Field(max_length=200)
    symbol: NonEmptyString = Field(max_length=32)
    interval: Literal["1h", "4h", "1D"]
    periods_per_year: int = Field(ge=1, le=10_000)
    bars: int = Field(ge=1)
    start: AwareDatetime
    end: AwareDatetime
    utc_coverage: QuantAgentMarketUtcCoverage
    digest: Digest
    runtime_descriptor_digest: Digest
    sealed_split_digest: Digest
    authenticity: str
    source_metadata: dict[str, object]
    data_quality: QuantAgentMarketQuality
    evaluation_partition: Literal["train"]
    split: QuantAgentMarketTrainingPartition

    _strict_start = field_validator("start", mode="before")(_require_strict_utc_timestamp)
    _strict_end = field_validator("end", mode="before")(_require_strict_utc_timestamp)

    @model_validator(mode="after")
    def validate_pinned_identity(self) -> QuantAgentMarketDatasetSummary:
        valid_periods = {
            "1h": {8_760},
            "4h": {2_190},
            "1D": {252, 365},
        }
        if self.periods_per_year not in valid_periods[self.interval]:
            raise ValueError("The interval and periods-per-year pair is not supported.")
        if self.start != self.utc_coverage.start or self.end != self.utc_coverage.end:
            raise ValueError("Top-level UTC range must match utc_coverage.")
        if self.start > self.end:
            raise ValueError("The market dataset range must be ordered.")
        if not (self.start <= self.split.train_start <= self.split.train_end <= self.end):
            raise ValueError("The train-only partition must stay inside UTC coverage.")
        if self.split.train_bar_count > self.bars:
            raise ValueError("The train-only partition cannot contain more bars than the dataset.")
        if (
            self.dataset_id != self.split.dataset_id
            or self.digest != self.split.dataset_digest
            or self.interval != self.split.interval
            or self.periods_per_year != self.split.periods_per_year
        ):
            raise ValueError("The train-only partition must match the pinned dataset identity.")
        return self


_LEGACY_DAILY_SUMMARY_KEYS = {
    "dataset_id",
    "symbol",
    "interval",
    "bars",
    "start",
    "end",
    "digest",
    "authenticity",
    "source_metadata",
    "data_quality",
    "evaluation_partition",
    "split",
}
_LEGACY_DAILY_SPLIT_KEYS = {
    "method",
    "rule_version",
    "train_bar_count",
    "holdout_bar_count",
    "train_start",
    "train_end",
    "holdout_start",
    "holdout_end",
    "cutoff_date",
    "dataset_id",
    "dataset_digest",
}
_V2_DATASET_SUMMARY_KEYS = {
    "periods_per_year",
    "utc_coverage",
    "runtime_descriptor_digest",
    "sealed_split_digest",
}
_SEALED_EVIDENCE_KEYS = {"holdout", "generalization", "validation"}


def _is_iso_date(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_legacy_daily_dataset_summary(value: dict[str, object]) -> bool:
    split = value.get("split")
    return (
        set(value) == _LEGACY_DAILY_SUMMARY_KEYS
        and value.get("interval") == "1D"
        and value.get("evaluation_partition") == "train"
        and _is_iso_date(value.get("start"))
        and _is_iso_date(value.get("end"))
        and isinstance(split, dict)
        and set(split) == _LEGACY_DAILY_SPLIT_KEYS
        and _is_iso_date(split.get("train_start"))
        and _is_iso_date(split.get("train_end"))
        and _is_iso_date(split.get("holdout_start"))
        and _is_iso_date(split.get("holdout_end"))
        and _is_iso_date(split.get("cutoff_date"))
    )


def _has_v2_dataset_summary_signal(value: dict[str, object]) -> bool:
    if _is_legacy_daily_dataset_summary(value):
        return False
    split = value.get("split")
    has_timestamp_range = any(
        isinstance(value.get(field), str) and "T" in str(value[field]) for field in ("start", "end")
    )
    has_split_signal = isinstance(split, dict) and (
        bool({"interval", "periods_per_year"}.intersection(split))
        or bool(_SEALED_EVIDENCE_KEYS.intersection(split))
        or any(
            isinstance(split.get(field), str) and "T" in str(split[field])
            for field in ("train_start", "train_end")
        )
    )
    return (
        value.get("interval") in {"1h", "4h"}
        or value.get("evaluation_partition") == "train"
        or bool(_V2_DATASET_SUMMARY_KEYS.intersection(value))
        or bool(_SEALED_EVIDENCE_KEYS.intersection(value))
        or has_timestamp_range
        or has_split_signal
    )


class QuantRefinementSeedCandidate(ContractModel):
    """Trusted, strategy-only context retained from a parent run."""

    name: NonEmptyString = Field(max_length=200)
    template: NonEmptyString = Field(max_length=100)
    parameters: dict[str, int | float | str | bool] = Field(min_length=1)


class QuantRefinementSeedContext(ContractModel):
    """Lineage context that deliberately excludes parent evaluation evidence."""

    parent_run_id: NonEmptyString = Field(max_length=200)
    seed_candidate_id: NonEmptyString = Field(max_length=200)
    refinement_reason: NonEmptyString = Field(max_length=2_000)
    source_research_goal: NonEmptyString = Field(max_length=4_000)
    seed_candidate: QuantRefinementSeedCandidate


class QuantResearchMemoryCandidate(ContractModel):
    """One prior strategy identity with only bounded training classification."""

    source_run_id: NonEmptyString = Field(max_length=200)
    candidate_key: NonEmptyString = Field(max_length=256)
    template: Literal["sma_crossover", "rsi_mean_reversion", "breakout"]
    parameters: dict[str, int | float | str | bool] = Field(min_length=1)
    training_rank: int | None = Field(default=None, ge=1, le=100)
    training_failure_category: (
        Literal[
            "zero_trades",
            "negative_training_return",
            "non_positive_training_sharpe",
        ]
        | None
    ) = None


class QuantResearchMemorySource(ContractModel):
    """One closed same-evidence source identity; no result payload is retained."""

    run_id: NonEmptyString = Field(max_length=200)
    relationship: Literal["ancestor", "workspace_history"]
    attempt_number: int = Field(ge=1)
    retry_of_run_id: NonEmptyString | None = Field(default=None, max_length=200)
    dataset_id: NonEmptyString = Field(max_length=200)
    dataset_digest: Digest
    symbol: NonEmptyString = Field(max_length=32)
    interval: Literal["1h", "4h", "1D"]
    periods_per_year: int = Field(ge=1, le=10_000)
    range_start: NonEmptyString = Field(max_length=64)
    range_end: NonEmptyString = Field(max_length=64)
    runtime_descriptor_digest: Digest
    training_split_digest: Digest
    selection_objective: Literal[
        "risk_adjusted_return",
        "total_return",
        "drawdown_control",
    ]
    comparability: Literal["same_evidence"] = "same_evidence"
    limitations: list[
        Literal[
            "duplicate_avoidance_only",
            "prior_training_context_only",
        ]
    ] = Field(
        default_factory=lambda: [
            "duplicate_avoidance_only",
            "prior_training_context_only",
        ],
        min_length=2,
        max_length=2,
    )

    @model_validator(mode="after")
    def validate_limitations(self) -> QuantResearchMemorySource:
        if self.limitations != [
            "duplicate_avoidance_only",
            "prior_training_context_only",
        ]:
            raise ValueError("research memory limitations must use the closed v1 boundary")
        return self


class QuantResearchMemoryContext(ContractModel):
    """Pinned, bounded prior-work context used only to avoid exact repetition."""

    schema_version: Literal["quant-research-memory-v1"] = "quant-research-memory-v1"
    source_run_ids: list[NonEmptyString] = Field(max_length=5)
    sources: list[QuantResearchMemorySource] = Field(max_length=5)
    tested_candidate_keys: list[NonEmptyString] = Field(max_length=15)
    candidates: list[QuantResearchMemoryCandidate] = Field(max_length=15)
    comparability: Literal["same_evidence"] = "same_evidence"
    context_digest: Digest

    @model_validator(mode="after")
    def validate_pinned_identity(self) -> QuantResearchMemoryContext:
        if len(set(self.source_run_ids)) != len(self.source_run_ids):
            raise ValueError("research memory source runs must be unique")
        if [item.run_id for item in self.sources] != self.source_run_ids:
            raise ValueError("research memory sources must match the pinned source run ids")
        if len(set(self.tested_candidate_keys)) != len(self.tested_candidate_keys):
            raise ValueError("research memory candidate keys must be unique")
        if [item.candidate_key for item in self.candidates] != self.tested_candidate_keys:
            raise ValueError("research memory candidates must match the pinned candidate keys")
        if any(item.source_run_id not in self.source_run_ids for item in self.candidates):
            raise ValueError("research memory candidates must belong to a pinned source run")
        return self


class QuantIterationMetrics(ContractModel):
    total_return_pct: float
    annualized_return_pct: float
    maximum_drawdown_pct: float
    sharpe_ratio: float
    trade_count: int = Field(ge=0)
    win_rate_pct: float
    final_equity: float


class QuantIterationDeltas(ContractModel):
    return_difference: float
    drawdown_difference: float
    sharpe_difference: float
    trade_count_difference: int


class QuantIterationWalkForwardAggregate(ContractModel):
    """Aggregate-only repeated training evidence; individual folds stay private."""

    status: str
    evaluated_folds: int = Field(ge=0)
    candidate_positive_return_folds: int | None = Field(default=None, ge=0)
    candidate_lower_drawdown_folds: int | None = Field(default=None, ge=0)
    candidate_median_return_pct: float | None = None
    benchmark_median_return_pct: float | None = None
    candidate_median_drawdown_pct: float | None = None
    benchmark_median_drawdown_pct: float | None = None
    candidate_median_sharpe_ratio: float | None = None
    benchmark_median_sharpe_ratio: float | None = None
    distinct_market_regimes: int | None = Field(default=None, ge=0)
    regime_diversity_status: str | None = None


class QuantIterationCandidateFeedback(ContractModel):
    candidate_id: NonEmptyString = Field(max_length=200)
    name: NonEmptyString = Field(max_length=200)
    template: NonEmptyString = Field(max_length=100)
    parameters: dict[str, int | float | str | bool] = Field(min_length=1)
    canonical_key: NonEmptyString = Field(max_length=256)
    metrics: QuantIterationMetrics
    deltas: QuantIterationDeltas
    walk_forward: QuantIterationWalkForwardAggregate


class QuantIterationTrainingSplit(ContractModel):
    rule_version: VersionString
    train_bar_count: int = Field(ge=1)
    train_start: NonEmptyString = Field(max_length=32)
    train_end: NonEmptyString = Field(max_length=32)


class QuantIterationRemainingBudget(ContractModel):
    experiments: int = Field(ge=0)
    iterations: int = Field(ge=0)


class QuantIterationNoveltyConstraint(ContractModel):
    exact_dedupe_rule: Literal["template_parameters_canonical_v1"] = (
        "template_parameters_canonical_v1"
    )
    tested_candidate_keys: list[NonEmptyString] = Field(min_length=2, max_length=100)


class QuantIterationImprovementReference(ContractModel):
    candidate_id: NonEmptyString = Field(max_length=200)
    canonical_key: NonEmptyString = Field(max_length=256)
    selection_rule: Literal[
        "highest_sharpe_then_return_then_drawdown",
        "risk_adjusted_return",
        "total_return",
        "drawdown_control",
    ] = "risk_adjusted_return"


class QuantIterationStopSignal(ContractModel):
    code: Literal["continue_train_only_iteration", "iteration_budget_exhausted"]
    reason: NonEmptyString = Field(max_length=500)


class QuantIterationFeedback(ContractModel):
    """One bounded, train-only comparison summary for a future Agent decision."""

    schema_version: VersionString = "quant-iteration-feedback-v1"
    round: int = Field(default=1, ge=1, le=1)
    comparison_artifact_id: NonEmptyString = Field(max_length=200)
    evaluation_partition: Literal["train"] = "train"
    training_split: QuantIterationTrainingSplit
    benchmark: QuantIterationMetrics
    completed_candidates: list[QuantIterationCandidateFeedback] = Field(
        min_length=2, max_length=100
    )
    remaining_budget: QuantIterationRemainingBudget
    novelty: QuantIterationNoveltyConstraint
    improvement_reference: QuantIterationImprovementReference
    stop_signal: QuantIterationStopSignal


class QuantAgentContext(ContractModel):
    run_id: str
    project_id: str
    research_goal: str
    mode: str
    run_state: str
    dataset_summary: dict[str, object]
    benchmark_summary: dict[str, object] | None
    available_templates: list[dict[str, object]]
    candidates: list[QuantAgentCandidateContext]
    budget: QuantAgentBudget
    recent_events: list[dict[str, object]]
    recent_observations: list[dict[str, object]]
    plan_summary: str | None
    approved_plan: QuantExecutablePlanContext | None = None
    final_conclusion: str | None
    refinement: QuantRefinementSeedContext | None = None
    iteration_feedback: QuantIterationFeedback | None = None
    latest_comparison: QuantAgentComparisonContext | None = None
    research_series: QuantResearchSeriesContext | None = None
    research_memory: QuantResearchMemoryContext | None = None

    @field_validator("dataset_summary")
    @classmethod
    def validate_market_dataset_summary(cls, value: dict[str, object]) -> dict[str, object]:
        """Keep legacy daily payloads byte-shaped while strictly validating v2 context."""

        if _has_v2_dataset_summary_signal(value):
            QuantAgentMarketDatasetSummary.model_validate(value)
        return value
