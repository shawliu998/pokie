"""Strict single-action output contract for the Quant research agent."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from ..base import ContractModel
from .series import QuantResearchSeriesDecision


class QuantAgentAction(StrEnum):
    INSPECT_RESEARCH_CONTEXT = "inspect_research_context"
    LIST_STRATEGY_TEMPLATES = "list_strategy_templates"
    CREATE_CANDIDATE = "create_candidate"
    RUN_BACKTEST = "run_backtest"
    REVISE_CANDIDATE = "revise_candidate"
    COMPARE_CANDIDATES = "compare_candidates"
    FINISH_RESEARCH = "finish_research"


class QuantEvidenceReplanDecision(ContractModel):
    """Closed P18 decision bound to one train-only A/B comparison."""

    action: Literal[
        "refine_parameters",
        "switch_approved_family",
        "stop_no_novel_candidate",
        "stop_insufficient_budget",
    ]
    source_comparison_artifact_id: str = Field(min_length=1, max_length=200)
    improvement_reference_candidate_id: str = Field(min_length=1, max_length=200)
    proposed_template: Literal["sma_crossover", "rsi_mean_reversion", "breakout"] | None = None
    proposed_parameters: dict[str, int | float] | None = None

    @model_validator(mode="after")
    def validate_stop_proposal(self) -> QuantEvidenceReplanDecision:
        has_proposal = self.proposed_template is not None or self.proposed_parameters is not None
        if self.action == "stop_no_novel_candidate":
            if self.proposed_template is None or not self.proposed_parameters:
                raise ValueError("stop_no_novel_candidate requires one bounded duplicate proposal")
        elif has_proposal:
            raise ValueError("only stop_no_novel_candidate may carry a bounded duplicate proposal")
        return self


class CreateCandidateArguments(ContractModel):
    name: str = Field(min_length=1, max_length=100)
    template: Literal["sma_crossover", "rsi_mean_reversion", "breakout"]
    hypothesis: str = Field(min_length=1, max_length=500)
    parameters: dict[str, int | float]
    change_rationale: str | None = Field(default=None, min_length=1, max_length=500)
    replan_decision: QuantEvidenceReplanDecision | None = None


class RunBacktestArguments(ContractModel):
    candidate_id: str = Field(min_length=1, max_length=128)


class ReviseCandidateArguments(ContractModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=500)
    parameter_patch: dict[str, int | float]


class QuantResearchDecisionDeviation(ContractModel):
    """One closed, train-only robustness reason for deviating from rank one."""

    reason: Literal[
        "walk_forward_stability",
        "regime_coverage",
        "minimum_trade_evidence",
    ]
    reference_candidate_id: str = Field(min_length=1, max_length=128)


class QuantResearchDecision(ContractModel):
    """Frozen final selection bound to the latest complete training comparison."""

    selected_candidate_id: str = Field(min_length=1, max_length=128)
    source_comparison_artifact_id: str = Field(min_length=1, max_length=200)
    decision_basis: Literal["approved_objective_rank", "robustness_override"]
    deviation: QuantResearchDecisionDeviation | None = None

    @model_validator(mode="after")
    def validate_basis(self) -> QuantResearchDecision:
        if self.decision_basis == "approved_objective_rank":
            if self.deviation is not None:
                raise ValueError("approved_objective_rank cannot carry a deviation")
        elif self.deviation is None:
            raise ValueError("robustness_override requires one closed deviation")
        elif self.deviation.reference_candidate_id == self.selected_candidate_id:
            raise ValueError("a robustness override must reference another candidate")
        return self


class FinishResearchArguments(ContractModel):
    selected_candidate_id: str | None = Field(default=None, min_length=1, max_length=128)
    conclusion: str = Field(min_length=1, max_length=2_000)
    next_step: Literal["paper_evaluation", "run_more_research", "stop"]
    series_decision: QuantResearchSeriesDecision | None = None
    replan_decision: QuantEvidenceReplanDecision | None = None
    research_decision: QuantResearchDecision | None = None

    @model_validator(mode="after")
    def validate_structured_stop(self) -> FinishResearchArguments:
        if self.selected_candidate_id is None:
            if self.research_decision is not None:
                raise ValueError("a no-candidate finish cannot carry a research decision")
        elif self.research_decision is None:
            raise ValueError("a selected candidate requires a structured research decision")
        elif self.research_decision.selected_candidate_id != self.selected_candidate_id:
            raise ValueError("selected candidate and research decision must match")
        if self.replan_decision is None or self.replan_decision.action not in {
            "stop_no_novel_candidate",
            "stop_insufficient_budget",
        }:
            return self
        if self.next_step != "stop":
            raise ValueError("a structured evidence stop requires next_step=stop")
        if self.series_decision is not None and self.series_decision.action != "stop":
            raise ValueError("a structured evidence stop cannot schedule a Research Series child")
        return self


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


class QuantStrategyScopeDecision(ContractModel):
    """Closed pre-execution decision for the registered strategy boundary."""

    schema_version: Literal["quant-strategy-scope-v1"] = "quant-strategy-scope-v1"
    status: Literal["supported", "bounded_proxy", "unsupported"]
    reason: str = Field(min_length=1, max_length=1_000)
    proxy_description: str | None = Field(default=None, min_length=1, max_length=1_000)
    excluded_behaviors: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_scope_shape(self) -> QuantStrategyScopeDecision:
        if not self.reason.strip() or self.reason != self.reason.strip():
            raise ValueError("strategy scope reason must contain trimmed non-empty text")
        if self.proxy_description is not None and (
            not self.proxy_description.strip()
            or self.proxy_description != self.proxy_description.strip()
        ):
            raise ValueError("strategy scope proxy_description must contain trimmed text")
        if any(not item.strip() or item != item.strip() for item in self.excluded_behaviors):
            raise ValueError("excluded_behaviors must contain trimmed non-empty text")
        if len(set(self.excluded_behaviors)) != len(self.excluded_behaviors):
            raise ValueError("excluded_behaviors must be unique")
        if self.status == "supported":
            if self.proxy_description is not None or self.excluded_behaviors:
                raise ValueError("supported scope cannot contain a proxy or excluded behaviors")
        elif self.status == "bounded_proxy":
            if self.proxy_description is None or not self.excluded_behaviors:
                raise ValueError(
                    "bounded_proxy scope requires a proxy and at least one excluded behavior"
                )
        elif self.proxy_description is not None or not self.excluded_behaviors:
            raise ValueError(
                "unsupported scope requires excluded behaviors and cannot contain a proxy"
            )
        return self


class QuantAgentPlan(ContractModel):
    objective_summary: str = Field(min_length=1, max_length=1_000)
    steps: list[QuantAgentPlanStep] = Field(min_length=1, max_length=8)
    candidate_families: list[Literal["sma_crossover", "rsi_mean_reversion", "breakout"]] = Field(
        max_length=3
    )
    strategy_scope: QuantStrategyScopeDecision
    selection_objective: Literal["risk_adjusted_return", "total_return", "drawdown_control"]
    # Autonomous Iteration v1 reserves the third experiment for the one
    # feedback-driven exploration candidate, so plans cannot silently opt out
    # of the bounded 2+1 loop.
    max_experiments: Literal[3] = 3
    max_repairs: int = Field(ge=0, le=2)
    completion_criteria: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_executable_policy(self) -> QuantAgentPlan:
        if len(set(self.candidate_families)) != len(self.candidate_families):
            raise ValueError("candidate_families must be unique")
        if self.strategy_scope.status == "unsupported":
            if self.candidate_families:
                raise ValueError("unsupported scope cannot approve candidate families")
        elif not self.candidate_families:
            raise ValueError("supported and bounded_proxy scope require candidate families")
        if any(not item.strip() or item != item.strip() for item in self.completion_criteria):
            raise ValueError("completion_criteria must contain trimmed non-empty text")
        return self
