"""Strict contracts for validator-proven Quant tool-contract learning."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from ..base import ContractModel, Digest, NonEmptyString, VersionString
from .agent import QuantAgentAction

QUANT_LEARNING_TRACE_SCHEMA_VERSION = "quant-learning-trace-v1"
QUANT_REPAIR_MEMORY_SCHEMA_VERSION = "quant-repair-memory-v1"
QUANT_REPAIR_MEMORY_REUSE_SCHEMA_VERSION = "quant-repair-memory-reuse-v1"
QUANT_REPAIR_MEMORY_MAX_ENTRIES = 8
QUANT_REPAIR_MEMORY_MAX_SOURCE_TRACES = 3


class QuantToolIdentity(ContractModel):
    """Exact registered input-contract identity for one Quant tool."""

    registry_version: VersionString
    action: QuantAgentAction
    tool_version: VersionString
    input_schema_digest: Digest


class QuantLearningEventRef(ContractModel):
    """Digest-only reference to one authoritative persisted Run event."""

    event_id: UUID
    sequence: int = Field(ge=1)
    event_digest: Digest


class QuantLearningViolation(ContractModel):
    """Closed metadata for one rejected argument field."""

    path: NonEmptyString = Field(max_length=200)
    code: Literal[
        "field_not_allowed_for_action",
        "field_required",
        "invalid_value",
        "invalid_shape",
    ]
    required_change: Literal["remove", "supply", "replace"]
    allowed_values_digest: Digest | None = None
    rejected_value_fingerprint: Digest | None = None


class QuantLearningFieldDelta(ContractModel):
    """Digest-only material change between the rejected and corrected call."""

    path: NonEmptyString = Field(max_length=200)
    change: Literal["remove", "supply", "replace"]
    before_digest: Digest | None = None
    after_digest: Digest | None = None

    @model_validator(mode="after")
    def validate_change_shape(self) -> QuantLearningFieldDelta:
        if self.change == "remove":
            if self.before_digest is None or self.after_digest is not None:
                raise ValueError("a remove delta requires only before_digest")
        elif self.change == "supply":
            if self.before_digest is not None or self.after_digest is None:
                raise ValueError("a supply delta requires only after_digest")
        elif self.before_digest is None or self.after_digest is None:
            raise ValueError("a replace delta requires before_digest and after_digest")
        return self


class QuantLearningTrace(ContractModel):
    """One immutable typed outcome for an existing R0 repair episode."""

    schema_version: Literal["quant-learning-trace-v1"] = QUANT_LEARNING_TRACE_SCHEMA_VERSION
    trace_id: UUID
    workspace_id: NonEmptyString = Field(max_length=200)
    run_id: UUID
    attempt_number: int = Field(ge=1)
    provider: NonEmptyString = Field(max_length=100)
    model: str | None = Field(default=None, max_length=200)
    selection_objective: Literal[
        "risk_adjusted_return",
        "total_return",
        "drawdown_control",
    ]
    phase: Literal["tool_execution"] = "tool_execution"
    context_identity_digest: Digest
    tool: QuantToolIdentity
    failed_event: QuantLearningEventRef
    failed_call_fingerprint: Digest
    error_code: Literal["INVALID_ARGUMENTS"] = "INVALID_ARGUMENTS"
    violations: list[QuantLearningViolation] = Field(min_length=1, max_length=8)
    correction_delta: list[QuantLearningFieldDelta] = Field(default_factory=list, max_length=8)
    correction_started_event: QuantLearningEventRef | None = None
    corrected_call_fingerprint: Digest | None = None
    outcome: Literal["resolved", "stopped", "failed"]
    outcome_event: QuantLearningEventRef
    supporting_events: list[QuantLearningEventRef] = Field(default_factory=list, max_length=4)
    closed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_outcome_shape(self) -> QuantLearningTrace:
        violation_paths = [item.path for item in self.violations]
        delta_paths = [item.path for item in self.correction_delta]
        if len(violation_paths) != len(set(violation_paths)):
            raise ValueError("learning trace violation paths must be unique")
        if len(delta_paths) != len(set(delta_paths)):
            raise ValueError("learning trace delta paths must be unique")
        if self.failed_event.sequence >= self.outcome_event.sequence:
            raise ValueError("learning trace outcome must follow its failed event")
        if self.outcome == "stopped":
            if (
                self.correction_started_event is not None
                or self.corrected_call_fingerprint is not None
                or self.correction_delta
            ):
                raise ValueError("a stopped trace cannot claim a corrected tool call")
        else:
            if (
                self.correction_started_event is None
                or self.corrected_call_fingerprint is None
                or not self.correction_delta
            ):
                raise ValueError("a corrected trace requires its call identity and delta")
            if not (
                self.failed_event.sequence
                < self.correction_started_event.sequence
                < self.outcome_event.sequence
            ):
                raise ValueError("learning trace corrected event order is invalid")
        supporting_ids = [item.event_id for item in self.supporting_events]
        if len(supporting_ids) != len(set(supporting_ids)):
            raise ValueError("learning trace supporting events must be unique")
        return self


class QuantRepairMemoryEntry(ContractModel):
    """One compatible exact-fingerprint, remove-only verified repair."""

    source_trace_ids: list[UUID] = Field(
        min_length=1,
        max_length=QUANT_REPAIR_MEMORY_MAX_SOURCE_TRACES,
    )
    action: QuantAgentAction
    failed_call_fingerprint: Digest
    tool: QuantToolIdentity
    remove_paths: list[NonEmptyString] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_entry(self) -> QuantRepairMemoryEntry:
        if self.tool.action != self.action:
            raise ValueError("repair memory tool identity must match its action")
        if len(self.source_trace_ids) != len(set(self.source_trace_ids)):
            raise ValueError("repair memory source traces must be unique")
        if self.remove_paths != sorted(set(self.remove_paths)):
            raise ValueError("repair memory remove paths must be sorted and unique")
        return self


class QuantRepairMemory(ContractModel):
    """Immutable Run-creation pin of compatible prior resolved traces."""

    schema_version: Literal["quant-repair-memory-v1"] = QUANT_REPAIR_MEMORY_SCHEMA_VERSION
    entries: list[QuantRepairMemoryEntry] = Field(
        default_factory=list,
        max_length=QUANT_REPAIR_MEMORY_MAX_ENTRIES,
    )
    context_digest: Digest

    @model_validator(mode="after")
    def validate_unique_fingerprints(self) -> QuantRepairMemory:
        keys = [(item.action, item.failed_call_fingerprint) for item in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("repair memory exact fingerprints must be unique")
        return self


class QuantRepairMemoryReuseReceipt(ContractModel):
    """Argument-free receipt for one pre-execution verified repair reuse."""

    schema_version: Literal["quant-repair-memory-reuse-v1"] = (
        QUANT_REPAIR_MEMORY_REUSE_SCHEMA_VERSION
    )
    source_trace_ids: list[UUID] = Field(
        min_length=1,
        max_length=QUANT_REPAIR_MEMORY_MAX_SOURCE_TRACES,
    )
    action: QuantAgentAction
    original_call_fingerprint: Digest
    corrected_call_fingerprint: Digest
    changed_paths: list[NonEmptyString] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_receipt(self) -> QuantRepairMemoryReuseReceipt:
        if len(self.source_trace_ids) != len(set(self.source_trace_ids)):
            raise ValueError("repair reuse source traces must be unique")
        if self.changed_paths != sorted(set(self.changed_paths)):
            raise ValueError("repair reuse changed paths must be sorted and unique")
        if self.original_call_fingerprint == self.corrected_call_fingerprint:
            raise ValueError("repair reuse must materially change the call fingerprint")
        return self
