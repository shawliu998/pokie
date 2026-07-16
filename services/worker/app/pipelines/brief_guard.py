"""Boundary guard for Decision Brief creation commands.

The worker never creates a DecisionBriefVersion from deterministic run output.
This helper is a small shared guard for the future API/domain adapter wiring:
only an explicit command with a verified same-Investigation synthesis may pass.
"""

from __future__ import annotations

from dataclasses import dataclass


class DecisionBriefBoundaryError(RuntimeError):
    """Raised when a Brief command tries to bypass verified synthesis review."""


@dataclass(frozen=True, slots=True)
class BriefCreationBoundaryCommand:
    investigation_id: str
    synthesis_version_id: str
    synthesis_investigation_id: str
    synthesis_review_id: str | None
    synthesis_review_decision: str | None
    verified_claim_version_ids: tuple[str, ...]
    template_version: str


def validate_brief_creation_boundary(command: BriefCreationBoundaryCommand) -> None:
    if command.investigation_id != command.synthesis_investigation_id:
        raise DecisionBriefBoundaryError("synthesis must belong to the same Investigation")
    if not command.synthesis_version_id:
        raise DecisionBriefBoundaryError("synthesis_version_id is required")
    if not command.synthesis_review_id:
        raise DecisionBriefBoundaryError("verified synthesis_review_id is required")
    if command.synthesis_review_decision != "verify":
        raise DecisionBriefBoundaryError("Decision Brief requires a verified synthesis review")
    if not command.verified_claim_version_ids:
        raise DecisionBriefBoundaryError("verified synthesis must pin at least one ClaimVersion")
    if command.template_version != "decision-brief-v1":
        raise DecisionBriefBoundaryError("unsupported Decision Brief template")
