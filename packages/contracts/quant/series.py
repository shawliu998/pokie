"""Bounded, train-only contracts for one Research Series follow-up."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from ..base import ContractModel, Digest, NonEmptyString


class QuantResearchLoopPolicy(ContractModel):
    """Server-owned budget for an optional, precommitted follow-up version."""

    schema_version: Literal["quant-research-loop-policy-v1"] = "quant-research-loop-policy-v1"
    follow_up_mode: Literal["stop_after_run", "one_train_only_follow_up"] = "stop_after_run"
    max_versions: Literal[1, 2] = 1
    max_total_experiments: Literal[3, 6] = 3
    max_total_agent_actions: Literal[12, 24] = 12
    automatic_retry: Literal[False] = False
    decision_partition: Literal["train"] = "train"
    descriptor_policy: Literal["exact"] = "exact"

    @model_validator(mode="after")
    def validate_budget_shape(self) -> QuantResearchLoopPolicy:
        expected = (1, 3, 12) if self.follow_up_mode == "stop_after_run" else (2, 6, 24)
        actual = (
            self.max_versions,
            self.max_total_experiments,
            self.max_total_agent_actions,
        )
        if actual != expected:
            raise ValueError("Research-loop budgets must match the selected follow-up mode.")
        return self


def research_loop_policy_digest(policy: QuantResearchLoopPolicy) -> str:
    payload = json.dumps(
        policy.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class QuantResearchSeriesContext(ContractModel):
    """Compact series state allowed inside an Agent decision context."""

    schema_version: Literal["quant-research-series-context-v1"] = "quant-research-series-context-v1"
    root_run_id: NonEmptyString = Field(max_length=200)
    current_run_id: NonEmptyString = Field(max_length=200)
    version_number: int = Field(ge=1, le=2)
    remaining_versions: int = Field(ge=0, le=1)
    allowed_actions: list[Literal["finish_without_follow_up", "precommit_one_refinement"]] = Field(
        min_length=1, max_length=2
    )
    blocking_reasons: list[NonEmptyString] = Field(default_factory=list, max_length=20)
    ancestor_candidate_keys: list[NonEmptyString] = Field(default_factory=list, max_length=100)
    ancestor_candidates: list[dict[str, object]] = Field(default_factory=list, max_length=100)
    policy_digest: Digest


class QuantResearchSeriesDecision(ContractModel):
    """Agent decision derived only from the final training comparison."""

    schema_version: Literal["quant-research-series-decision-v1"] = (
        "quant-research-series-decision-v1"
    )
    evaluation_partition: Literal["train"] = "train"
    action: Literal["stop", "refine_selected", "needs_review"]
    source_comparison_artifact_id: NonEmptyString = Field(max_length=200)
    seed_candidate_id: NonEmptyString | None = Field(default=None, max_length=200)
    focus: (
        Literal[
            "reduce_drawdown",
            "improve_risk_adjusted_return",
            "increase_exposure",
            "improve_walk_forward_stability",
            "test_distinct_family",
        ]
        | None
    ) = None
    refinement_reason: NonEmptyString | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_action_payload(self) -> QuantResearchSeriesDecision:
        refinement_fields = (
            self.seed_candidate_id,
            self.focus,
            self.refinement_reason,
        )
        if self.action == "refine_selected" and any(value is None for value in refinement_fields):
            raise ValueError("A refinement decision requires a seed, focus, and reason.")
        if self.action != "refine_selected" and any(
            value is not None for value in refinement_fields
        ):
            raise ValueError("A non-refinement decision cannot carry refinement fields.")
        return self


class QuantResearchSeriesControl(ContractModel):
    """Durable technical state stored inside the existing workspace state JSON."""

    schema_version: Literal["quant-research-series-control-v1"] = "quant-research-series-control-v1"
    root_run_id: NonEmptyString = Field(max_length=200)
    workspace_id: NonEmptyString = Field(max_length=200)
    project_id: NonEmptyString = Field(max_length=200)
    active_run_id: NonEmptyString = Field(max_length=200)
    state: Literal["active", "awaiting_review", "blocked", "stopped", "completed"]
    policy_digest: Digest
    scheduled_from_run_id: NonEmptyString | None = Field(default=None, max_length=200)
    decision_artifact_id: NonEmptyString | None = Field(default=None, max_length=200)
    terminal_reason: NonEmptyString | None = Field(default=None, max_length=500)
    row_version: int = Field(ge=1)
    created_at: NonEmptyString = Field(max_length=64)
    updated_at: NonEmptyString = Field(max_length=64)
