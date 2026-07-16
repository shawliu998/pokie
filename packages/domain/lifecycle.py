"""Canonical Investigation and ResearchRun state machines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .canonical import require_sha256_digest
from .errors import InvalidTransition, InvariantViolation


class InvestigationState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    NEEDS_INPUT = "needs_input"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    CLOSED_INSUFFICIENT = "closed_insufficient"
    CANCELLED = "cancelled"


class InvestigationAction(StrEnum):
    REQUEST_INPUT = "request_input"
    PROVIDE_INPUT = "provide_input"
    START_REVIEW = "start_review"
    COMPLETE = "complete"
    CLOSE_INSUFFICIENT = "close_insufficient"
    CANCEL = "cancel"


class ResearchRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResearchRunAction(StrEnum):
    START = "start"
    WAIT_FOR_INPUT = "wait_for_input"
    RESUME = "resume"
    COMPLETE = "complete"
    FAIL = "fail"
    CANCEL = "cancel"


class WaitingReason(StrEnum):
    SCOPE_CLARIFICATION = "scope_clarification"
    PLAN_CHANGE = "plan_change"
    BUDGET_CHANGE = "budget_change"
    CLAIM_REVIEW = "claim_review"
    SOURCE_POLICY = "source_policy"


TERMINAL_INVESTIGATION_STATES = frozenset(
    {
        InvestigationState.COMPLETED,
        InvestigationState.CLOSED_INSUFFICIENT,
        InvestigationState.CANCELLED,
    }
)
TERMINAL_RESEARCH_RUN_STATES = frozenset(
    {ResearchRunState.COMPLETED, ResearchRunState.FAILED, ResearchRunState.CANCELLED}
)

_INVESTIGATION_TRANSITIONS: dict[
    tuple[InvestigationState, InvestigationAction], InvestigationState
] = {
    (
        InvestigationState.ACTIVE,
        InvestigationAction.REQUEST_INPUT,
    ): InvestigationState.NEEDS_INPUT,
    (
        InvestigationState.REVIEWING,
        InvestigationAction.REQUEST_INPUT,
    ): InvestigationState.NEEDS_INPUT,
    (
        InvestigationState.ACTIVE,
        InvestigationAction.START_REVIEW,
    ): InvestigationState.REVIEWING,
    (
        InvestigationState.REVIEWING,
        InvestigationAction.COMPLETE,
    ): InvestigationState.COMPLETED,
}


def transition_investigation(
    current: InvestigationState,
    action: InvestigationAction,
    *,
    resume_to: InvestigationState | None = None,
) -> InvestigationState:
    """Return the canonical state produced by an Investigation command."""

    try:
        current = InvestigationState(current)
        action = InvestigationAction(action)
        resume_to = InvestigationState(resume_to) if resume_to is not None else None
    except ValueError as exc:
        raise InvariantViolation("Investigation transition contains an unknown value.") from exc
    if action is InvestigationAction.PROVIDE_INPUT:
        if current is not InvestigationState.NEEDS_INPUT:
            raise InvalidTransition("Investigation", current.value, action.value)
        if resume_to is None or resume_to not in {
            InvestigationState.ACTIVE,
            InvestigationState.REVIEWING,
        }:
            raise InvariantViolation(
                "provide_input must resume an Investigation to active or reviewing."
            )
        return resume_to
    if resume_to is not None:
        raise InvariantViolation("resume_to is valid only for provide_input.")

    if action is InvestigationAction.CLOSE_INSUFFICIENT:
        if current not in {
            InvestigationState.ACTIVE,
            InvestigationState.NEEDS_INPUT,
            InvestigationState.REVIEWING,
        }:
            raise InvalidTransition("Investigation", current.value, action.value)
        return InvestigationState.CLOSED_INSUFFICIENT
    if action is InvestigationAction.CANCEL:
        if current not in {
            InvestigationState.DRAFT,
            InvestigationState.ACTIVE,
            InvestigationState.NEEDS_INPUT,
            InvestigationState.REVIEWING,
        }:
            raise InvalidTransition("Investigation", current.value, action.value)
        return InvestigationState.CANCELLED

    target = _INVESTIGATION_TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidTransition("Investigation", current.value, action.value)
    return target


@dataclass(frozen=True, slots=True)
class ResearchRunPins:
    investigation_id: str
    investigation_scope_version_id: str
    run_input_manifest_digest: str
    budget_digest: str

    def __post_init__(self) -> None:
        if not self.investigation_id or not self.investigation_scope_version_id:
            raise InvariantViolation("A ResearchRun must pin Investigation and scope IDs.")
        require_sha256_digest(self.run_input_manifest_digest, field="run_input_manifest_digest")
        require_sha256_digest(self.budget_digest, field="budget_digest")


@dataclass(frozen=True, slots=True)
class ResearchRunTransition:
    state: ResearchRunState
    waiting_reason: WaitingReason | None = None


def assert_research_run_pins_unchanged(expected: ResearchRunPins, actual: ResearchRunPins) -> None:
    if expected != actual:
        raise InvariantViolation(
            "ResearchRun resume requires the same immutable scope, manifest and budget; "
            "create a new attempt instead.",
            code="RUN_INPUT_CHANGED",
        )


def transition_research_run(
    current: ResearchRunState,
    action: ResearchRunAction,
    *,
    waiting_reason: WaitingReason | None = None,
    original_pins: ResearchRunPins | None = None,
    current_pins: ResearchRunPins | None = None,
) -> ResearchRunTransition:
    """Apply one ResearchRun command without leaking graph-internal state."""

    try:
        current = ResearchRunState(current)
        action = ResearchRunAction(action)
        waiting_reason = WaitingReason(waiting_reason) if waiting_reason is not None else None
    except ValueError as exc:
        raise InvariantViolation("ResearchRun transition contains an unknown value.") from exc
    if action is ResearchRunAction.START:
        if current is not ResearchRunState.QUEUED:
            raise InvalidTransition("ResearchRun", current.value, action.value)
        target = ResearchRunState.RUNNING
    elif action is ResearchRunAction.WAIT_FOR_INPUT:
        if current is not ResearchRunState.RUNNING:
            raise InvalidTransition("ResearchRun", current.value, action.value)
        if waiting_reason is None:
            raise InvariantViolation("waiting_for_input requires a closed waiting reason.")
        return ResearchRunTransition(ResearchRunState.WAITING_FOR_INPUT, waiting_reason)
    elif action is ResearchRunAction.RESUME:
        if current is not ResearchRunState.WAITING_FOR_INPUT:
            raise InvalidTransition("ResearchRun", current.value, action.value)
        if original_pins is None or current_pins is None:
            raise InvariantViolation("Resume requires both original and current run pins.")
        assert_research_run_pins_unchanged(original_pins, current_pins)
        target = ResearchRunState.RUNNING
    elif action is ResearchRunAction.COMPLETE:
        if current is not ResearchRunState.RUNNING:
            raise InvalidTransition("ResearchRun", current.value, action.value)
        target = ResearchRunState.COMPLETED
    elif action is ResearchRunAction.FAIL:
        if current is not ResearchRunState.RUNNING:
            raise InvalidTransition("ResearchRun", current.value, action.value)
        target = ResearchRunState.FAILED
    elif action is ResearchRunAction.CANCEL:
        if current not in {
            ResearchRunState.QUEUED,
            ResearchRunState.RUNNING,
            ResearchRunState.WAITING_FOR_INPUT,
        }:
            raise InvalidTransition("ResearchRun", current.value, action.value)
        target = ResearchRunState.CANCELLED
    else:  # pragma: no cover - protects future enum additions
        raise InvalidTransition("ResearchRun", current.value, action.value)

    if waiting_reason is not None:
        raise InvariantViolation("waiting_reason is valid only for wait_for_input.")
    return ResearchRunTransition(target)
