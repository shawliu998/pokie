"""Closed registry and safe observations for bounded Quant tools."""

from __future__ import annotations

from pydantic import Field

from ..base import ContractModel
from .agent import QuantAgentAction


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


QUANT_AGENT_TOOL_REGISTRY: tuple[QuantAgentAction, ...] = tuple(QuantAgentAction)
