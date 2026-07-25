"""PokieQuant Phase 0 deterministic Quant run kernel.

This module is dependency-free: persistence and transport layers import it, and
it never imports FastAPI, Pydantic, SQLAlchemy, or a worker runtime.  It owns
the canonical Quant run state machine, the closed fixture programs behind
``POKIEQUANT_E2E_RUN_STATE``, and the typed records shared by the API fixture
store and the deterministic fixture worker.  No market data access, broker
networking, execution, or trading semantics exist in this phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .canonical import canonical_digest
from .errors import InvalidTransition, InvariantViolation

QUANT_FIXTURE_STATE_ENV = "POKIEQUANT_E2E_RUN_STATE"
QUANT_STORE_PATH_ENV = "POKIEQUANT_STORE_PATH"


class QuantProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class QuantRunState(StrEnum):
    DRAFT = "draft"
    QUEUED = "queued"
    PLANNING = "planning"
    WAITING_PLAN_APPROVAL = "waiting_plan_approval"
    LOADING_DATA = "loading_data"
    GENERATING_CANDIDATES = "generating_candidates"
    RUNNING_EXPERIMENTS = "running_experiments"
    REPAIRING = "repairing"
    VALIDATING = "validating"
    GENERATING_REPORT = "generating_report"
    WAITING_FOR_REVIEW = "waiting_for_review"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class QuantRunAction(StrEnum):
    BEGIN_PLANNING = "begin_planning"
    PUBLISH_PLAN = "publish_plan"
    APPROVE_PLAN = "approve_plan"
    REQUEST_PLAN_CHANGES = "request_plan_changes"
    COMPLETE = "complete"
    FAIL = "fail"
    CANCEL = "cancel"


class QuantRunMode(StrEnum):
    PLAN = "plan"
    AUTO = "auto"


class QuantPlanDecision(StrEnum):
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


class QuantExperimentVerdict(StrEnum):
    VIABLE = "viable"
    NOT_VIABLE = "not_viable"
    REJECTED = "rejected"


class QuantArtifactKind(StrEnum):
    PLAN = "plan"
    RESEARCH_SCOPE = "research_scope"
    DATASET_SNAPSHOT = "dataset_snapshot"
    BENCHMARK = "benchmark"
    STRATEGY_SPEC = "strategy_spec"
    BACKTEST_RESULT = "backtest_result"
    BACKTEST_METRICS = "backtest_metrics"
    EQUITY_CURVE = "equity_curve"
    TRADE_LOG = "trade_log"
    VALIDATION_REPORT = "validation_report"
    ITERATION_FEEDBACK = "iteration_feedback"
    ROBUSTNESS_SENSITIVITY = "robustness_sensitivity"
    LEARNING_TRACE = "learning_trace"
    RESEARCH_REPORT = "research_report"
    EXECUTION_LOG = "execution_log"
    DIAGNOSTICS = "diagnostics"


class QuantArtifactReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class QuantFixtureRunState(StrEnum):
    """Closed deterministic programs selected by ``POKIEQUANT_E2E_RUN_STATE``."""

    COMPLETED = "completed"
    COMPLETED_NO_VIABLE_CANDIDATES = "completed_no_viable_candidates"
    COMPLETED_REJECTED_CANDIDATE = "completed_rejected_candidate"
    FAILED = "failed"


DEFAULT_QUANT_FIXTURE_RUN_STATE = QuantFixtureRunState.COMPLETED

TERMINAL_QUANT_RUN_STATES = frozenset(
    {QuantRunState.COMPLETED, QuantRunState.FAILED, QuantRunState.CANCELLED}
)
CANCELLABLE_QUANT_RUN_STATES = frozenset(
    {
        QuantRunState.QUEUED,
        QuantRunState.PLANNING,
        QuantRunState.WAITING_PLAN_APPROVAL,
        QuantRunState.RUNNING_EXPERIMENTS,
    }
)
PENDING_QUANT_RUN_STATES = frozenset(
    {QuantRunState.QUEUED, QuantRunState.PLANNING, QuantRunState.RUNNING_EXPERIMENTS}
)

_QUANT_RUN_TRANSITIONS: dict[tuple[QuantRunState, QuantRunAction], QuantRunState] = {
    (QuantRunState.QUEUED, QuantRunAction.BEGIN_PLANNING): QuantRunState.PLANNING,
    (QuantRunState.PLANNING, QuantRunAction.PUBLISH_PLAN): (QuantRunState.WAITING_PLAN_APPROVAL),
    (
        QuantRunState.WAITING_PLAN_APPROVAL,
        QuantRunAction.APPROVE_PLAN,
    ): QuantRunState.RUNNING_EXPERIMENTS,
    (QuantRunState.WAITING_PLAN_APPROVAL, QuantRunAction.REQUEST_PLAN_CHANGES): (
        QuantRunState.PLANNING
    ),
    (QuantRunState.RUNNING_EXPERIMENTS, QuantRunAction.COMPLETE): QuantRunState.COMPLETED,
    (QuantRunState.RUNNING_EXPERIMENTS, QuantRunAction.FAIL): QuantRunState.FAILED,
    (QuantRunState.PLANNING, QuantRunAction.FAIL): QuantRunState.FAILED,
}


def parse_quant_fixture_run_state(raw: str | None) -> QuantFixtureRunState:
    """Parse ``POKIEQUANT_E2E_RUN_STATE`` strictly; unknown values never silently pass."""

    if raw is None or not raw.strip():
        return DEFAULT_QUANT_FIXTURE_RUN_STATE
    try:
        return QuantFixtureRunState(raw.strip())
    except ValueError as exc:
        allowed = ", ".join(sorted(member.value for member in QuantFixtureRunState))
        raise InvariantViolation(
            f"{QUANT_FIXTURE_STATE_ENV} must be one of: {allowed}.",
            code="INVALID_FIXTURE_STATE",
        ) from exc


def transition_quant_run(current: QuantRunState, action: QuantRunAction) -> QuantRunState:
    """Apply one server-owned Quant run command to the canonical state machine."""

    try:
        current = QuantRunState(current)
        action = QuantRunAction(action)
    except ValueError as exc:
        raise InvariantViolation("Quant run transition contains an unknown value.") from exc
    if action is QuantRunAction.CANCEL:
        if current not in CANCELLABLE_QUANT_RUN_STATES:
            raise InvalidTransition("QuantRun", current.value, action.value)
        return QuantRunState.CANCELLED
    target = _QUANT_RUN_TRANSITIONS.get((current, action))
    if target is None:
        raise InvalidTransition("QuantRun", current.value, action.value)
    return target


@dataclass(frozen=True, slots=True)
class QuantPlanStep:
    """One deterministic fixture plan step; the server never invents steps at read time."""

    key: str
    title: str
    owner: str


@dataclass(frozen=True, slots=True)
class QuantPlan:
    revision: int
    question: str
    steps: tuple[QuantPlanStep, ...]

    def digest(self) -> str:
        return canonical_digest(
            {
                "revision": self.revision,
                "question": self.question,
                "steps": [
                    {"key": step.key, "title": step.title, "owner": step.owner}
                    for step in self.steps
                ],
            }
        )


_FIXTURE_PLAN_STEPS: tuple[QuantPlanStep, ...] = (
    QuantPlanStep("pin-dataset", "Pin the synthetic demo dataset snapshot", "fixture_worker"),
    QuantPlanStep("draft-hypotheses", "Draft bounded strategy hypotheses", "fixture_worker"),
    QuantPlanStep(
        "evaluate-candidates", "Evaluate candidates against fixture bars", "fixture_worker"
    ),
    QuantPlanStep("record-findings", "Record validation findings and verdicts", "fixture_worker"),
    QuantPlanStep("publish-report", "Publish the fixture research report", "fixture_worker"),
)


def build_fixture_plan(*, question: str, revision: int) -> QuantPlan:
    """Build the deterministic fixture plan for one revision of a Quant run."""

    if revision < 1:
        raise InvariantViolation("A Quant plan revision starts at 1.")
    return QuantPlan(revision=revision, question=question, steps=_FIXTURE_PLAN_STEPS)


@dataclass(frozen=True, slots=True)
class QuantFixtureExperiment:
    name: str
    hypothesis: str
    verdict: QuantExperimentVerdict
    summary: str


@dataclass(frozen=True, slots=True)
class QuantFixtureProgram:
    """The deterministic replay script for one ``POKIEQUANT_E2E_RUN_STATE`` value."""

    state: QuantFixtureRunState
    experiments: tuple[QuantFixtureExperiment, ...]
    artifact_kinds: tuple[QuantArtifactKind, ...]
    terminal_state: QuantRunState
    failure_reason: str | None = None


_FIXTURE_PROGRAMS: dict[QuantFixtureRunState, QuantFixtureProgram] = {
    QuantFixtureRunState.COMPLETED: QuantFixtureProgram(
        state=QuantFixtureRunState.COMPLETED,
        experiments=(
            QuantFixtureExperiment(
                name="fixture-momentum-baseline",
                hypothesis="Fixture momentum beats the pinned synthetic baseline window.",
                verdict=QuantExperimentVerdict.VIABLE,
                summary="Viable against the synthetic demo fixture; not market evidence.",
            ),
            QuantFixtureExperiment(
                name="fixture-mean-reversion",
                hypothesis="Fixture mean reversion beats the pinned synthetic baseline window.",
                verdict=QuantExperimentVerdict.NOT_VIABLE,
                summary="Not viable on the pinned synthetic fixture; retained as a negative result.",
            ),
        ),
        artifact_kinds=(
            QuantArtifactKind.DATASET_SNAPSHOT,
            QuantArtifactKind.BACKTEST_METRICS,
            QuantArtifactKind.TRADE_LOG,
            QuantArtifactKind.RESEARCH_REPORT,
        ),
        terminal_state=QuantRunState.COMPLETED,
    ),
    QuantFixtureRunState.COMPLETED_NO_VIABLE_CANDIDATES: QuantFixtureProgram(
        state=QuantFixtureRunState.COMPLETED_NO_VIABLE_CANDIDATES,
        experiments=(
            QuantFixtureExperiment(
                name="fixture-momentum-baseline",
                hypothesis="Fixture momentum beats the pinned synthetic baseline window.",
                verdict=QuantExperimentVerdict.NOT_VIABLE,
                summary="Not viable on the pinned synthetic fixture; the run still completes.",
            ),
        ),
        artifact_kinds=(
            QuantArtifactKind.DATASET_SNAPSHOT,
            QuantArtifactKind.BACKTEST_METRICS,
            QuantArtifactKind.RESEARCH_REPORT,
        ),
        terminal_state=QuantRunState.COMPLETED,
    ),
    QuantFixtureRunState.COMPLETED_REJECTED_CANDIDATE: QuantFixtureProgram(
        state=QuantFixtureRunState.COMPLETED_REJECTED_CANDIDATE,
        experiments=(
            QuantFixtureExperiment(
                name="fixture-overfit-candidate",
                hypothesis="An overfit fixture candidate passes pinned validation.",
                verdict=QuantExperimentVerdict.REJECTED,
                summary="Rejected by deterministic fixture validation; the run does not fail.",
            ),
            QuantFixtureExperiment(
                name="fixture-momentum-baseline",
                hypothesis="Fixture momentum beats the pinned synthetic baseline window.",
                verdict=QuantExperimentVerdict.VIABLE,
                summary="Viable against the synthetic demo fixture; not market evidence.",
            ),
        ),
        artifact_kinds=(
            QuantArtifactKind.DATASET_SNAPSHOT,
            QuantArtifactKind.BACKTEST_METRICS,
            QuantArtifactKind.TRADE_LOG,
            QuantArtifactKind.RESEARCH_REPORT,
        ),
        terminal_state=QuantRunState.COMPLETED,
    ),
    QuantFixtureRunState.FAILED: QuantFixtureProgram(
        state=QuantFixtureRunState.FAILED,
        experiments=(
            QuantFixtureExperiment(
                name="fixture-momentum-baseline",
                hypothesis="Fixture momentum beats the pinned synthetic baseline window.",
                verdict=QuantExperimentVerdict.REJECTED,
                summary="Evaluation halted by the deterministic fixture failure injection.",
            ),
        ),
        artifact_kinds=(QuantArtifactKind.DATASET_SNAPSHOT,),
        terminal_state=QuantRunState.FAILED,
        failure_reason="Deterministic fixture failure requested by POKIEQUANT_E2E_RUN_STATE=failed.",
    ),
}


def quant_fixture_program(state: QuantFixtureRunState) -> QuantFixtureProgram:
    """Return the closed deterministic program for one fixture run state."""

    try:
        state = QuantFixtureRunState(state)
    except ValueError as exc:
        raise InvariantViolation("Unknown Quant fixture run state.") from exc
    return _FIXTURE_PROGRAMS[state]


@dataclass(slots=True)
class QuantProjectRecord:
    id: str
    workspace_id: str
    name: str
    objective: str
    created_at: str
    updated_at: str
    status: str = QuantProjectStatus.ACTIVE.value
    row_version: int = 1
    data_authenticity: str = "generated"


@dataclass(slots=True)
class QuantRunRecord:
    id: str
    workspace_id: str
    project_id: str
    question: str
    mode: str
    trace_id: str
    created_at: str
    updated_at: str
    state: str = QuantRunState.QUEUED.value
    plan_revision: int = 0
    attempt_number: int = 1
    retry_of_run_id: str | None = None
    latest_sequence: int = 0
    failure_reason: str | None = None
    worker_attempt_id: str | None = None
    row_version: int = 1
    data_authenticity: str = "generated"


@dataclass(slots=True)
class QuantEventRecord:
    id: str
    workspace_id: str
    quant_run_id: str
    sequence: int
    event_id: str
    idempotency_key: str
    type: str
    payload_json: dict[str, Any]
    trace_id: str
    occurred_at: str
    data_authenticity: str = "generated"


@dataclass(slots=True)
class QuantPlanDecisionRecord:
    id: str
    workspace_id: str
    quant_run_id: str
    plan_revision: int
    decision: str
    actor_id: str
    reason: str
    request_id: str
    occurred_at: str
    data_authenticity: str = "human_authored"


@dataclass(slots=True)
class QuantExperimentRecord:
    id: str
    workspace_id: str
    quant_run_id: str
    ordinal: int
    name: str
    hypothesis: str
    verdict: str
    summary: str
    created_at: str
    data_authenticity: str = "generated"


@dataclass(slots=True)
class QuantArtifactRecord:
    id: str
    workspace_id: str
    quant_run_id: str
    ordinal: int
    kind: str
    title: str
    digest: str
    created_at: str
    review_status: str = QuantArtifactReviewStatus.UNREVIEWED.value
    data_authenticity: str = "generated"


def fixture_artifact_payload(
    *, run_id: str, attempt_number: int, kind: QuantArtifactKind
) -> dict[str, Any]:
    """Return the deterministic, clearly synthetic artifact body for one kind."""

    try:
        kind = QuantArtifactKind(kind)
    except ValueError as exc:
        raise InvariantViolation("Unknown Quant artifact kind.") from exc
    base: dict[str, Any] = {
        "authenticity_notice": "Synthetic Demo Fixture",
        "quant_run_id": run_id,
        "attempt_number": attempt_number,
        "kind": kind.value,
        "live_market_data": False,
    }
    if kind is QuantArtifactKind.DATASET_SNAPSHOT:
        return {
            **base,
            "symbol": "SPY",
            "source": "synthetic_fixture",
            "bar_count": 64,
            "first_bar": "2026-01-05T00:00:00Z",
            "last_bar": "2026-04-01T00:00:00Z",
        }
    if kind is QuantArtifactKind.BACKTEST_METRICS:
        return {
            **base,
            "engine": "deterministic-fixture-evaluator-v1",
            "metrics": {
                "total_return": "0.0312",
                "max_drawdown": "-0.0118",
                "win_rate": "0.55",
                "trade_count": 20,
            },
        }
    if kind is QuantArtifactKind.TRADE_LOG:
        return {
            **base,
            "trades": [
                {"ordinal": index, "side": side, "quantity": 10, "price": price}
                for index, (side, price) in enumerate(
                    (
                        ("buy", "100.00"),
                        ("sell", "101.25"),
                        ("buy", "99.50"),
                        ("sell", "100.75"),
                    ),
                    start=1,
                )
            ],
        }
    if kind is QuantArtifactKind.RESEARCH_REPORT:
        return {
            **base,
            "title": "Synthetic Demo Fixture research report",
            "conclusion": (
                "Deterministic fixture conclusion retained for audit; "
                "it is not investment advice and uses no market data."
            ),
        }
    raise InvariantViolation("Plan artifacts carry the plan digest, not a fixture payload.")


@dataclass(frozen=True, slots=True)
class QuantStoreSnapshot:
    """Serializable store image used for deterministic durability and recovery."""

    projects: tuple[QuantProjectRecord, ...] = ()
    runs: tuple[QuantRunRecord, ...] = ()
    events: tuple[QuantEventRecord, ...] = ()
    plan_decisions: tuple[QuantPlanDecisionRecord, ...] = ()
    experiments: tuple[QuantExperimentRecord, ...] = ()
    artifacts: tuple[QuantArtifactRecord, ...] = ()
    schema_version: int = 1
    extra: dict[str, Any] = field(default_factory=dict)
