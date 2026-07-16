"""Transparent Signal Impact/Urgency to Priority derivation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .errors import InvariantViolation


class BusinessImpact(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class Urgency(StrEnum):
    NOW = "now"
    THIS_WEEK = "this_week"
    MONITOR = "monitor"
    UNKNOWN = "unknown"


class Priority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class PriorityStatus(StrEnum):
    PENDING_CONFIRMATION = "pending_confirmation"
    INSUFFICIENT_INPUT = "insufficient_input"
    DERIVED = "derived"


DEFAULT_PRIORITY_POLICY_VERSION = "priority-matrix-v1"

_PRIORITY_MATRIX: dict[tuple[BusinessImpact, Urgency], Priority] = {
    (BusinessImpact.HIGH, Urgency.NOW): Priority.P0,
    (BusinessImpact.HIGH, Urgency.THIS_WEEK): Priority.P1,
    (BusinessImpact.HIGH, Urgency.MONITOR): Priority.P2,
    (BusinessImpact.MEDIUM, Urgency.NOW): Priority.P1,
    (BusinessImpact.MEDIUM, Urgency.THIS_WEEK): Priority.P2,
    (BusinessImpact.MEDIUM, Urgency.MONITOR): Priority.P3,
    (BusinessImpact.LOW, Urgency.NOW): Priority.P2,
    (BusinessImpact.LOW, Urgency.THIS_WEEK): Priority.P3,
    (BusinessImpact.LOW, Urgency.MONITOR): Priority.P3,
}


@dataclass(frozen=True, slots=True)
class SignalPriority:
    status: PriorityStatus
    level: Priority | None
    policy_version: str
    impact_assessment_version: int | None
    urgency_assessment_version: int | None
    explanation: str


def derive_signal_priority(
    business_impact: BusinessImpact | None,
    urgency: Urgency | None,
    *,
    impact_assessment_version: int | None,
    urgency_assessment_version: int | None,
    policy_version: str = DEFAULT_PRIORITY_POLICY_VERSION,
) -> SignalPriority:
    """Derive Priority only from exact human-confirmed assessment versions."""

    try:
        business_impact = BusinessImpact(business_impact) if business_impact is not None else None
        urgency = Urgency(urgency) if urgency is not None else None
    except ValueError as exc:
        raise InvariantViolation("Signal assessment contains an unknown level.") from exc
    if not policy_version:
        raise InvariantViolation("Priority derivation requires a policy version.")
    if (business_impact is None) != (impact_assessment_version is None):
        raise InvariantViolation(
            "Business Impact value and assessment version must be present together."
        )
    if (urgency is None) != (urgency_assessment_version is None):
        raise InvariantViolation("Urgency value and assessment version must be present together.")
    if impact_assessment_version is not None and impact_assessment_version < 1:
        raise InvariantViolation("Confirmed Business Impact requires a positive version.")
    if urgency_assessment_version is not None and urgency_assessment_version < 1:
        raise InvariantViolation("Confirmed Urgency requires a positive version.")
    if business_impact is None or urgency is None:
        return SignalPriority(
            PriorityStatus.PENDING_CONFIRMATION,
            None,
            policy_version,
            impact_assessment_version,
            urgency_assessment_version,
            "Confirm Business Impact and Urgency to derive Priority.",
        )
    if business_impact is BusinessImpact.UNKNOWN or urgency is Urgency.UNKNOWN:
        return SignalPriority(
            PriorityStatus.INSUFFICIENT_INPUT,
            None,
            policy_version,
            impact_assessment_version,
            urgency_assessment_version,
            "A confirmed Unknown assessment cannot enter the Priority matrix.",
        )
    level = _PRIORITY_MATRIX[(business_impact, urgency)]
    return SignalPriority(
        PriorityStatus.DERIVED,
        level,
        policy_version,
        impact_assessment_version,
        urgency_assessment_version,
        f"Derived from {business_impact.value} impact and {urgency.value} urgency.",
    )
