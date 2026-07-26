"""Strict train-only cost and local parameter-sensitivity evidence."""

from __future__ import annotations

from math import isfinite
from typing import Literal

from pydantic import ConfigDict, Field, FiniteFloat, StrictInt, field_validator, model_validator

from ..base import ContractModel, Digest, NonEmptyString


class _FrozenRobustnessModel(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        use_enum_values=False,
        validate_assignment=True,
        allow_inf_nan=False,
    )


class QuantRobustnessMetrics(_FrozenRobustnessModel):
    total_return_pct: FiniteFloat
    annualized_return_pct: FiniteFloat
    maximum_drawdown_pct: FiniteFloat
    sharpe_ratio: FiniteFloat
    trade_count: StrictInt = Field(ge=0)
    win_rate_pct: FiniteFloat
    final_equity: FiniteFloat


class QuantRobustnessCandidateIdentity(_FrozenRobustnessModel):
    candidate_id: NonEmptyString = Field(max_length=200)
    template: Literal["sma_crossover", "rsi_mean_reversion", "breakout"]
    parameters: dict[str, StrictInt | FiniteFloat] = Field(min_length=1, max_length=8)
    canonical_key: Digest

    @field_validator("parameters")
    @classmethod
    def validate_parameters(
        cls, value: dict[str, StrictInt | FiniteFloat]
    ) -> dict[str, StrictInt | FiniteFloat]:
        if any(
            not key or isinstance(item, bool) or not isfinite(float(item))
            for key, item in value.items()
        ):
            raise ValueError("strategy parameters must be finite named numeric values")
        return value


class QuantRobustnessArtifactIdentity(_FrozenRobustnessModel):
    artifact_id: NonEmptyString = Field(max_length=200)
    artifact_digest: Digest


class QuantRobustnessDatasetIdentity(_FrozenRobustnessModel):
    dataset_id: NonEmptyString = Field(max_length=200)
    dataset_digest: Digest


class QuantRobustnessTrainingSplitIdentity(_FrozenRobustnessModel):
    identity_kind: Literal["sealed_market_split", "deterministic_legacy_split"]
    rule_version: Literal["chronological-80-20-v1"]
    training_bar_count: StrictInt = Field(ge=1)
    training_start: NonEmptyString = Field(max_length=64)
    training_end: NonEmptyString = Field(max_length=64)
    training_split_digest: Digest
    sealed_split_digest: Digest | None = None

    @model_validator(mode="after")
    def validate_sealed_identity(self) -> QuantRobustnessTrainingSplitIdentity:
        if self.identity_kind == "sealed_market_split":
            if (
                self.sealed_split_digest is None
                or self.sealed_split_digest != self.training_split_digest
            ):
                raise ValueError("a market training split must retain its exact sealed digest")
        elif self.sealed_split_digest is not None:
            raise ValueError("a legacy deterministic split cannot claim a sealed digest")
        return self


class QuantRobustnessCostScenario(_FrozenRobustnessModel):
    scenario: Literal["baseline_1x", "stressed_2x", "stressed_4x"]
    multiplier: Literal[1, 2, 4]
    fee_rate: FiniteFloat = Field(ge=0)
    slippage_rate: FiniteFloat = Field(ge=0)
    candidate_metrics: QuantRobustnessMetrics
    benchmark_metrics: QuantRobustnessMetrics


class QuantRobustnessParameterNeighbor(_FrozenRobustnessModel):
    parameter_name: NonEmptyString = Field(max_length=80)
    direction: Literal["lower", "upper"]
    parameters: dict[str, StrictInt | FiniteFloat] = Field(min_length=1, max_length=8)
    canonical_key: Digest
    candidate_metrics: QuantRobustnessMetrics

    _validate_parameters = field_validator("parameters")(
        QuantRobustnessCandidateIdentity.validate_parameters.__func__
    )


class QuantRobustnessSensitivity(_FrozenRobustnessModel):
    """Immutable v1 evidence; it intentionally has no score or pass/fail verdict."""

    schema_version: Literal["robustness_sensitivity_v1"] = "robustness_sensitivity_v1"
    evaluation_partition: Literal["train"] = "train"
    run_id: NonEmptyString = Field(max_length=200)
    report_artifact_id: NonEmptyString = Field(max_length=200)
    candidate: QuantRobustnessCandidateIdentity
    final_training_comparison: QuantRobustnessArtifactIdentity
    dataset: QuantRobustnessDatasetIdentity
    interval: Literal["1h", "4h", "1D"]
    periods_per_year: StrictInt = Field(ge=1, le=10_000)
    runtime_descriptor_digest: Digest
    training_split: QuantRobustnessTrainingSplitIdentity
    execution_rule_version: Literal["quant-execution-cost-policy-v1"]
    sampler_rule_version: Literal["oat-parameter-neighborhood-v1"]
    cost_scenarios: list[QuantRobustnessCostScenario] = Field(min_length=3, max_length=3)
    parameter_neighbors: list[QuantRobustnessParameterNeighbor] = Field(max_length=6)
    kernel_call_count: StrictInt = Field(ge=6, le=12)

    @model_validator(mode="after")
    def validate_exact_evidence_shape(self) -> QuantRobustnessSensitivity:
        expected_costs = (
            ("baseline_1x", 1, 0.001, 0.0005),
            ("stressed_2x", 2, 0.002, 0.001),
            ("stressed_4x", 4, 0.004, 0.002),
        )
        actual_costs = tuple(
            (
                item.scenario,
                item.multiplier,
                item.fee_rate,
                item.slippage_rate,
            )
            for item in self.cost_scenarios
        )
        if actual_costs != expected_costs:
            raise ValueError("cost sensitivity must retain the exact ordered 1x/2x/4x set")
        if self.kernel_call_count != 6 + len(self.parameter_neighbors):
            raise ValueError("kernel call count must equal six cost calls plus OAT neighbors")

        expected_parameters = {
            "sma_crossover": ("fast_window", "slow_window"),
            "rsi_mean_reversion": (
                "period",
                "entry_threshold",
                "exit_threshold",
            ),
            "breakout": ("lookback_window",),
        }[self.candidate.template]
        if tuple(self.candidate.parameters) != expected_parameters:
            raise ValueError("candidate parameters do not match their canonical template order")

        allowed_order = [
            (parameter, direction)
            for parameter in expected_parameters
            for direction in ("lower", "upper")
        ]
        order_indexes: list[int] = []
        seen_keys = {self.candidate.canonical_key}
        for neighbor in self.parameter_neighbors:
            identity = (neighbor.parameter_name, neighbor.direction)
            if identity not in allowed_order:
                raise ValueError("parameter neighborhood contains an unsupported identity")
            order_indexes.append(allowed_order.index(identity))
            if tuple(neighbor.parameters) != expected_parameters:
                raise ValueError("neighbor parameters do not match their template order")
            changed = [
                key
                for key in expected_parameters
                if neighbor.parameters[key] != self.candidate.parameters[key]
            ]
            if changed != [neighbor.parameter_name]:
                raise ValueError("parameter neighborhood must use one-at-a-time changes")
            if neighbor.canonical_key in seen_keys:
                raise ValueError("parameter neighborhood canonical identities must be unique")
            seen_keys.add(neighbor.canonical_key)
        if order_indexes != sorted(order_indexes) or len(set(order_indexes)) != len(order_indexes):
            raise ValueError("parameter neighborhood identity and order must be deterministic")
        return self
