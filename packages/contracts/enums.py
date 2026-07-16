"""Closed public enums. Values are API compatibility surface."""

from enum import StrEnum


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    ANALYST = "analyst"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class WorkspaceStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class WatchlistStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class WatchlistCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MANUAL = "manual"


class InitialBaselineStatus(StrEnum):
    COLLECTING = "collecting"
    READY = "ready"
    INSUFFICIENT = "insufficient"


class SourceKind(StrEnum):
    CLOUD = "cloud"
    LOCAL = "local"
    IMPORTED_DATASET = "imported_dataset"


class SourceConnectorType(StrEnum):
    GITHUB = "github"
    RSS = "rss"
    CSV = "csv"
    SEED_FIXTURE = "seed_fixture"


class SourceRuntime(StrEnum):
    CLOUD = "cloud"
    MAC_DEVICE = "mac_device"
    STATIC_IMPORT = "static_import"


class SourceStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    AUTH_REQUIRED = "auth_required"
    DISABLED = "disabled"
    FAILED = "failed"


class SourceFreshnessState(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    NEVER = "never"


class SourceHealthState(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"
    DISABLED = "disabled"


class SourceValidationCommand(StrEnum):
    HEALTH_CHECK = "health_check"
    RECONNECT = "reconnect"


class SourceValidationJobState(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"


class ConnectorCapability(StrEnum):
    SEARCH = "search"
    FETCH = "fetch"
    HEALTH = "health"


class DataAuthenticity(StrEnum):
    SEED = "seed"
    IMPORTED = "imported"
    COLLECTED = "collected"
    GENERATED = "generated"
    HUMAN_AUTHORED = "human_authored"


class DataScope(StrEnum):
    PUBLIC = "public"
    WORKSPACE_CONFIDENTIAL = "workspace_confidential"
    RESTRICTED = "restricted"
    LOCAL_ONLY = "local_only"
    SEED = "seed"


class ContentAvailability(StrEnum):
    CAPTURED = "captured"
    DELETED = "deleted"
    UNAVAILABLE = "unavailable"


class CollectionRunState(StrEnum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MisfirePolicy(StrEnum):
    SKIP = "skip"
    RUN_ONCE = "run_once"


class OverlapPolicy(StrEnum):
    SKIP = "skip"
    QUEUE_ONE = "queue_one"


class ImportSessionState(StrEnum):
    DRAFT = "draft"
    CONSENTED = "consented"
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    FINALIZED = "finalized"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImportFinalizationJobState(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"


class TransferConsentDecision(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"


class ModelEgressAuthorization(StrEnum):
    NONE = "none"


class SignalStatus(StrEnum):
    NEW = "new"
    TRIAGED = "triaged"
    INVESTIGATING = "investigating"
    EXPLAINED = "explained"
    MONITORING = "monitoring"
    DISMISSED = "dismissed"


class SignalTransition(StrEnum):
    INVESTIGATE = "investigate"
    EXPLAIN = "explain"
    MONITOR = "monitor"
    DISMISS = "dismiss"
    UNDO = "undo"


class SignalDismissReason(StrEnum):
    DUPLICATE = "duplicate"
    SINGLE_AUTHOR_SPIKE = "single_author_spike"
    IRRELEVANT = "irrelevant"
    KNOWN_ISSUE = "known_issue"
    BAD_DATA = "bad_data"
    OTHER = "other"


class SignalEvidenceRole(StrEnum):
    TRIGGER = "trigger"
    SUPPORTING = "supporting"
    COUNTER = "counter"
    EXCLUDED = "excluded"


class DetectionConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CalibrationStatus(StrEnum):
    UNCALIBRATED = "uncalibrated"
    CALIBRATED = "calibrated"


class BusinessImpactLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class UrgencyLevel(StrEnum):
    NOW = "now"
    THIS_WEEK = "this_week"
    MONITOR = "monitor"
    UNKNOWN = "unknown"


class SuggestionOrigin(StrEnum):
    DETERMINISTIC_RULE = "deterministic_rule"
    MODEL = "model"
    NONE = "none"


class PriorityLevel(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class PriorityStatus(StrEnum):
    PENDING_CONFIRMATION = "pending_confirmation"
    INSUFFICIENT_INPUT = "insufficient_input"
    DERIVED = "derived"


class SignalAssessmentDimension(StrEnum):
    BUSINESS_IMPACT = "business_impact"
    URGENCY = "urgency"


class InvestigationStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    NEEDS_INPUT = "needs_input"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    CLOSED_INSUFFICIENT = "closed_insufficient"
    CANCELLED = "cancelled"


class InvestigationTransition(StrEnum):
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


class WaitingForInputReason(StrEnum):
    SCOPE_CLARIFICATION = "scope_clarification"
    PLAN_CHANGE = "plan_change"
    BUDGET_CHANGE = "budget_change"
    CLAIM_REVIEW = "claim_review"
    SOURCE_POLICY = "source_policy"


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    NEUTRAL = "neutral"


class EvidenceReviewProjection(StrEnum):
    PROPOSED = "proposed"
    VALID = "valid"
    WEAK = "weak"
    REJECTED = "rejected"


class EvidenceReviewDecision(StrEnum):
    VALID = "valid"
    WEAK = "weak"
    REJECTED = "rejected"


class ClaimType(StrEnum):
    OBSERVATION = "observation"
    PRODUCT_RISK = "product_risk"


class ClaimConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ClaimReviewProjection(StrEnum):
    PROPOSED = "proposed"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ClaimReviewDecision(StrEnum):
    VERIFY = "verify"
    REJECT = "reject"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"


class GenerationMethod(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL = "model"
    HUMAN = "human"


class SynthesisReviewProjection(StrEnum):
    DRAFT = "draft"
    NEEDS_REVIEW = "needs_review"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class SynthesisReviewDecision(StrEnum):
    VERIFY = "verify"
    REJECT = "reject"


class DecisionBriefStatus(StrEnum):
    DRAFT = "draft"
    DECISION_READY = "decision_ready"
    DECIDED = "decided"
    ARCHIVED = "archived"


class DecisionBriefReadinessProjection(StrEnum):
    DRAFT = "draft"
    DECISION_READY = "decision_ready"


class DecisionBriefReadinessDecision(StrEnum):
    MARK_DECISION_READY = "mark_decision_ready"
    REJECT = "reject"


class DecisionBriefFreshnessStatus(StrEnum):
    CURRENT = "current"
    EVIDENCE_STALE = "evidence_stale"


class BriefBlockType(StrEnum):
    FACT = "fact"
    SYNTHESIS = "synthesis"
    PM_JUDGMENT = "pm_judgment"
    RECOMMENDATION = "recommendation"


class RecommendationStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class BriefExportType(StrEnum):
    PRD_RESEARCH_INPUT_MARKDOWN = "prd_research_input_markdown"


class BriefExportDestination(StrEnum):
    LOCAL_DOWNLOAD = "local_download"
    COPY_MARKDOWN = "copy_markdown"


class ErrorCode(StrEnum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INVALID_STATE = "INVALID_STATE"
    ACTIVE_IMPORT_EXISTS = "ACTIVE_IMPORT_EXISTS"
    STALE_SOURCE_VERSION = "STALE_SOURCE_VERSION"
    CONSENT_EXPIRED_OR_REVOKED = "CONSENT_EXPIRED_OR_REVOKED"
    OBJECT_SCOPE_MISMATCH = "OBJECT_SCOPE_MISMATCH"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    SOURCE_SCOPE_BLOCKED = "SOURCE_SCOPE_BLOCKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class BusinessRunEventType(StrEnum):
    INVESTIGATION_STARTED_FROM_SIGNAL = "investigation.started_from_signal"
    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    RUN_WAITING_FOR_INPUT = "run.waiting_for_input"
    RUN_RESUMED = "run.resumed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    EVIDENCE_PROPOSED = "evidence.proposed"
    EVIDENCE_REVIEWED = "evidence.reviewed"
    CLAIM_VERSION_PROPOSED = "claim.version_proposed"
    CLAIM_VERSION_REVIEWED = "claim.version_reviewed"
    CLAIM_VERSION_SUPERSEDED = "claim.version_superseded"
    SYNTHESIS_PROPOSED = "synthesis.proposed"
    SYNTHESIS_REVIEWED = "synthesis.reviewed"
    REVIEW_REQUIRED = "review.required"


class StreamControlEventType(StrEnum):
    RESET = "stream.reset"


def assert_domain_enum_compatibility() -> None:
    """Assert transport enums have not drifted from the dependency-free domain package."""

    from packages.domain import (  # imported lazily so schema discovery stays lightweight
        BriefBlockType as DomainBriefBlockType,
    )
    from packages.domain import (
        BriefFreshness as DomainBriefFreshness,
    )
    from packages.domain import (
        BriefReadiness as DomainBriefReadiness,
    )
    from packages.domain import (
        BusinessImpact as DomainBusinessImpact,
    )
    from packages.domain import (
        ConsentDecision as DomainConsentDecision,
    )
    from packages.domain import (
        EvidenceStance as DomainEvidenceStance,
    )
    from packages.domain import (
        ExportDestination as DomainExportDestination,
    )
    from packages.domain import (
        ExportType as DomainExportType,
    )
    from packages.domain import (
        GenerationMethod as DomainGenerationMethod,
    )
    from packages.domain import (
        HeuristicLevel as DomainHeuristicLevel,
    )
    from packages.domain import (
        ImportState as DomainImportState,
    )
    from packages.domain import (
        InvestigationAction as DomainInvestigationAction,
    )
    from packages.domain import (
        InvestigationState as DomainInvestigationState,
    )
    from packages.domain import (
        ModelEgressAuthorization as DomainModelEgressAuthorization,
    )
    from packages.domain import (
        Priority as DomainPriority,
    )
    from packages.domain import (
        PriorityStatus as DomainPriorityStatus,
    )
    from packages.domain import (
        RecommendationStatus as DomainRecommendationStatus,
    )
    from packages.domain import (
        ResearchRunState as DomainResearchRunState,
    )
    from packages.domain import (
        ReviewDecision as DomainReviewDecision,
    )
    from packages.domain import (
        Urgency as DomainUrgency,
    )
    from packages.domain import (
        WaitingReason as DomainWaitingReason,
    )

    pairs = (
        (ImportSessionState, DomainImportState),
        (TransferConsentDecision, DomainConsentDecision),
        (ModelEgressAuthorization, DomainModelEgressAuthorization),
        (InvestigationStatus, DomainInvestigationState),
        (InvestigationTransition, DomainInvestigationAction),
        (ResearchRunState, DomainResearchRunState),
        (WaitingForInputReason, DomainWaitingReason),
        (BusinessImpactLevel, DomainBusinessImpact),
        (UrgencyLevel, DomainUrgency),
        (PriorityLevel, DomainPriority),
        (PriorityStatus, DomainPriorityStatus),
        (DetectionConfidenceLevel, DomainHeuristicLevel),
        (ClaimConfidenceLevel, DomainHeuristicLevel),
        (EvidenceStance, DomainEvidenceStance),
        (GenerationMethod, DomainGenerationMethod),
        (BriefBlockType, DomainBriefBlockType),
        (RecommendationStatus, DomainRecommendationStatus),
        (DecisionBriefReadinessProjection, DomainBriefReadiness),
        (DecisionBriefFreshnessStatus, DomainBriefFreshness),
        (BriefExportType, DomainExportType),
        (BriefExportDestination, DomainExportDestination),
        (SynthesisReviewDecision, DomainReviewDecision),
    )
    for contract_enum, domain_enum in pairs:
        contract_values = {member.value for member in contract_enum}
        domain_values = {member.value for member in domain_enum}
        if contract_values != domain_values:
            raise AssertionError(
                f"enum drift for {contract_enum.__name__}: "
                f"contract={sorted(contract_values)}, domain={sorted(domain_values)}"
            )
