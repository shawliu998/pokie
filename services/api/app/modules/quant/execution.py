"""Server-owned execution-cost policy shared by Quant service projections."""

from __future__ import annotations

from dataclasses import dataclass

from packages.domain.quant_backtest import ExecutionConfig

EXECUTION_RULE_VERSION = "quant-execution-cost-policy-v1"
PARAMETER_NEIGHBORHOOD_RULE_VERSION = "oat-parameter-neighborhood-v1"
BASELINE_FEE_RATE = 0.001
BASELINE_SLIPPAGE_RATE = 0.0005


@dataclass(frozen=True, slots=True)
class QuantCostScenario:
    name: str
    multiplier: int
    execution: ExecutionConfig


def execution_for_cost_multiplier(multiplier: int) -> ExecutionConfig:
    if multiplier not in {1, 2, 4}:
        raise ValueError("Quant cost multiplier must be one of 1, 2, or 4.")
    return ExecutionConfig(
        fee_rate=BASELINE_FEE_RATE * multiplier,
        slippage_rate=BASELINE_SLIPPAGE_RATE * multiplier,
    )


BASELINE_EXECUTION = execution_for_cost_multiplier(1)
COST_SENSITIVITY_SCENARIOS = (
    QuantCostScenario("baseline_1x", 1, BASELINE_EXECUTION),
    QuantCostScenario("stressed_2x", 2, execution_for_cost_multiplier(2)),
    QuantCostScenario("stressed_4x", 4, execution_for_cost_multiplier(4)),
)
