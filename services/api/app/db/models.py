from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Identified:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Versioned:
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Authentic:
    data_authenticity: Mapped[str] = mapped_column(String(24), default="human_authored")


class Workspace(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "workspaces"
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="active")
    data_region: Mapped[str] = mapped_column(String(32), default="local")
    retention_policy_version: Mapped[str] = mapped_column(String(64), default="retention-v1")
    created_by: Mapped[str] = mapped_column(String(36))


class WorkspaceMember(Identified, Timestamped, Authentic, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(24), default="owner")
    status: Mapped[str] = mapped_column(String(24), default="active")


class Project(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "projects"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(24), default="active")
    created_by: Mapped[str] = mapped_column(String(36))


class QuantRepositoryState(Timestamped, Versioned, Authentic, Base):
    """Durable Phase 0 Quant aggregate and fixture-worker lease.

    Phase 0 deliberately keeps the synthetic aggregate in one JSON document so
    the contract can evolve without pretending that production market or
    execution tables exist. PostgreSQL remains authoritative and the row is
    workspace-scoped, versioned, and fenced for the deterministic worker.
    """

    __tablename__ = "quant_repository_states"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    research_memory_contract_version: Mapped[str] = mapped_column(
        String(64),
        default="quant-research-memory-v1",
        server_default=text("'quant-research-memory-v1'"),
        nullable=False,
    )
    evidence_replan_contract_marker: Mapped[str] = mapped_column(
        String(64),
        default="legacy-pre-p18",
        server_default=text("'legacy-pre-p18'"),
        nullable=False,
    )
    research_decision_contract_marker: Mapped[str] = mapped_column(
        String(64),
        default="legacy-pre-p19",
        server_default=text("'legacy-pre-p19'"),
        nullable=False,
    )
    fixture_state: Mapped[str | None] = mapped_column(String(48), nullable=True)
    fixture_input_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fixture_row_version: Mapped[int] = mapped_column(Integer, default=8)
    worker_lease_token: Mapped[str | None] = mapped_column(String(96), nullable=True)
    worker_lease_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    worker_lease_worker_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    worker_lease_attempt_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worker_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_fencing_version: Mapped[int] = mapped_column(Integer, default=0)


class PaperTradingState(Timestamped, Versioned, Base):
    """Workspace-scoped simulation state, deliberately separate from research."""

    __tablename__ = "paper_trading_states"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    contract_version: Mapped[str] = mapped_column(
        String(64),
        default="qurio-paper-v1",
        server_default=text("'qurio-paper-v1'"),
        nullable=False,
    )
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Watchlist(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "watchlists"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    rules_version: Mapped[int] = mapped_column(Integer, default=1)
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    owner_id: Mapped[str] = mapped_column(String(36))


class SourceConnection(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "source_connections"
    __table_args__ = (
        CheckConstraint(
            "(source_kind = 'imported_dataset' AND runtime = 'static_import') OR "
            "(source_kind = 'cloud' AND runtime = 'cloud') OR "
            "(source_kind = 'local' AND runtime = 'mac_device')",
            name="source_kind_runtime_match",
        ),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_kind: Mapped[str] = mapped_column(String(32))
    runtime: Mapped[str] = mapped_column(String(32))
    connector_type: Mapped[str] = mapped_column(String(64))
    connector_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="draft")
    credential_ref: Mapped[str | None] = mapped_column(String(250), nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cadence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freshness_state: Mapped[str] = mapped_column(String(24), default="never")
    health_state: Mapped[str] = mapped_column(String(32), default="unknown")
    health_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    health_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    data_scope: Mapped[str] = mapped_column(String(40), default="workspace_confidential")
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    current_import_manifest_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class SourceValidationJobRecord(Identified, Timestamped, Authentic, Base):
    __tablename__ = "source_validation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_source_validation_idempotency",
        ),
        CheckConstraint(
            "command IN ('health_check', 'reconnect')",
            name="source_validation_command_closed",
        ),
        CheckConstraint(
            "state IN ('queued', 'claimed', 'completed', 'failed')",
            name="source_validation_state_closed",
        ),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    source_connection_id: Mapped[str] = mapped_column(
        ForeignKey("source_connections.id"), index=True
    )
    command: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    expected_source_row_version: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner_token: Mapped[str | None] = mapped_column(String(96), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fencing_version: Mapped[int] = mapped_column(Integer, default=0)
    result_source_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


Index(
    "uq_active_source_validation_job",
    SourceValidationJobRecord.workspace_id,
    SourceValidationJobRecord.source_connection_id,
    unique=True,
    sqlite_where=text("state IN ('queued','claimed')"),
    postgresql_where=text("state IN ('queued','claimed')"),
)


class CollectionRun(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "collection_runs"
    __table_args__ = (UniqueConstraint("workspace_id", "stable_key", "attempt"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    watchlist_id: Mapped[str] = mapped_column(ForeignKey("watchlists.id"), index=True)
    source_connection_id: Mapped[str] = mapped_column(
        ForeignKey("source_connections.id"), index=True
    )
    stable_key: Mapped[str] = mapped_column(String(160), index=True)
    state: Mapped[str] = mapped_column(String(32), default="scheduled")
    cadence: Mapped[str] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    backoff_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_window_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    counters_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    partial_success: Mapped[bool] = mapped_column(Boolean, default=False)
    freshness_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CollectionSchedule(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "collection_schedules"
    __table_args__ = (UniqueConstraint("workspace_id", "watchlist_id", "source_connection_id"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    source_connection_id: Mapped[str] = mapped_column(
        ForeignKey("source_connections.id"), index=True
    )
    watchlist_id: Mapped[str] = mapped_column(ForeignKey("watchlists.id"), index=True)
    query_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cadence_seconds: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    misfire_policy: Mapped[str] = mapped_column(String(24), default="skip")
    catch_up: Mapped[bool] = mapped_column(Boolean, default=False)
    overlap_policy: Mapped[str] = mapped_column(String(24), default="skip")
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    lease_owner_token: Mapped[str | None] = mapped_column(String(96), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_attempt: Mapped[int] = mapped_column(Integer, default=0)
    lease_fencing_version: Mapped[int] = mapped_column(Integer, default=0)


class ImportSession(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "import_sessions"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    source_connection_id: Mapped[str] = mapped_column(
        ForeignKey("source_connections.id"), index=True
    )
    expected_source_row_version: Mapped[int] = mapped_column(Integer)
    expected_current_import_manifest_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    local_manifest_digest: Mapped[str] = mapped_column(String(96))
    file_digest: Mapped[str] = mapped_column(String(96))
    expected_upload_digest: Mapped[str] = mapped_column(String(96))
    client_file_name: Mapped[str] = mapped_column(String(255))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(100))
    parser_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    selected_scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    selected_scope_digest: Mapped[str] = mapped_column(String(96))
    state: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    uploaded_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    uploaded_object_digest: Mapped[str | None] = mapped_column(String(96), nullable=True)
    terminal_manifest_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(36))


Index(
    "uq_active_import_per_source",
    ImportSession.source_connection_id,
    unique=True,
    sqlite_where=text(
        "state IN ('draft','consented','uploaded','validating') "
        "OR (state = 'failed' AND retryable = 1)"
    ),
    postgresql_where=text(
        "state IN ('draft','consented','uploaded','validating') "
        "OR (state = 'failed' AND retryable IS TRUE)"
    ),
)


class TransferConsentRecord(Identified, Authentic, Base):
    __tablename__ = "transfer_consent_records"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    import_session_id: Mapped[str] = mapped_column(ForeignKey("import_sessions.id"), index=True)
    decision: Mapped[str] = mapped_column(String(16))
    local_manifest_digest: Mapped[str] = mapped_column(String(96))
    file_digest: Mapped[str] = mapped_column(String(96))
    expected_upload_digest: Mapped[str] = mapped_column(String(96))
    selected_scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    selected_scope_digest: Mapped[str] = mapped_column(String(96))
    destination_workspace_id: Mapped[str] = mapped_column(String(36))
    upload_object_scope: Mapped[dict[str, Any]] = mapped_column(JSON)
    model_egress_authorization: Mapped[str] = mapped_column(String(24), default="none")
    policy_version: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(String(36))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class UploadGrant(Identified, Base):
    __tablename__ = "upload_grants"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    import_session_id: Mapped[str] = mapped_column(ForeignKey("import_sessions.id"), unique=True)
    consent_record_id: Mapped[str] = mapped_column(
        ForeignKey("transfer_consent_records.id"), unique=True
    )
    token_digest: Mapped[str] = mapped_column(String(96), unique=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    max_bytes: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_media_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    observed_digest: Mapped[str | None] = mapped_column(String(96), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportFinalizationJobRecord(Identified, Timestamped, Authentic, Base):
    __tablename__ = "import_finalization_jobs"
    __table_args__ = (
        UniqueConstraint("import_session_id"),
        UniqueConstraint("workspace_id", "idempotency_key"),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    import_session_id: Mapped[str] = mapped_column(ForeignKey("import_sessions.id"), index=True)
    expected_session_row_version: Mapped[int] = mapped_column(Integer)
    expected_source_row_version: Mapped[int] = mapped_column(Integer)
    expected_current_import_manifest_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    consent_record_id: Mapped[str] = mapped_column(ForeignKey("transfer_consent_records.id"))
    actor_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    result_manifest_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ImportManifest(Identified, Authentic, Base):
    __tablename__ = "import_manifests"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    import_session_id: Mapped[str] = mapped_column(ForeignKey("import_sessions.id"), unique=True)
    source_connection_id: Mapped[str] = mapped_column(
        ForeignKey("source_connections.id"), index=True
    )
    file_digest: Mapped[str] = mapped_column(String(96))
    uploaded_object_key: Mapped[str] = mapped_column(String(512))
    uploaded_object_digest: Mapped[str] = mapped_column(String(96))
    parser_version: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(64))
    selected_scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    selected_scope_digest: Mapped[str] = mapped_column(String(96))
    consent_record_id: Mapped[str] = mapped_column(ForeignKey("transfer_consent_records.id"))
    normalized_payload_digest: Mapped[str] = mapped_column(String(96))
    content_count: Mapped[int] = mapped_column(Integer)
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportManifestContentVersion(Identified, Authentic, Base):
    __tablename__ = "import_manifest_content_versions"
    __table_args__ = (
        UniqueConstraint("import_manifest_id", "content_version_id"),
        UniqueConstraint("import_manifest_id", "ordinal"),
        Index("ix_manifest_content_version", "content_version_id", "import_manifest_id"),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    import_manifest_id: Mapped[str] = mapped_column(ForeignKey("import_manifests.id"), index=True)
    content_version_id: Mapped[str] = mapped_column(ForeignKey("content_versions.id"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class RawContentItem(Identified, Authentic, Base):
    __tablename__ = "raw_content_items"
    __table_args__ = (
        CheckConstraint(
            "(import_manifest_id IS NOT NULL AND collection_run_id IS NULL) OR "
            "(import_manifest_id IS NULL AND collection_run_id IS NOT NULL)",
            name="raw_content_exactly_one_origin",
        ),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    import_manifest_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_manifests.id"), index=True, nullable=True
    )
    collection_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("collection_runs.id"), index=True, nullable=True
    )
    source_connection_id: Mapped[str] = mapped_column(
        ForeignKey("source_connections.id"), index=True
    )
    source_external_id: Mapped[str] = mapped_column(String(255))
    raw_snapshot_uri: Mapped[str] = mapped_column(String(512))
    raw_digest: Mapped[str] = mapped_column(String(96))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentItem(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "content_items"
    __table_args__ = (UniqueConstraint("workspace_id", "source_connection_id", "identity_key"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    source_connection_id: Mapped[str] = mapped_column(
        ForeignKey("source_connections.id"), index=True
    )
    source_item_id: Mapped[str] = mapped_column(String(255))
    canonical_url: Mapped[str | None] = mapped_column(String(1_024), nullable=True)
    identity_key: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    duplicate_cluster_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    independence_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class ContentVersion(Identified, Authentic, Base):
    __tablename__ = "content_versions"
    __table_args__ = (
        UniqueConstraint("content_item_id", "version_number"),
        UniqueConstraint("content_item_id", "content_digest"),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    content_item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id"), index=True)
    source_connection_id: Mapped[str] = mapped_column(
        ForeignKey("source_connections.id"), index=True
    )
    raw_content_item_id: Mapped[str] = mapped_column(ForeignKey("raw_content_items.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    content_digest: Mapped[str] = mapped_column(String(96), index=True)
    normalized_title: Mapped[str] = mapped_column(String(500))
    normalized_body: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_snapshot_uri: Mapped[str] = mapped_column(String(512))
    parser_version: Mapped[str] = mapped_column(String(64))
    availability: Mapped[str] = mapped_column(String(24), default="captured", nullable=False)
    availability_last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    availability_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Signal(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "signals"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    watchlist_id: Mapped[str] = mapped_column(ForeignKey("watchlists.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    detector_version: Mapped[str] = mapped_column(String(64), default="import-signal-v1")
    status: Mapped[str] = mapped_column(String(24), default="new")
    window_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dimensions_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    disposition_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    explanation: Mapped[str] = mapped_column(Text)


class SignalEvidence(Identified, Authentic, Base):
    __tablename__ = "signal_evidence"
    __table_args__ = (UniqueConstraint("signal_id", "content_version_id"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), index=True)
    content_version_id: Mapped[str] = mapped_column(ForeignKey("content_versions.id"))
    role: Mapped[str] = mapped_column(String(24))
    independence_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    contribution: Mapped[float] = mapped_column(Float, default=1.0)
    added_by: Mapped[str] = mapped_column(String(36))


class Investigation(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "investigations"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signals.id"), index=True)
    current_scope_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    owner_id: Mapped[str] = mapped_column(String(36))
    current_synthesis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decision_brief_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class InvestigationScopeVersion(Identified, Authentic, Base):
    __tablename__ = "investigation_scope_versions"
    __table_args__ = (UniqueConstraint("investigation_id", "version_number"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    decision_question: Mapped[str] = mapped_column(Text)
    source_scope_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    time_range_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    budget_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    stop_conditions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(36))
    change_reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchRun(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "research_runs"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    investigation_scope_version_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_scope_versions.id")
    )
    state: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    graph_version: Mapped[str] = mapped_column(String(64), default="deterministic-import-v1")
    run_input_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    run_input_manifest_digest: Mapped[str] = mapped_column(String(96))
    budget_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    used_cost: Mapped[float] = mapped_column(Float, default=0.0)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    initiated_by: Mapped[str] = mapped_column(String(36))
    trace_id: Mapped[str] = mapped_column(String(64))
    latest_sequence: Mapped[int] = mapped_column(Integer, default=0)
    worker_claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    worker_attempt_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    worker_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    worker_fencing_version: Mapped[int] = mapped_column(Integer, default=0)


class RunEvent(Identified, Authentic, Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("research_run_id", "sequence"),
        UniqueConstraint("research_run_id", "idempotency_key"),
    )
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"))
    research_run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, default=new_id)
    idempotency_key: Mapped[str] = mapped_column(String(96))
    type: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    trace_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Evidence(Identified, Authentic, Base):
    __tablename__ = "evidence"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    research_run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), index=True)
    content_version_id: Mapped[str] = mapped_column(ForeignKey("content_versions.id"), index=True)
    quote_start: Mapped[int] = mapped_column(Integer)
    quote_end: Mapped[int] = mapped_column(Integer)
    quote_text: Mapped[str] = mapped_column(Text)
    quote_text_digest: Mapped[str] = mapped_column(String(96))
    stance: Mapped[str] = mapped_column(String(16))
    relevance: Mapped[float] = mapped_column(Float)
    reliability: Mapped[float] = mapped_column(Float)
    independence: Mapped[float] = mapped_column(Float)
    recency: Mapped[float] = mapped_column(Float)
    specificity: Mapped[float] = mapped_column(Float)
    extraction_method: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceReview(Identified, Authentic, Base):
    __tablename__ = "evidence_reviews"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), index=True)
    decision: Mapped[str] = mapped_column(String(16))
    reviewer_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Claim(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "claims"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    research_run_id: Mapped[str] = mapped_column(ForeignKey("research_runs.id"), index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    aggregate_status: Mapped[str] = mapped_column(String(24), default="proposed")
    owner_id: Mapped[str] = mapped_column(String(36))


class ClaimVersion(Identified, Authentic, Base):
    __tablename__ = "claim_versions"
    __table_args__ = (UniqueConstraint("claim_id", "version_number"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    claim_type: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    confidence_inputs_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_level: Mapped[str] = mapped_column(String(16))
    confidence_policy_version: Mapped[str] = mapped_column(
        String(64), default="claim-confidence-v2", nullable=False
    )
    confidence_input_digest: Mapped[str] = mapped_column(
        String(96), default="sha256:" + "0" * 64, nullable=False
    )
    calibration_status: Mapped[str] = mapped_column(String(24), default="uncalibrated")
    limitations: Mapped[list[str]] = mapped_column(JSON, default=list)
    generation_method: Mapped[str] = mapped_column(String(24), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(64), nullable=False)
    suggestion_origin: Mapped[str] = mapped_column(String(32), nullable=False)
    model_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClaimEvidence(Identified, Authentic, Base):
    __tablename__ = "claim_evidence"
    __table_args__ = (UniqueConstraint("claim_version_id", "evidence_id"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    claim_version_id: Mapped[str] = mapped_column(ForeignKey("claim_versions.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), index=True)
    stance: Mapped[str] = mapped_column(String(16))
    weight: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    linked_by: Mapped[str] = mapped_column(String(36))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ClaimReview(Identified, Authentic, Base):
    __tablename__ = "claim_reviews"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    claim_version_id: Mapped[str] = mapped_column(ForeignKey("claim_versions.id"), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    claim_evidence_snapshot_json: Mapped[list[str]] = mapped_column(JSON)
    evidence_review_snapshot_json: Mapped[list[str]] = mapped_column(JSON)
    snapshot_digest: Mapped[str] = mapped_column(String(96))
    reviewer_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InvestigationSynthesis(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "investigation_syntheses"
    __table_args__ = (UniqueConstraint("investigation_id"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class InvestigationSynthesisVersion(Identified, Authentic, Base):
    __tablename__ = "investigation_synthesis_versions"
    __table_args__ = (UniqueConstraint("synthesis_id", "version_number"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    synthesis_id: Mapped[str] = mapped_column(ForeignKey("investigation_syntheses.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    verified_claim_version_snapshot_json: Mapped[list[str]] = mapped_column(JSON)
    claim_review_snapshot_json: Mapped[list[str]] = mapped_column(JSON)
    generation_method: Mapped[str] = mapped_column(String(24))
    generator_version: Mapped[str] = mapped_column(String(64))
    model_prompt_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    executive_summary: Mapped[str] = mapped_column(Text)
    business_implications: Mapped[list[str]] = mapped_column(JSON)
    limitations: Mapped[list[str]] = mapped_column(JSON)
    provenance_digest: Mapped[str] = mapped_column(String(96))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SynthesisReview(Identified, Authentic, Base):
    __tablename__ = "synthesis_reviews"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    synthesis_version_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_synthesis_versions.id"), index=True
    )
    decision: Mapped[str] = mapped_column(String(16))
    reviewer_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(64))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DecisionBrief(Identified, Timestamped, Versioned, Authentic, Base):
    __tablename__ = "decision_briefs"
    __table_args__ = (UniqueConstraint("investigation_id"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="draft")
    owner_id: Mapped[str] = mapped_column(String(36))
    decision_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_checkpoint_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class DecisionBriefVersion(Identified, Authentic, Base):
    __tablename__ = "decision_brief_versions"
    __table_args__ = (UniqueConstraint("decision_brief_id", "version_number"),)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    decision_brief_id: Mapped[str] = mapped_column(ForeignKey("decision_briefs.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    synthesis_version_id: Mapped[str] = mapped_column(
        ForeignKey("investigation_synthesis_versions.id")
    )
    synthesis_review_id: Mapped[str] = mapped_column(ForeignKey("synthesis_reviews.id"))
    block_document: Mapped[dict[str, Any]] = mapped_column(JSON)
    reference_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    template_version: Mapped[str] = mapped_column(String(64))
    human_edit_digest: Mapped[str] = mapped_column(String(96))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DecisionBriefReadinessReview(Identified, Authentic, Base):
    __tablename__ = "decision_brief_readiness_reviews"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    decision_brief_version_id: Mapped[str] = mapped_column(
        ForeignKey("decision_brief_versions.id"), index=True
    )
    decision: Mapped[str] = mapped_column(String(32))
    reviewer_id: Mapped[str] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(64))
    checklist_digest: Mapped[str] = mapped_column(String(96))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DecisionBriefFreshnessRecord(Identified, Authentic, Base):
    __tablename__ = "decision_brief_freshness_records"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    decision_brief_version_id: Mapped[str] = mapped_column(
        ForeignKey("decision_brief_versions.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(24))
    affected_reference_snapshot_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    policy_version: Mapped[str] = mapped_column(String(64))
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BriefExport(Identified, Authentic, Base):
    __tablename__ = "brief_exports"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    decision_brief_version_id: Mapped[str] = mapped_column(
        ForeignKey("decision_brief_versions.id"), index=True
    )
    export_type: Mapped[str] = mapped_column(String(64))
    destination: Mapped[str] = mapped_column(String(64))
    selection_manifest_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    reference_digest: Mapped[str] = mapped_column(String(96))
    policy_version: Mapped[str] = mapped_column(String(64))
    template_version: Mapped[str] = mapped_column(String(64))
    rendered_snapshot_uri: Mapped[str] = mapped_column(String(512))
    output_digest: Mapped[str] = mapped_column(String(96))
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Identified, Authentic, Base):
    __tablename__ = "audit_logs"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str] = mapped_column(String(36))
    before_digest: Mapped[str | None] = mapped_column(String(96), nullable=True)
    after_digest: Mapped[str | None] = mapped_column(String(96), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IdempotencyRecord(Identified, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("workspace_scope", "principal_id", "route", "idempotency_key"),
    )
    workspace_scope: Mapped[str] = mapped_column(
        String(36), default="00000000-0000-0000-0000-000000000000"
    )
    principal_id: Mapped[str] = mapped_column(String(36))
    route: Mapped[str] = mapped_column(String(512))
    idempotency_key: Mapped[str] = mapped_column(String(36))
    request_fingerprint: Mapped[str] = mapped_column(String(96))
    state: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    owner_token: Mapped[str] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


APPEND_ONLY_MODELS = (
    TransferConsentRecord,
    ImportManifestContentVersion,
    ImportManifest,
    RawContentItem,
    ContentVersion,
    InvestigationScopeVersion,
    RunEvent,
    Evidence,
    EvidenceReview,
    ClaimVersion,
    ClaimEvidence,
    ClaimReview,
    InvestigationSynthesisVersion,
    SynthesisReview,
    DecisionBriefVersion,
    DecisionBriefReadinessReview,
    DecisionBriefFreshnessRecord,
    BriefExport,
    AuditLog,
)


def _reject_immutable_change(_mapper: Any, _connection: Any, target: Any) -> None:
    raise ValueError(f"{type(target).__name__} is append-only")


def _allow_only_content_availability_change(
    _mapper: Any, _connection: Any, target: ContentVersion
) -> None:
    allowed = {
        "availability",
        "availability_last_checked_at",
        "availability_reason",
    }
    changed = {
        attribute.key for attribute in sa_inspect(target).attrs if attribute.history.has_changes()
    }
    if not changed.issubset(allowed):
        raise ValueError("ContentVersion immutable content fields cannot be updated")


for immutable_model in APPEND_ONLY_MODELS:
    if immutable_model is ContentVersion:
        event.listen(immutable_model, "before_update", _allow_only_content_availability_change)
    else:
        event.listen(immutable_model, "before_update", _reject_immutable_change)
    event.listen(immutable_model, "before_delete", _reject_immutable_change)


def _restore_utc(target: Any, *_args: Any) -> None:
    """SQLite drops tzinfo; restore the declared UTC wire contract on load/refresh."""
    for column in target.__table__.columns:
        if isinstance(column.type, DateTime):
            value = getattr(target, column.name, None)
            if isinstance(value, datetime) and value.tzinfo is None:
                setattr(target, column.name, value.replace(tzinfo=UTC))


for mapper in Base.registry.mappers:
    event.listen(mapper.class_, "load", _restore_utc)
    event.listen(mapper.class_, "refresh", _restore_utc)
