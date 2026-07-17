"""Closed public enums for the PokieQuant Phase 0 wire surface."""

from enum import StrEnum


class QuantProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class QuantRunMode(StrEnum):
    PLAN = "plan"
    AUTO = "auto"


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
    RESEARCH_REPORT = "research_report"
    EXECUTION_LOG = "execution_log"
    DIAGNOSTICS = "diagnostics"


class QuantArtifactReviewStatus(StrEnum):
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class QuantArtifactStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    REVIEWED = "reviewed"
    REJECTED = "rejected"


class QuantCandidateVerdict(StrEnum):
    PROMISING = "promising"
    INCONCLUSIVE = "inconclusive"
    REJECTED = "rejected"
    INVALID = "invalid"


class QuantDataAuthenticity(StrEnum):
    SYNTHETIC_FIXTURE = "synthetic_fixture"
    IMPORTED_FIXTURE = "imported_fixture"


class QuantStepStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class QuantFixtureScenario(StrEnum):
    NORMAL = "normal"
    NO_VIABLE = "no_viable"
    FAILED_SAFE = "failed_safe"
    CANCELLED = "cancelled"


class QuantEventType(StrEnum):
    RUN_CREATED = "run.created"
    PLAN_GENERATED = "plan.generated"
    REVIEW_REQUIRED = "review.required"
    PLAN_APPROVED = "plan.approved"
    DATA_LOAD_STARTED = "data.load.started"
    DATA_LOAD_COMPLETED = "data.load.completed"
    BENCHMARK_GENERATED = "benchmark.generated"
    CANDIDATE_GENERATED = "candidate.generated"
    BACKTEST_STARTED = "backtest.started"
    BACKTEST_COMPLETED = "backtest.completed"
    BACKTEST_FAILED = "backtest.failed"
    REPAIR_STARTED = "repair.started"
    REPAIR_COMPLETED = "repair.completed"
    VALIDATION_STARTED = "validation.started"
    CANDIDATE_REJECTED = "candidate.rejected"
    CANDIDATE_PROMOTED = "candidate.promoted"
    VALIDATION_COMPLETED = "validation.completed"
    REPORT_GENERATED = "report.generated"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"


class QuantRunEventType(StrEnum):
    RUN_QUEUED = "run.queued"
    PLAN_PROPOSED = "plan.proposed"
    PLAN_AWAITING_APPROVAL = "plan.awaiting_approval"
    PLAN_APPROVED = "plan.approved"
    PLAN_CHANGES_REQUESTED = "plan.changes_requested"
    RUN_STARTED = "run.started"
    EXPERIMENT_PROPOSED = "experiment.proposed"
    EXPERIMENT_VERDICT_RECORDED = "experiment.verdict_recorded"
    ARTIFACT_PUBLISHED = "artifact.published"
    AGENT_CONTEXT_BUILT = "agent.context_built"
    AGENT_DECISION_STARTED = "agent.decision_started"
    AGENT_ACTION_SELECTED = "agent.action_selected"
    AGENT_DECISION_FAILED = "agent.decision_failed"
    AGENT_PROVIDER_FALLBACK = "agent.provider_fallback"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    CANDIDATE_GENERATED = "candidate.generated"
    CANDIDATE_REVISED = "candidate.revised"
    BACKTEST_STARTED = "backtest.started"
    BACKTEST_COMPLETED = "backtest.completed"
    BACKTEST_FAILED = "backtest.failed"
    REPAIR_STARTED = "repair.started"
    REPAIR_COMPLETED = "repair.completed"
    COMPARISON_GENERATED = "comparison.generated"
    REPORT_GENERATED = "report.generated"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"


class QuantStreamControlEventType(StrEnum):
    RESET = "stream.reset"


def assert_quant_enum_compatibility() -> None:
    from packages.domain import quant as domain_quant

    pairs = (
        (QuantProjectStatus, domain_quant.QuantProjectStatus),
        (QuantRunMode, domain_quant.QuantRunMode),
        (QuantRunState, domain_quant.QuantRunState),
        (QuantPlanDecision, domain_quant.QuantPlanDecision),
        (QuantExperimentVerdict, domain_quant.QuantExperimentVerdict),
        (QuantArtifactKind, domain_quant.QuantArtifactKind),
    )
    for contract_enum, domain_enum in pairs:
        if {member.value for member in contract_enum} != {member.value for member in domain_enum}:
            raise AssertionError(
                f"enum drift for {contract_enum.__name__}: "
                f"contract={sorted(member.value for member in contract_enum)}, "
                f"domain={sorted(member.value for member in domain_enum)}"
            )
