"""Frozen pre-release head schema and PostgreSQL workspace RLS.

Revision ID: 20260715_0001
Revises: None

This revision is a static current-head baseline for the pre-release repository.
Historical revisions must never import mutable application ORM metadata: a future
model or table must be introduced by a new Alembic revision and receive explicit
RLS and grants there.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260715_0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA_TABLES = (
    "idempotency_records",
    "workspaces",
    "audit_logs",
    "projects",
    "source_connections",
    "workspace_members",
    "content_items",
    "import_sessions",
    "source_validation_jobs",
    "watchlists",
    "collection_runs",
    "collection_schedules",
    "signals",
    "transfer_consent_records",
    "import_finalization_jobs",
    "import_manifests",
    "investigations",
    "upload_grants",
    "decision_briefs",
    "investigation_scope_versions",
    "investigation_syntheses",
    "raw_content_items",
    "content_versions",
    "investigation_synthesis_versions",
    "research_runs",
    "claims",
    "evidence",
    "import_manifest_content_versions",
    "run_events",
    "signal_evidence",
    "synthesis_reviews",
    "claim_versions",
    "decision_brief_versions",
    "evidence_reviews",
    "brief_exports",
    "claim_evidence",
    "claim_reviews",
    "decision_brief_freshness_records",
    "decision_brief_readiness_reviews",
)

TENANT_TABLES = (
    "audit_logs",
    "projects",
    "source_connections",
    "content_items",
    "import_sessions",
    "source_validation_jobs",
    "watchlists",
    "collection_runs",
    "collection_schedules",
    "signals",
    "transfer_consent_records",
    "import_finalization_jobs",
    "import_manifests",
    "investigations",
    "upload_grants",
    "decision_briefs",
    "investigation_scope_versions",
    "investigation_syntheses",
    "raw_content_items",
    "content_versions",
    "investigation_synthesis_versions",
    "research_runs",
    "claims",
    "evidence",
    "import_manifest_content_versions",
    "run_events",
    "signal_evidence",
    "synthesis_reviews",
    "claim_versions",
    "decision_brief_versions",
    "evidence_reviews",
    "brief_exports",
    "claim_evidence",
    "claim_reviews",
    "decision_brief_freshness_records",
    "decision_brief_readiness_reviews",
)

APPEND_ONLY_TABLES = (
    "transfer_consent_records",
    "import_manifest_content_versions",
    "import_manifests",
    "raw_content_items",
    "content_versions",
    "investigation_scope_versions",
    "run_events",
    "evidence",
    "evidence_reviews",
    "claim_versions",
    "claim_evidence",
    "claim_reviews",
    "investigation_synthesis_versions",
    "synthesis_reviews",
    "decision_brief_versions",
    "decision_brief_readiness_reviews",
    "decision_brief_freshness_records",
    "brief_exports",
    "audit_logs",
)


def _create_schema() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("workspace_scope", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("route", sa.String(length=512), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=96), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("owner_token", sa.String(length=36), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_scope", "principal_id", "route", "idempotency_key"),
    )
    op.create_index(
        op.f("ix_idempotency_records_state"), "idempotency_records", ["state"], unique=False
    )
    op.create_table(
        "workspaces",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("data_region", sa.String(length=32), nullable=False),
        sa.Column("retention_policy_version", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("before_digest", sa.String(length=96), nullable=True),
        sa.Column("after_digest", sa.String(length=96), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_actor_id"), "audit_logs", ["actor_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_request_id"), "audit_logs", ["request_id"], unique=False)
    op.create_index(
        op.f("ix_audit_logs_workspace_id"), "audit_logs", ["workspace_id"], unique=False
    )
    op.create_table(
        "projects",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_projects_workspace_id"), "projects", ["workspace_id"], unique=False)
    op.create_table(
        "source_connections",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("runtime", sa.String(length=32), nullable=False),
        sa.Column("connector_type", sa.String(length=64), nullable=False),
        sa.Column("connector_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("credential_ref", sa.String(length=250), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("cadence", sa.String(length=32), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness_state", sa.String(length=24), nullable=False),
        sa.Column("health_state", sa.String(length=32), nullable=False),
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("health_error_code", sa.String(length=80), nullable=True),
        sa.Column("data_scope", sa.String(length=40), nullable=False),
        sa.Column("approved_by", sa.String(length=36), nullable=True),
        sa.Column("current_import_manifest_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.CheckConstraint(
            "(source_kind = 'imported_dataset' AND runtime = 'static_import') OR "
            "(source_kind = 'cloud' AND runtime = 'cloud') OR "
            "(source_kind = 'local' AND runtime = 'mac_device')",
            name="source_kind_runtime_match",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_source_connections_workspace_id"),
        "source_connections",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id"),
    )
    op.create_index(
        op.f("ix_workspace_members_user_id"), "workspace_members", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_workspace_members_workspace_id"),
        "workspace_members",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "content_items",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("source_connection_id", sa.String(length=36), nullable=False),
        sa.Column("source_item_id", sa.String(length=255), nullable=False),
        sa.Column("canonical_url", sa.String(length=1024), nullable=True),
        sa.Column("identity_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("duplicate_cluster_id", sa.String(length=36), nullable=True),
        sa.Column("independence_group_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_connection_id"],
            ["source_connections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "source_connection_id", "identity_key"),
    )
    op.create_index(
        op.f("ix_content_items_duplicate_cluster_id"),
        "content_items",
        ["duplicate_cluster_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_items_independence_group_id"),
        "content_items",
        ["independence_group_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_items_source_connection_id"),
        "content_items",
        ["source_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_items_workspace_id"), "content_items", ["workspace_id"], unique=False
    )
    op.create_table(
        "import_sessions",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("source_connection_id", sa.String(length=36), nullable=False),
        sa.Column("expected_source_row_version", sa.Integer(), nullable=False),
        sa.Column("expected_current_import_manifest_id", sa.String(length=36), nullable=True),
        sa.Column("local_manifest_digest", sa.String(length=96), nullable=False),
        sa.Column("file_digest", sa.String(length=96), nullable=False),
        sa.Column("expected_upload_digest", sa.String(length=96), nullable=False),
        sa.Column("client_file_name", sa.String(length=255), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("selected_scope_json", sa.JSON(), nullable=False),
        sa.Column("selected_scope_digest", sa.String(length=96), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("uploaded_object_key", sa.String(length=512), nullable=True),
        sa.Column("uploaded_object_digest", sa.String(length=96), nullable=True),
        sa.Column("terminal_manifest_id", sa.String(length=36), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_connection_id"],
            ["source_connections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_import_sessions_source_connection_id"),
        "import_sessions",
        ["source_connection_id"],
        unique=False,
    )
    op.create_index(op.f("ix_import_sessions_state"), "import_sessions", ["state"], unique=False)
    op.create_index(
        op.f("ix_import_sessions_workspace_id"), "import_sessions", ["workspace_id"], unique=False
    )
    op.create_index(
        "uq_active_import_per_source",
        "import_sessions",
        ["source_connection_id"],
        unique=True,
        sqlite_where=sa.text(
            "state IN ('draft','consented','uploaded','validating') "
            "OR (state = 'failed' AND retryable = 1)"
        ),
        postgresql_where=sa.text(
            "state IN ('draft','consented','uploaded','validating') "
            "OR (state = 'failed' AND retryable IS TRUE)"
        ),
    )
    op.create_table(
        "source_validation_jobs",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("source_connection_id", sa.String(length=36), nullable=False),
        sa.Column("command", sa.String(length=24), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("expected_source_row_version", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_owner_token", sa.String(length=96), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_version", sa.Integer(), nullable=False),
        sa.Column("result_source_status", sa.String(length=32), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.CheckConstraint(
            "command IN ('health_check', 'reconnect')", name="source_validation_command_closed"
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'claimed', 'completed', 'failed')",
            name="source_validation_state_closed",
        ),
        sa.ForeignKeyConstraint(
            ["source_connection_id"],
            ["source_connections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_source_validation_idempotency",
        ),
    )
    op.create_index(
        op.f("ix_source_validation_jobs_source_connection_id"),
        "source_validation_jobs",
        ["source_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_validation_jobs_state"), "source_validation_jobs", ["state"], unique=False
    )
    op.create_index(
        op.f("ix_source_validation_jobs_workspace_id"),
        "source_validation_jobs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "uq_active_source_validation_job",
        "source_validation_jobs",
        ["workspace_id", "source_connection_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('queued','claimed')"),
        postgresql_where=sa.text("state IN ('queued','claimed')"),
    )
    op.create_table(
        "watchlists",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("rules_version", sa.Integer(), nullable=False),
        sa.Column("rules_json", sa.JSON(), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_watchlists_project_id"), "watchlists", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_watchlists_workspace_id"), "watchlists", ["workspace_id"], unique=False
    )
    op.create_table(
        "collection_runs",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("watchlist_id", sa.String(length=36), nullable=False),
        sa.Column("source_connection_id", sa.String(length=36), nullable=False),
        sa.Column("stable_key", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("cadence", sa.String(length=64), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("backoff_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_window_json", sa.JSON(), nullable=False),
        sa.Column("counters_json", sa.JSON(), nullable=False),
        sa.Column("partial_success", sa.Boolean(), nullable=False),
        sa.Column("freshness_json", sa.JSON(), nullable=False),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_connection_id"],
            ["source_connections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_id"],
            ["watchlists.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "stable_key", "attempt"),
    )
    op.create_index(
        op.f("ix_collection_runs_source_connection_id"),
        "collection_runs",
        ["source_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_runs_stable_key"), "collection_runs", ["stable_key"], unique=False
    )
    op.create_index(
        op.f("ix_collection_runs_watchlist_id"), "collection_runs", ["watchlist_id"], unique=False
    )
    op.create_index(
        op.f("ix_collection_runs_workspace_id"), "collection_runs", ["workspace_id"], unique=False
    )
    op.create_table(
        "collection_schedules",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("source_connection_id", sa.String(length=36), nullable=False),
        sa.Column("watchlist_id", sa.String(length=36), nullable=False),
        sa.Column("query_json", sa.JSON(), nullable=False),
        sa.Column("cadence_seconds", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("misfire_policy", sa.String(length=24), nullable=False),
        sa.Column("catch_up", sa.Boolean(), nullable=False),
        sa.Column("overlap_policy", sa.String(length=24), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("lease_owner_token", sa.String(length=96), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_attempt", sa.Integer(), nullable=False),
        sa.Column("lease_fencing_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_connection_id"],
            ["source_connections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["watchlist_id"],
            ["watchlists.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "watchlist_id", "source_connection_id"),
    )
    op.create_index(
        op.f("ix_collection_schedules_next_run_at"),
        "collection_schedules",
        ["next_run_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_schedules_source_connection_id"),
        "collection_schedules",
        ["source_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_schedules_watchlist_id"),
        "collection_schedules",
        ["watchlist_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_collection_schedules_workspace_id"),
        "collection_schedules",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "signals",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("watchlist_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("detector_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("window_json", sa.JSON(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("dimensions_json", sa.JSON(), nullable=False),
        sa.Column("disposition_json", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["watchlist_id"],
            ["watchlists.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_signals_watchlist_id"), "signals", ["watchlist_id"], unique=False)
    op.create_index(op.f("ix_signals_workspace_id"), "signals", ["workspace_id"], unique=False)
    op.create_table(
        "transfer_consent_records",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("import_session_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("local_manifest_digest", sa.String(length=96), nullable=False),
        sa.Column("file_digest", sa.String(length=96), nullable=False),
        sa.Column("expected_upload_digest", sa.String(length=96), nullable=False),
        sa.Column("selected_scope_json", sa.JSON(), nullable=False),
        sa.Column("selected_scope_digest", sa.String(length=96), nullable=False),
        sa.Column("destination_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("upload_object_scope", sa.JSON(), nullable=False),
        sa.Column("model_egress_authorization", sa.String(length=24), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_session_id"],
            ["import_sessions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_transfer_consent_records_import_session_id"),
        "transfer_consent_records",
        ["import_session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_transfer_consent_records_workspace_id"),
        "transfer_consent_records",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "import_finalization_jobs",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("import_session_id", sa.String(length=36), nullable=False),
        sa.Column("expected_session_row_version", sa.Integer(), nullable=False),
        sa.Column("expected_source_row_version", sa.Integer(), nullable=False),
        sa.Column("expected_current_import_manifest_id", sa.String(length=36), nullable=True),
        sa.Column("consent_record_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("result_manifest_id", sa.String(length=36), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("claimed_by", sa.String(length=100), nullable=True),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["consent_record_id"],
            ["transfer_consent_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["import_session_id"],
            ["import_sessions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_session_id"),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
    )
    op.create_index(
        op.f("ix_import_finalization_jobs_import_session_id"),
        "import_finalization_jobs",
        ["import_session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_import_finalization_jobs_state"),
        "import_finalization_jobs",
        ["state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_import_finalization_jobs_workspace_id"),
        "import_finalization_jobs",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "import_manifests",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("import_session_id", sa.String(length=36), nullable=False),
        sa.Column("source_connection_id", sa.String(length=36), nullable=False),
        sa.Column("file_digest", sa.String(length=96), nullable=False),
        sa.Column("uploaded_object_key", sa.String(length=512), nullable=False),
        sa.Column("uploaded_object_digest", sa.String(length=96), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("selected_scope_json", sa.JSON(), nullable=False),
        sa.Column("selected_scope_digest", sa.String(length=96), nullable=False),
        sa.Column("consent_record_id", sa.String(length=36), nullable=False),
        sa.Column("normalized_payload_digest", sa.String(length=96), nullable=False),
        sa.Column("content_count", sa.Integer(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["consent_record_id"],
            ["transfer_consent_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["import_session_id"],
            ["import_sessions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_connection_id"],
            ["source_connections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_session_id"),
    )
    op.create_index(
        op.f("ix_import_manifests_source_connection_id"),
        "import_manifests",
        ["source_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_import_manifests_workspace_id"), "import_manifests", ["workspace_id"], unique=False
    )
    op.create_table(
        "investigations",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("current_scope_version_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("current_synthesis_id", sa.String(length=36), nullable=True),
        sa.Column("decision_brief_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_investigations_project_id"), "investigations", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_investigations_signal_id"), "investigations", ["signal_id"], unique=False
    )
    op.create_index(
        op.f("ix_investigations_workspace_id"), "investigations", ["workspace_id"], unique=False
    )
    op.create_table(
        "upload_grants",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("import_session_id", sa.String(length=36), nullable=False),
        sa.Column("consent_record_id", sa.String(length=36), nullable=False),
        sa.Column("token_digest", sa.String(length=96), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("max_bytes", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_size_bytes", sa.Integer(), nullable=True),
        sa.Column("observed_media_type", sa.String(length=100), nullable=True),
        sa.Column("observed_digest", sa.String(length=96), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["consent_record_id"],
            ["transfer_consent_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["import_session_id"],
            ["import_sessions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consent_record_id"),
        sa.UniqueConstraint("import_session_id"),
        sa.UniqueConstraint("object_key"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index(
        op.f("ix_upload_grants_workspace_id"), "upload_grants", ["workspace_id"], unique=False
    )
    op.create_table(
        "decision_briefs",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("investigation_id", sa.String(length=36), nullable=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("decision_outcome", sa.Text(), nullable=True),
        sa.Column("next_checkpoint_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("investigation_id"),
    )
    op.create_index(
        op.f("ix_decision_briefs_investigation_id"),
        "decision_briefs",
        ["investigation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_briefs_workspace_id"), "decision_briefs", ["workspace_id"], unique=False
    )
    op.create_table(
        "investigation_scope_versions",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("investigation_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("decision_question", sa.Text(), nullable=False),
        sa.Column("source_scope_json", sa.JSON(), nullable=False),
        sa.Column("time_range_json", sa.JSON(), nullable=False),
        sa.Column("budget_json", sa.JSON(), nullable=False),
        sa.Column("stop_conditions", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("investigation_id", "version_number"),
    )
    op.create_index(
        op.f("ix_investigation_scope_versions_investigation_id"),
        "investigation_scope_versions",
        ["investigation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_investigation_scope_versions_workspace_id"),
        "investigation_scope_versions",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "investigation_syntheses",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("investigation_id", sa.String(length=36), nullable=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("investigation_id"),
    )
    op.create_index(
        op.f("ix_investigation_syntheses_investigation_id"),
        "investigation_syntheses",
        ["investigation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_investigation_syntheses_workspace_id"),
        "investigation_syntheses",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "raw_content_items",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("import_manifest_id", sa.String(length=36), nullable=True),
        sa.Column("collection_run_id", sa.String(length=36), nullable=True),
        sa.Column("source_connection_id", sa.String(length=36), nullable=False),
        sa.Column("source_external_id", sa.String(length=255), nullable=False),
        sa.Column("raw_snapshot_uri", sa.String(length=512), nullable=False),
        sa.Column("raw_digest", sa.String(length=96), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.CheckConstraint(
            "(import_manifest_id IS NOT NULL AND collection_run_id IS NULL) OR "
            "(import_manifest_id IS NULL AND collection_run_id IS NOT NULL)",
            name="raw_content_exactly_one_origin",
        ),
        sa.ForeignKeyConstraint(
            ["collection_run_id"],
            ["collection_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["import_manifest_id"],
            ["import_manifests.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_connection_id"],
            ["source_connections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_raw_content_items_collection_run_id"),
        "raw_content_items",
        ["collection_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_raw_content_items_import_manifest_id"),
        "raw_content_items",
        ["import_manifest_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_raw_content_items_source_connection_id"),
        "raw_content_items",
        ["source_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_raw_content_items_workspace_id"),
        "raw_content_items",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "content_versions",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("content_item_id", sa.String(length=36), nullable=False),
        sa.Column("source_connection_id", sa.String(length=36), nullable=False),
        sa.Column("raw_content_item_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(length=96), nullable=False),
        sa.Column("normalized_title", sa.String(length=500), nullable=False),
        sa.Column("normalized_body", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_snapshot_uri", sa.String(length=512), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("availability", sa.String(length=24), nullable=False),
        sa.Column("availability_last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("availability_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_item_id"],
            ["content_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["raw_content_item_id"],
            ["raw_content_items.id"],
        ),
        sa.ForeignKeyConstraint(
            ["source_connection_id"],
            ["source_connections.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_item_id", "content_digest"),
        sa.UniqueConstraint("content_item_id", "version_number"),
    )
    op.create_index(
        op.f("ix_content_versions_content_digest"),
        "content_versions",
        ["content_digest"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_versions_content_item_id"),
        "content_versions",
        ["content_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_versions_raw_content_item_id"),
        "content_versions",
        ["raw_content_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_versions_source_connection_id"),
        "content_versions",
        ["source_connection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_content_versions_workspace_id"), "content_versions", ["workspace_id"], unique=False
    )
    op.create_table(
        "investigation_synthesis_versions",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("synthesis_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("verified_claim_version_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("claim_review_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("generation_method", sa.String(length=24), nullable=False),
        sa.Column("generator_version", sa.String(length=64), nullable=False),
        sa.Column("model_prompt_refs_json", sa.JSON(), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("business_implications", sa.JSON(), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("provenance_digest", sa.String(length=96), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["synthesis_id"],
            ["investigation_syntheses.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("synthesis_id", "version_number"),
    )
    op.create_index(
        op.f("ix_investigation_synthesis_versions_synthesis_id"),
        "investigation_synthesis_versions",
        ["synthesis_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_investigation_synthesis_versions_workspace_id"),
        "investigation_synthesis_versions",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "research_runs",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("investigation_id", sa.String(length=36), nullable=False),
        sa.Column("investigation_scope_version_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("graph_version", sa.String(length=64), nullable=False),
        sa.Column("run_input_manifest_json", sa.JSON(), nullable=False),
        sa.Column("run_input_manifest_digest", sa.String(length=96), nullable=False),
        sa.Column("budget_json", sa.JSON(), nullable=False),
        sa.Column("used_cost", sa.Float(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("initiated_by", sa.String(length=36), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("latest_sequence", sa.Integer(), nullable=False),
        sa.Column("worker_claimed_by", sa.String(length=100), nullable=True),
        sa.Column("worker_attempt_id", sa.String(length=100), nullable=True),
        sa.Column("worker_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_fencing_version", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["investigation_scope_version_id"],
            ["investigation_scope_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_research_runs_investigation_id"),
        "research_runs",
        ["investigation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_research_runs_state"), "research_runs", ["state"], unique=False)
    op.create_index(
        op.f("ix_research_runs_workspace_id"), "research_runs", ["workspace_id"], unique=False
    )
    op.create_table(
        "claims",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("investigation_id", sa.String(length=36), nullable=False),
        sa.Column("research_run_id", sa.String(length=36), nullable=False),
        sa.Column("current_version_id", sa.String(length=36), nullable=True),
        sa.Column("aggregate_status", sa.String(length=24), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_claims_investigation_id"), "claims", ["investigation_id"], unique=False
    )
    op.create_index(op.f("ix_claims_research_run_id"), "claims", ["research_run_id"], unique=False)
    op.create_index(op.f("ix_claims_workspace_id"), "claims", ["workspace_id"], unique=False)
    op.create_table(
        "evidence",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("investigation_id", sa.String(length=36), nullable=False),
        sa.Column("research_run_id", sa.String(length=36), nullable=False),
        sa.Column("content_version_id", sa.String(length=36), nullable=False),
        sa.Column("quote_start", sa.Integer(), nullable=False),
        sa.Column("quote_end", sa.Integer(), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("quote_text_digest", sa.String(length=96), nullable=False),
        sa.Column("stance", sa.String(length=16), nullable=False),
        sa.Column("relevance", sa.Float(), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False),
        sa.Column("independence", sa.Float(), nullable=False),
        sa.Column("recency", sa.Float(), nullable=False),
        sa.Column("specificity", sa.Float(), nullable=False),
        sa.Column("extraction_method", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_version_id"],
            ["content_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evidence_content_version_id"), "evidence", ["content_version_id"], unique=False
    )
    op.create_index(
        op.f("ix_evidence_investigation_id"), "evidence", ["investigation_id"], unique=False
    )
    op.create_index(
        op.f("ix_evidence_research_run_id"), "evidence", ["research_run_id"], unique=False
    )
    op.create_index(op.f("ix_evidence_workspace_id"), "evidence", ["workspace_id"], unique=False)
    op.create_table(
        "import_manifest_content_versions",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("import_manifest_id", sa.String(length=36), nullable=False),
        sa.Column("content_version_id", sa.String(length=36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_version_id"],
            ["content_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["import_manifest_id"],
            ["import_manifests.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("import_manifest_id", "content_version_id"),
        sa.UniqueConstraint("import_manifest_id", "ordinal"),
    )
    op.create_index(
        op.f("ix_import_manifest_content_versions_content_version_id"),
        "import_manifest_content_versions",
        ["content_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_import_manifest_content_versions_import_manifest_id"),
        "import_manifest_content_versions",
        ["import_manifest_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_import_manifest_content_versions_workspace_id"),
        "import_manifest_content_versions",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_manifest_content_version",
        "import_manifest_content_versions",
        ["content_version_id", "import_manifest_id"],
        unique=False,
    )
    op.create_table(
        "run_events",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("investigation_id", sa.String(length=36), nullable=False),
        sa.Column("research_run_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=96), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["investigation_id"],
            ["investigations.id"],
        ),
        sa.ForeignKeyConstraint(
            ["research_run_id"],
            ["research_runs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
        sa.UniqueConstraint("research_run_id", "idempotency_key"),
        sa.UniqueConstraint("research_run_id", "sequence"),
    )
    op.create_index(
        op.f("ix_run_events_research_run_id"), "run_events", ["research_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_run_events_workspace_id"), "run_events", ["workspace_id"], unique=False
    )
    op.create_table(
        "signal_evidence",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("content_version_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("independence_group_id", sa.String(length=36), nullable=True),
        sa.Column("contribution", sa.Float(), nullable=False),
        sa.Column("added_by", sa.String(length=36), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["content_version_id"],
            ["content_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", "content_version_id"),
    )
    op.create_index(
        op.f("ix_signal_evidence_independence_group_id"),
        "signal_evidence",
        ["independence_group_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_signal_evidence_signal_id"), "signal_evidence", ["signal_id"], unique=False
    )
    op.create_index(
        op.f("ix_signal_evidence_workspace_id"), "signal_evidence", ["workspace_id"], unique=False
    )
    op.create_table(
        "synthesis_reviews",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("synthesis_version_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["synthesis_version_id"],
            ["investigation_synthesis_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_synthesis_reviews_synthesis_version_id"),
        "synthesis_reviews",
        ["synthesis_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_synthesis_reviews_workspace_id"),
        "synthesis_reviews",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "claim_versions",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("claim_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("claim_type", sa.String(length=40), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("confidence_inputs_json", sa.JSON(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("confidence_level", sa.String(length=16), nullable=False),
        sa.Column("confidence_policy_version", sa.String(length=64), nullable=False),
        sa.Column("confidence_input_digest", sa.String(length=96), nullable=False),
        sa.Column("calibration_status", sa.String(length=24), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        sa.Column("generation_method", sa.String(length=24), nullable=False),
        sa.Column("generator_version", sa.String(length=64), nullable=False),
        sa.Column("suggestion_origin", sa.String(length=32), nullable=False),
        sa.Column("model_run_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["claims.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_id", "version_number"),
    )
    op.create_index(
        op.f("ix_claim_versions_claim_id"), "claim_versions", ["claim_id"], unique=False
    )
    op.create_index(
        op.f("ix_claim_versions_workspace_id"), "claim_versions", ["workspace_id"], unique=False
    )
    op.create_table(
        "decision_brief_versions",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("decision_brief_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("synthesis_version_id", sa.String(length=36), nullable=False),
        sa.Column("synthesis_review_id", sa.String(length=36), nullable=False),
        sa.Column("block_document", sa.JSON(), nullable=False),
        sa.Column("reference_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("template_version", sa.String(length=64), nullable=False),
        sa.Column("human_edit_digest", sa.String(length=96), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_brief_id"],
            ["decision_briefs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["synthesis_review_id"],
            ["synthesis_reviews.id"],
        ),
        sa.ForeignKeyConstraint(
            ["synthesis_version_id"],
            ["investigation_synthesis_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_brief_id", "version_number"),
    )
    op.create_index(
        op.f("ix_decision_brief_versions_decision_brief_id"),
        "decision_brief_versions",
        ["decision_brief_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_brief_versions_workspace_id"),
        "decision_brief_versions",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "evidence_reviews",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_evidence_reviews_evidence_id"), "evidence_reviews", ["evidence_id"], unique=False
    )
    op.create_index(
        op.f("ix_evidence_reviews_workspace_id"), "evidence_reviews", ["workspace_id"], unique=False
    )
    op.create_table(
        "brief_exports",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("decision_brief_version_id", sa.String(length=36), nullable=False),
        sa.Column("export_type", sa.String(length=64), nullable=False),
        sa.Column("destination", sa.String(length=64), nullable=False),
        sa.Column("selection_manifest_json", sa.JSON(), nullable=False),
        sa.Column("reference_digest", sa.String(length=96), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("template_version", sa.String(length=64), nullable=False),
        sa.Column("rendered_snapshot_uri", sa.String(length=512), nullable=False),
        sa.Column("output_digest", sa.String(length=96), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_brief_version_id"],
            ["decision_brief_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_brief_exports_decision_brief_version_id"),
        "brief_exports",
        ["decision_brief_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_brief_exports_workspace_id"), "brief_exports", ["workspace_id"], unique=False
    )
    op.create_table(
        "claim_evidence",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("claim_version_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("stance", sa.String(length=16), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("linked_by", sa.String(length=36), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["claim_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("claim_version_id", "evidence_id"),
    )
    op.create_index(
        op.f("ix_claim_evidence_claim_version_id"),
        "claim_evidence",
        ["claim_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_evidence_evidence_id"), "claim_evidence", ["evidence_id"], unique=False
    )
    op.create_index(
        op.f("ix_claim_evidence_workspace_id"), "claim_evidence", ["workspace_id"], unique=False
    )
    op.create_table(
        "claim_reviews",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("claim_version_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("claim_evidence_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("evidence_review_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_digest", sa.String(length=96), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_version_id"],
            ["claim_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_claim_reviews_claim_version_id"),
        "claim_reviews",
        ["claim_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_claim_reviews_workspace_id"), "claim_reviews", ["workspace_id"], unique=False
    )
    op.create_table(
        "decision_brief_freshness_records",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("decision_brief_version_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("affected_reference_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_brief_version_id"],
            ["decision_brief_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_decision_brief_freshness_records_decision_brief_version_id"),
        "decision_brief_freshness_records",
        ["decision_brief_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_brief_freshness_records_workspace_id"),
        "decision_brief_freshness_records",
        ["workspace_id"],
        unique=False,
    )
    op.create_table(
        "decision_brief_readiness_reviews",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("decision_brief_version_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("checklist_digest", sa.String(length=96), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("data_authenticity", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_brief_version_id"],
            ["decision_brief_versions.id"],
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_decision_brief_readiness_reviews_decision_brief_version_id"),
        "decision_brief_readiness_reviews",
        ["decision_brief_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_brief_readiness_reviews_workspace_id"),
        "decision_brief_readiness_reviews",
        ["workspace_id"],
        unique=False,
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN IF current_user IN ('glint_app', 'glint_api', 'glint_worker') THEN "
            "RAISE EXCEPTION 'Alembic must run as a migration owner, not a runtime role'; "
            "END IF; END $$"
        )

    _create_schema()
    if bind.dialect.name != "postgresql":
        return

    # Deployment owns LOGIN and credentials. Alembic never rotates a password
    # or silently creates an unprovisioned runtime identity.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM unnest(ARRAY['glint_app','glint_api','glint_worker']) "
        "AS required(role_name) WHERE NOT EXISTS (SELECT 1 FROM pg_roles "
        "WHERE rolname = required.role_name)) THEN "
        "RAISE EXCEPTION 'Deployment must provision glint_app, glint_api and glint_worker'; "
        "ELSIF EXISTS (SELECT 1 FROM pg_roles WHERE "
        "rolname IN ('glint_app','glint_api','glint_worker') AND "
        "(rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN "
        "RAISE EXCEPTION 'Glint runtime roles must be least-privilege roles'; "
        "ELSIF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'glint_app' AND rolcanlogin) THEN "
        "RAISE EXCEPTION 'glint_app compatibility role must be NOLOGIN'; "
        "ELSIF EXISTS (SELECT 1 FROM pg_roles WHERE "
        "rolname IN ('glint_api','glint_worker') AND NOT rolcanlogin) THEN "
        "RAISE EXCEPTION 'glint_api and glint_worker must be LOGIN roles'; "
        "END IF; END $$"
    )
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC, glint_app, glint_api, glint_worker")
    op.execute("GRANT USAGE ON SCHEMA public TO glint_api")
    for table in SCHEMA_TABLES:
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "{table}" TO glint_api')
    for table in APPEND_ONLY_TABLES:
        op.execute(f'REVOKE UPDATE, DELETE ON TABLE "{table}" FROM glint_api')

    # Workspace is the tenant root and therefore scopes by its primary key,
    # rather than by a non-existent workspace_id column.
    op.execute('ALTER TABLE "workspaces" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "workspaces" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "workspaces_workspace_scope" ON "workspaces" '
        "USING (id::text = current_setting('app.workspace_id', true)) "
        "WITH CHECK (id::text = current_setting('app.workspace_id', true) "
        "AND created_by::text = current_setting('app.principal_id', true))"
    )

    # Membership lookup supports principal listing with an explicit empty
    # workspace context and normal workspace-scoped authorization/bootstrap.
    op.execute('ALTER TABLE "workspace_members" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "workspace_members" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "workspace_members_principal_list" ON "workspace_members" '
        "FOR SELECT USING (user_id::text = current_setting('app.principal_id', true) "
        "AND (workspace_id::text = current_setting('app.workspace_id', true) "
        "OR current_setting('app.workspace_id', true) = ''))"
    )
    op.execute(
        'CREATE POLICY "workspace_members_owner_bootstrap" ON "workspace_members" '
        "FOR INSERT WITH CHECK ("
        "workspace_id::text = current_setting('app.workspace_id', true) "
        "AND user_id::text = current_setting('app.principal_id', true) "
        "AND role = 'owner' AND status = 'active')"
    )

    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_workspace_scope" ON "{table}" '
            "USING (workspace_id::text = current_setting('app.workspace_id', true)) "
            "WITH CHECK (workspace_id::text = current_setting('app.workspace_id', true))"
        )

    # IdempotencyRecord intentionally calls the tenant field workspace_scope.
    op.execute('ALTER TABLE "idempotency_records" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "idempotency_records" FORCE ROW LEVEL SECURITY')
    op.execute(
        'CREATE POLICY "idempotency_records_workspace_scope" '
        'ON "idempotency_records" '
        "USING (workspace_scope::text = current_setting('app.workspace_id', true) "
        "AND principal_id::text = current_setting('app.principal_id', true)) "
        "WITH CHECK (workspace_scope::text = current_setting('app.workspace_id', true) "
        "AND principal_id::text = current_setting('app.principal_id', true))"
    )


def downgrade() -> None:
    # Drop in the exact reverse of the frozen FK dependency order.
    for table in reversed(SCHEMA_TABLES):
        op.drop_table(table)
