"""Strict single-action output contract for the Quant research agent."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from ..base import ContractModel


class QuantAgentAction(StrEnum):
    INSPECT_RESEARCH_CONTEXT = "inspect_research_context"
    LIST_STRATEGY_TEMPLATES = "list_strategy_templates"
    CREATE_CANDIDATE = "create_candidate"
    RUN_BACKTEST = "run_backtest"
    REVISE_CANDIDATE = "revise_candidate"
    COMPARE_CANDIDATES = "compare_candidates"
    FINISH_RESEARCH = "finish_research"


class CreateCandidateArguments(ContractModel):
    name: str = Field(min_length=1, max_length=100)
    template: Literal["sma_crossover", "rsi_mean_reversion", "breakout"]
    hypothesis: str = Field(min_length=1, max_length=500)
    parameters: dict[str, int | float]


class RunBacktestArguments(ContractModel):
    candidate_id: str = Field(min_length=1, max_length=128)


class ReviseCandidateArguments(ContractModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
    parameter_patch: dict[str, int | float]


class FinishResearchArguments(ContractModel):
    selected_candidate_id: str | None = Field(default=None, min_length=1, max_length=128)
    conclusion: str = Field(min_length=1, max_length=2_000)
    next_step: Literal["paper_evaluation", "run_more_research", "stop"]


class QuantAgentDecision(ContractModel):
    action: QuantAgentAction
    arguments: dict[str, Any] = Field(default_factory=dict)
    decision_summary: str = Field(min_length=1, max_length=500)
    expected_result: str = Field(min_length=1, max_length=300)


class QuantAgentPlanStep(ContractModel):
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    owner: Literal["user", "agent", "system"]
    description: str = Field(min_length=1, max_length=500)


class QuantAgentPlan(ContractModel):
    objective_summary: str = Field(min_length=1, max_length=1_000)
    steps: list[QuantAgentPlanStep] = Field(min_length=1, max_length=8)
    candidate_families: list[str] = Field(min_length=1, max_length=3)
    max_experiments: int = Field(ge=1, le=3)
    max_repairs: int = Field(ge=0, le=2)
    completion_criteria: list[str] = Field(min_length=1, max_length=8)
