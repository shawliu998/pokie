"""Database-rebuilt bounded context for one Quant agent decision."""

from __future__ import annotations

from pydantic import Field

from ..base import ContractModel


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
    final_conclusion: str | None
