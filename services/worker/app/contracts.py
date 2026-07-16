"""Worker-owned contracts used until the API domain services are wired in.

These classes intentionally model the boundary described in the Phase 0 docs:
workers receive typed immutable inputs, write through a domain adapter, and
never use ImportSession IDs outside the dedicated finalization job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4


class DataAuthenticity(StrEnum):
    SEED = "seed"
    IMPORTED = "imported"
    COLLECTED = "collected"
    GENERATED = "generated"
    HUMAN_AUTHORED = "human_authored"


class ImportSessionState(StrEnum):
    DRAFT = "draft"
    CONSENTED = "consented"
    UPLOADED = "uploaded"
    VALIDATING = "validating"
    FINALIZED = "finalized"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConsentDecision(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"


class ResearchRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_INPUT = "waiting_for_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    DISABLED = "disabled"


class WorkerContractError(RuntimeError):
    """Base error for worker contract violations."""


class NonTerminalImportError(WorkerContractError):
    """Raised when a downstream pipeline receives anything but a manifest ID."""


class ConsentError(WorkerContractError):
    """Raised when no effective transfer consent exists."""


class ObjectVerificationError(WorkerContractError):
    """Raised when uploaded bytes do not match pinned consent/session values."""


class ObjectNotFoundError(ObjectVerificationError):
    """Raised when staged object bytes are missing."""


class SourcePointerError(WorkerContractError):
    """Raised when an import cannot compare-and-set the source pointer."""


class RetryableJobError(WorkerContractError):
    """Raised when a job can retry with the same pinned inputs."""


class ObjectUnavailableError(RetryableJobError):
    """Raised when object storage is temporarily unavailable."""


def now_utc() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class UploadObjectScope:
    object_key: str
    max_bytes: int
    media_type: str


@dataclass(slots=True)
class SourceConnection:
    id: str
    workspace_id: str
    source_kind: str
    runtime: str
    connector_type: str
    connector_version: str
    status: SourceHealthStatus = SourceHealthStatus.HEALTHY
    credential_ref: str | None = None
    data_scope: str = "workspace_confidential"
    current_import_manifest_id: str | None = None
    row_version: int = 1
    data_authenticity: DataAuthenticity = DataAuthenticity.COLLECTED
    freshness: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImportSession:
    id: str
    workspace_id: str
    source_connection_id: str
    expected_source_row_version: int
    expected_current_import_manifest_id: str | None
    local_manifest_digest: str
    file_digest: str
    expected_upload_digest: str
    client_file_name: str
    file_size_bytes: int
    media_type: str
    parser_version: str
    schema_version: str
    selected_scope_json: dict[str, Any]
    selected_scope_digest: str
    state: ImportSessionState = ImportSessionState.DRAFT
    uploaded_object_key: str | None = None
    uploaded_object_digest: str | None = None
    terminal_manifest_id: str | None = None
    failure_code: str | None = None
    retryable: bool = False
    row_version: int = 1
    data_authenticity: DataAuthenticity = DataAuthenticity.IMPORTED


@dataclass(slots=True)
class TransferConsentRecord:
    id: str
    workspace_id: str
    import_session_id: str
    decision: ConsentDecision
    local_manifest_digest: str
    file_digest: str
    expected_upload_digest: str
    selected_scope_digest: str
    destination_workspace_id: str
    upload_object_scope: UploadObjectScope
    model_egress_authorization: str
    policy_version: str
    actor_id: str
    recorded_at: datetime
    expires_at: datetime
    supersedes_id: str | None = None
    data_authenticity: DataAuthenticity = DataAuthenticity.IMPORTED


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    body: bytes
    digest: str
    size_bytes: int
    media_type: str


@dataclass(frozen=True, slots=True)
class ImportManifest:
    id: str
    workspace_id: str
    import_session_id: str
    source_connection_id: str
    file_digest: str
    uploaded_object_key: str
    uploaded_object_digest: str
    parser_version: str
    schema_version: str
    selected_scope_digest: str
    consent_record_id: str
    normalized_payload_digest: str
    content_count: int
    finalized_at: datetime
    data_authenticity: DataAuthenticity


@dataclass(frozen=True, slots=True)
class RawContentItem:
    id: str
    workspace_id: str
    source_connection_id: str
    source_item_id: str
    title: str
    body: str
    canonical_url: str | None
    author: str | None
    published_at: datetime | None
    captured_at: datetime
    content_digest: str
    data_authenticity: DataAuthenticity
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceRefetchTarget:
    source_item_id: str
    current_content_version_id: str
    canonical_url: str | None = None
    checked_at: datetime | None = None


@dataclass(slots=True)
class ContentItem:
    id: str
    workspace_id: str
    source_connection_id: str
    source_item_id: str
    canonical_url: str | None
    identity_key: str
    title: str
    current_version_id: str
    duplicate_cluster_id: str | None
    independence_group_id: str | None
    data_authenticity: DataAuthenticity


@dataclass(frozen=True, slots=True)
class ContentVersion:
    id: str
    workspace_id: str
    content_item_id: str
    version_number: int
    content_digest: str
    normalized_title: str
    normalized_body: str
    captured_at: datetime
    parser_version: str
    canonical_url: str | None
    author: str | None
    data_authenticity: DataAuthenticity
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Signal:
    id: str
    workspace_id: str
    watchlist_id: str
    title: str
    detector_version: str
    detection_window: tuple[datetime, datetime]
    baseline_window: tuple[datetime, datetime]
    metrics: dict[str, Any]
    dimensions: dict[str, Any]
    explanation: str
    content_version_ids: tuple[str, ...]
    data_authenticity: DataAuthenticity


@dataclass(frozen=True, slots=True)
class SignalPersistenceResult:
    signal_id: str
    created: bool
    suppressed_reason: str | None = None
    existing_signal_id: str | None = None
    cooldown_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class InitialBaselineProjection:
    status: str
    current_count: int
    required_count: int
    candidate_count: int
    expected_detectable_at: datetime | None = None
    reason: str | None = None
    last_terminal_run_at: datetime | None = None


@dataclass(slots=True)
class ResearchRun:
    id: str
    workspace_id: str
    investigation_id: str
    investigation_scope_version_id: str
    state: ResearchRunState
    graph_version: str
    run_input_manifest_digest: str
    source_manifest_id: str | None
    content_version_ids: tuple[str, ...]
    data_authenticity: DataAuthenticity
    row_version: int = 1


@dataclass(frozen=True, slots=True)
class RunEvent:
    event_id: str
    run_id: str
    sequence: int
    timestamp: datetime
    event_type: str
    payload: dict[str, Any]
    trace_id: str


@dataclass(frozen=True, slots=True)
class EvidenceProposal:
    id: str
    workspace_id: str
    investigation_id: str
    research_run_id: str
    content_version_id: str
    quote_start: int
    quote_end: int
    quote_text_digest: str
    stance: str
    extraction_method: str
    injection_flags: tuple[str, ...]
    data_authenticity: DataAuthenticity


@dataclass(frozen=True, slots=True)
class ClaimVersionProposal:
    id: str
    claim_id: str
    research_run_id: str
    text: str
    confidence_level: str
    confidence_inputs: dict[str, Any]
    limitations: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    generation_method: str
    generator_version: str
    data_authenticity: DataAuthenticity


@dataclass(frozen=True, slots=True)
class SynthesisProposal:
    id: str
    research_run_id: str
    executive_summary: str
    business_implications: tuple[str, ...]
    limitations: tuple[str, ...]
    verified_claim_version_ids: tuple[str, ...]
    generation_method: str
    generator_version: str
    data_authenticity: DataAuthenticity


@dataclass(frozen=True, slots=True)
class ImportFinalizationCommand:
    workspace_id: str
    import_session_id: str
    finalize_command_id: str
    expected_session_row_version: int
    expected_source_row_version: int
    expected_current_import_manifest_id: str | None
    consent_record_id: str | None = None
    actor_id: str = "worker"
    request_id: str = "worker"
    lease_token: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ImportFinalizationCommand:
        return cls(
            workspace_id=value["workspace_id"],
            import_session_id=value["import_session_id"],
            finalize_command_id=value.get("finalize_command_id")
            or value.get("command_id")
            or value["id"],
            expected_session_row_version=value["expected_session_row_version"],
            expected_source_row_version=value["expected_source_row_version"],
            expected_current_import_manifest_id=value.get("expected_current_import_manifest_id")
            if "expected_current_import_manifest_id" in value
            else value.get("expected_source_manifest_id"),
            consent_record_id=value.get("consent_record_id"),
            actor_id=value.get("actor_id") or "worker",
            request_id=value.get("request_id") or "worker",
            lease_token=value.get("lease_token"),
        )


@dataclass(frozen=True, slots=True)
class ManifestProcessingCommand:
    workspace_id: str
    import_manifest_id: str
    command_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True, slots=True)
class ScheduledCollectionClaim:
    schedule_id: str
    lease_token: str
    command: Any


@dataclass(frozen=True, slots=True)
class CollectionLeaseContext:
    collection_run_id: str
    schedule_id: str
    schedule_lease_token: str
    schedule_fencing_version: int


@dataclass(frozen=True, slots=True)
class ResearchRunClaim:
    run_id: str
    worker_attempt_id: str
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class SourceValidationClaim:
    job_id: str
    workspace_id: str
    source_connection_id: str
    command: str
    connector_config: dict[str, Any]
    lease_token: str
    attempt: int
    fencing_version: int
    lease_expires_at: datetime


class ObjectStore(Protocol):
    def get_import_object(
        self,
        *,
        workspace_id: str,
        import_session_id: str,
        key: str,
    ) -> StoredObject:
        """Return bytes only after exact workspace/import-key containment."""
        ...

    def quarantine_import_object(
        self,
        *,
        workspace_id: str,
        import_session_id: str,
        key: str,
        reason: str,
    ) -> None:
        """Quarantine bytes only after exact workspace/import-key containment."""
        ...


class WorkerDomainAdapter(Protocol):
    """Minimal domain-service protocol for P1/P2 worker integration."""

    def claim_next_import_finalization_command(
        self,
        worker_id: str,
        lease_for: timedelta,
    ) -> ImportFinalizationCommand | None:
        """Claim one queued/retryable import finalization command for this worker."""
        ...

    def replay_completed_import_finalization(
        self,
        command: ImportFinalizationCommand,
    ) -> ImportManifest | None:
        """Return the completed manifest for an already successful command replay."""
        ...

    def heartbeat_import_finalization(
        self,
        command: ImportFinalizationCommand,
        now: datetime,
        lease_for: timedelta,
    ) -> None:
        """Extend a claimed import finalization lease."""
        ...

    def get_import_session_for_finalization(
        self, command: ImportFinalizationCommand
    ) -> ImportSession:
        """Resolve an ImportSession only for ImportFinalizationJob."""
        ...

    def get_source_connection(self, source_connection_id: str) -> SourceConnection:
        """Fetch a source connection for validation and compare-and-set."""
        ...

    def resolve_effective_consent(
        self,
        session: ImportSession,
        at: datetime,
    ) -> TransferConsentRecord:
        """Return the exact unexpired grant or raise ConsentError."""
        ...

    def finalize_import(
        self,
        command: ImportFinalizationCommand,
        manifest: ImportManifest,
        raw_items: list[RawContentItem],
        content_items: list[ContentItem],
        content_versions: list[ContentVersion],
    ) -> ImportManifest:
        """Atomically create visible content, terminal manifest, and source pointer."""
        ...

    def fail_import_finalization(
        self,
        command: ImportFinalizationCommand,
        failure_code: str,
        retryable: bool,
    ) -> None:
        """Fail one claimed finalization command and mark session failed when appropriate."""
        ...

    def fail_import_session(
        self,
        session_id: str,
        failure_code: str,
        retryable: bool,
    ) -> None:
        """Legacy test helper: mark import session failed without a command."""
        ...

    def cancel_import_session(self, session_id: str, reason: str) -> None:
        """Cancel an unfinished session and ensure zero manifest/content."""
        ...

    def get_terminal_manifest(self, manifest_id: str) -> ImportManifest:
        """Resolve only finalized manifests for downstream jobs."""
        ...

    def get_content_versions_for_manifest(self, manifest_id: str) -> list[ContentVersion]:
        """Return frozen ContentVersions created by a terminal manifest."""
        ...

    def upsert_collected_raw_items(
        self,
        workspace_id: str,
        source_connection_id: str,
        items: list[RawContentItem],
        collection_key: str,
        lease: CollectionLeaseContext,
    ) -> list[ContentVersion]:
        """Persist connector output idempotently and return immutable versions."""
        ...

    def get_signal_candidate_versions(
        self,
        workspace_id: str,
        watchlist_id: str,
        terms: tuple[str, ...],
        current_window: tuple[datetime, datetime],
        baseline_window: tuple[datetime, datetime],
        collection_key: str,
        lease: CollectionLeaseContext,
    ) -> list[ContentVersion]:
        """Return frozen current/baseline versions across approved watchlist sources."""
        ...

    def get_initial_baseline_projection(
        self,
        workspace_id: str,
        watchlist_id: str,
        collection_key: str,
        lease: CollectionLeaseContext,
        current_candidate_count: int,
    ) -> InitialBaselineProjection:
        """Return the worker-side equivalent of the public initial-baseline projection."""
        ...

    def get_source_refetch_targets(
        self,
        workspace_id: str,
        source_connection_id: str,
        collection_key: str,
        lease: CollectionLeaseContext,
        limit: int,
    ) -> list[SourceRefetchTarget]:
        """Return bounded current external IDs for deleted/unavailable refetch checks."""
        ...

    def persist_dedupe_assignments(
        self,
        workspace_id: str,
        assignments: dict[str, dict[str, str]],
        collection_key: str,
        lease: CollectionLeaseContext,
    ) -> None:
        """Persist duplicate cluster IDs and durable independence-group evidence."""
        ...

    def begin_collection_run(
        self,
        workspace_id: str,
        source_connection_id: str,
        stable_key: str,
        metadata: dict[str, Any],
    ) -> str:
        """Create or mark running a CollectionRun and return its ID."""
        ...

    def complete_collection_run(
        self,
        lease: CollectionLeaseContext,
        state: str,
        counters: dict[str, Any],
        freshness: dict[str, Any],
        failure_code: str | None = None,
    ) -> None:
        """Persist collection input/output/dedupe/signal counters and freshness."""
        ...

    def claim_due_collection_schedule(
        self,
        worker_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> ScheduledCollectionClaim | None:
        """Atomically claim one due collection schedule or scheduled run."""
        ...

    def heartbeat_collection_schedule(
        self,
        schedule_id: str,
        lease_token: str,
        now: datetime,
        lease_for: timedelta,
    ) -> None:
        """Extend a repository-backed schedule lease."""
        ...

    def release_collection_schedule(self, schedule_id: str, lease_token: str) -> None:
        """Release an exact repository-backed schedule lease."""
        ...

    def complete_collection_schedule(
        self,
        schedule_id: str,
        lease_token: str,
        success: bool,
        next_run_at: datetime | None,
        now: datetime | None = None,
    ) -> None:
        """Advance or fail a claimed schedule after enqueue/collection outcome."""
        ...

    def update_source_health(
        self,
        source_connection_id: str,
        status: SourceHealthStatus,
        details: dict[str, Any],
        lease: CollectionLeaseContext,
    ) -> None:
        """Persist source health/freshness without exposing credentials."""
        ...

    def create_signal(
        self, signal: Signal, lease: CollectionLeaseContext | None = None
    ) -> SignalPersistenceResult:
        """Persist or suppress an explainable Signal under repository idempotency/cooldown."""
        ...

    def claim_next_source_validation_job(
        self,
        worker_id: str,
        lease_for: timedelta,
    ) -> SourceValidationClaim | None:
        """Claim one API-enqueued durable source validation job."""
        ...

    def heartbeat_source_validation_job(
        self,
        claim: SourceValidationClaim,
        lease_for: timedelta,
    ) -> None:
        """Extend a fenced source validation lease."""
        ...

    def complete_source_validation_job(
        self,
        claim: SourceValidationClaim,
        source_status: str,
        health_error_code: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Complete a source validation with a public terminal source status."""
        ...

    def fail_source_validation_job(
        self,
        claim: SourceValidationClaim,
        failure_code: str,
        reason: str,
    ) -> None:
        """Fail a source validation job after a worker-side terminal exception."""
        ...

    def get_research_run(self, run_id: str) -> ResearchRun:
        """Fetch a deterministic ResearchRun."""
        ...

    def claim_next_research_run_command(
        self,
        worker_id: str,
        lease_for: timedelta,
    ) -> ResearchRunClaim | None:
        """Return one queued ResearchRun claim with a fenced worker attempt token."""
        ...

    def get_content_versions_for_research_run(self, run_id: str) -> list[ContentVersion]:
        """Return frozen ContentVersions for a deterministic ResearchRun."""
        ...

    def heartbeat_research_run(
        self,
        run_id: str,
        worker_attempt_id: str,
        now: datetime,
        lease_for: timedelta,
    ) -> None:
        """Extend a claimed ResearchRun lease."""
        ...

    def transition_research_run(
        self,
        run_id: str,
        state: ResearchRunState,
        worker_attempt_id: str | None = None,
    ) -> None:
        """Transition a ResearchRun state."""
        ...

    def append_run_event(
        self, run_id: str, event_type: str, payload: dict[str, Any], trace_id: str
    ) -> RunEvent:
        """Append a durable, sequence-ordered RunEvent."""
        ...

    def persist_research_proposals(
        self,
        run_id: str,
        evidence: list[EvidenceProposal],
        claims: list[ClaimVersionProposal],
        synthesis: SynthesisProposal | None,
        worker_attempt_id: str | None = None,
    ) -> None:
        """Persist deterministic proposals only; Brief creation is an API/domain command."""
        ...
