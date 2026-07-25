"""Closed registry and safe observations for bounded Quant tools."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.domain.canonical import canonical_digest

from ..base import ContractModel, Digest, NonEmptyString
from .agent import (
    CreateCandidateArguments,
    FinishResearchArguments,
    QuantAgentAction,
    ReviseCandidateArguments,
    RunBacktestArguments,
)
from .learning import QuantToolIdentity

QUANT_AGENT_TOOL_REGISTRY_VERSION = "1.0.0"


class QuantEmptyToolArguments(BaseModel):
    """The shared actual input model for registered no-argument tools."""

    model_config = ConfigDict(extra="forbid", title="_EmptyArguments")


_QUANT_TOOL_INPUT_MODELS: MappingProxyType[QuantAgentAction, type[BaseModel]] = MappingProxyType(
    {
        QuantAgentAction.INSPECT_RESEARCH_CONTEXT: QuantEmptyToolArguments,
        QuantAgentAction.LIST_STRATEGY_TEMPLATES: QuantEmptyToolArguments,
        QuantAgentAction.CREATE_CANDIDATE: CreateCandidateArguments,
        QuantAgentAction.RUN_BACKTEST: RunBacktestArguments,
        QuantAgentAction.REVISE_CANDIDATE: ReviseCandidateArguments,
        QuantAgentAction.COMPARE_CANDIDATES: QuantEmptyToolArguments,
        QuantAgentAction.FINISH_RESEARCH: FinishResearchArguments,
    }
)
_QUANT_TOOL_VERSIONS: MappingProxyType[QuantAgentAction, str] = MappingProxyType(
    {action: "1.0.0" for action in QuantAgentAction}
)


def quant_tool_input_model(action: QuantAgentAction) -> type[BaseModel]:
    return _QUANT_TOOL_INPUT_MODELS[QuantAgentAction(action)]


def quant_tool_version(action: QuantAgentAction) -> str:
    return _QUANT_TOOL_VERSIONS[QuantAgentAction(action)]


def quant_tool_identity(action: QuantAgentAction) -> QuantToolIdentity:
    action = QuantAgentAction(action)
    input_model = quant_tool_input_model(action)
    return QuantToolIdentity(
        registry_version=QUANT_AGENT_TOOL_REGISTRY_VERSION,
        action=action,
        tool_version=quant_tool_version(action),
        input_schema_digest=canonical_digest(input_model.model_json_schema()),
    )


def validate_quant_tool_arguments(
    action: QuantAgentAction,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Validate and normalize without invoking the registered tool."""

    parsed = quant_tool_input_model(action).model_validate(arguments)
    return parsed.model_dump(mode="json", exclude_none=True)


class QuantToolRepairViolation(ContractModel):
    """One safe field-level correction for a rejected tool call."""

    path: NonEmptyString = Field(max_length=200)
    code: Literal[
        "field_not_allowed_for_action",
        "field_required",
        "invalid_value",
        "invalid_shape",
    ]
    constraint: NonEmptyString = Field(max_length=500)
    correction: NonEmptyString = Field(max_length=500)
    required_change: Literal["remove", "supply", "replace"]
    allowed_values: list[NonEmptyString] = Field(default_factory=list, max_length=20)
    rejected_value_fingerprint: Digest | None = None


class QuantToolRepair(ContractModel):
    """Closed repair guidance retained after one INVALID_ARGUMENTS result."""

    schema_version: Literal["quant-tool-repair-v1"] = "quant-tool-repair-v1"
    action: QuantAgentAction
    call_fingerprint: Digest
    allowed_shape: NonEmptyString = Field(max_length=1_000)
    violations: list[QuantToolRepairViolation] = Field(min_length=1, max_length=8)
    retry_policy: Literal["modify_arguments_or_stop"] = "modify_arguments_or_stop"

    @model_validator(mode="after")
    def validate_unique_paths(self) -> QuantToolRepair:
        paths = [item.path for item in self.violations]
        if len(paths) != len(set(paths)):
            raise ValueError("tool repair violation paths must be unique")
        return self


class QuantToolObservation(ContractModel):
    action: QuantAgentAction
    success: bool
    safe_summary: str = Field(min_length=1, max_length=1_000)
    candidate_id: str | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    data: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None
    retryable: bool = False
    terminal: bool = False
    call_fingerprint: Digest | None = None
    repair: QuantToolRepair | None = None

    @model_validator(mode="after")
    def validate_repair_binding(self) -> QuantToolObservation:
        if self.repair is None:
            return self
        if self.success or self.error_code != "INVALID_ARGUMENTS":
            raise ValueError("tool repair is only valid for failed INVALID_ARGUMENTS observations")
        if self.call_fingerprint != self.repair.call_fingerprint:
            raise ValueError("tool repair must match the rejected call fingerprint")
        if self.action != self.repair.action:
            raise ValueError("tool repair must match the rejected action")
        return self


QUANT_AGENT_TOOL_REGISTRY: tuple[QuantAgentAction, ...] = tuple(QuantAgentAction)
